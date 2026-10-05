from __future__ import annotations

import datetime as dt
import logging
import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import connections, transaction
from psycopg2.extras import Json

from geoflow_ops.services.s3_service import get_bucket_name, get_s3_client

from .changeset import (
    ChangesetUnavailable,
    _allocate_revisions,
    _complete_receipt,
    _ensure_project_state,
    _insert_change_log,
    _plain_value,
    _reserve_receipt,
    _uuid_text,
)
from .qgis_sync import SyncConflict, SyncRejected


SOURCE_TYPES = frozenset({"GNSS", "GPS", "TOTAL", "CSV", "XLSX", "OTHER"})
_EPSG = re.compile(r"^EPSG:(\d{3,6})$", re.I)
logger = logging.getLogger(__name__)

_POINT_FIELDS = frozenset({
    "id", "source_row_id", "raw_x", "raw_y", "raw_z", "raw_crs", "raw_code",
    "raw_geoid_model", "longitude", "latitude", "raw_data", "worker_id",
    "survey_date", "name", "code", "solution_info", "pdop", "antenna_height",
})


class SurveySourceNotFound(SyncRejected):
    pass


class SurveySourceDeleteBlocked(SyncRejected):
    def __init__(self, reason: str, precheck: dict[str, Any]):
        super().__init__(reason)
        self.reason = reason
        self.precheck = precheck


def _delete_reason(precheck: dict[str, Any]) -> str | None:
    links = precheck.get("links") or {}
    if int(links.get("LINKED") or 0):
        return "linked_survey_points"
    if int(links.get("MANUALLY_MODIFIED") or 0):
        return "manually_modified_links"
    if int(links.get("UNLINKED") or 0):
        return "unlinked_history"
    if int(precheck.get("child_version_count") or 0) or precheck.get("supersedes_id"):
        return "version_lineage"
    if int(precheck.get("version") or 0) != 1:
        return "version_lineage"
    if not precheck.get("is_active"):
        return "inactive_source"
    if int(precheck.get("shared_object_reference_count") or 0):
        return "shared_object"
    if precheck.get("object_key_valid") is False:
        return "invalid_object_key"
    return None


def _source_dict(row) -> dict[str, Any]:
    return {
        "id": str(row[0]), "project_id": str(row[1]), "source_group_id": str(row[2]),
        "supersedes_id": str(row[3]) if row[3] else None, "source_type": row[4],
        "original_file_name": row[5], "original_file_key": row[6],
        "imported_at": row[7].isoformat(), "imported_by": str(row[8]) if row[8] else None,
        "source_crs": row[9], "geoid_model": row[10],
        "calibration_info": row[11] or {}, "version": int(row[12]),
        "is_active": bool(row[13]), "note": row[14] or "",
        "point_count": int(row[15] or 0),
        "survey_date_from": row[16].isoformat() if row[16] else None,
        "survey_date_to": row[17].isoformat() if row[17] else None,
        "worker_count": int(row[18] or 0),
        "workers": row[19] or [],
    }


def list_survey_sources(alias: str, *, project_id: str, include_inactive: bool = False) -> list[dict[str, Any]]:
    with connections[alias].cursor() as cursor:
        cursor.execute(
            """
            SELECT src.id,src.project_id,src.source_group_id,src.supersedes_id,src.source_type,
                   original_file_name,original_file_key,imported_at,imported_by,
                   source_crs,geoid_model,calibration_info,version,is_active,note
                   ,count(s.id),min(s.survey_date),max(s.survey_date),
                   count(DISTINCT s.worker_id),
                   COALESCE(jsonb_agg(DISTINCT jsonb_build_object(
                       'id', ep.id::text, 'name', ep.name
                   )) FILTER (WHERE ep.id IS NOT NULL),'[]'::jsonb)
              FROM gis.survey_source src
              LEFT JOIN gis.survey s ON s.source_id=src.id
              LEFT JOIN hr.employee_profile ep ON ep.id=s.worker_id AND ep.is_deleted=false
             WHERE src.project_id=%s AND (%s OR src.is_active)
             GROUP BY src.id
             ORDER BY src.source_group_id,src.version DESC
            """,
            [project_id, include_inactive],
        )
        return [_source_dict(row) for row in cursor.fetchall()]


def survey_source_delete_precheck(
    alias: str, *, project_id: str, source_id: str, lock: bool = False
) -> dict[str, Any]:
    source_id = _uuid_text(source_id, "source_id")
    lock_sql = " FOR UPDATE" if lock else ""
    with connections[alias].cursor() as cursor:
        cursor.execute(
            f"""
            SELECT id::text,source_group_id::text,supersedes_id::text,version,is_active,
                   original_file_key
              FROM gis.survey_source
             WHERE id=%s AND project_id=%s{lock_sql}
            """,
            [source_id, project_id],
        )
        source = cursor.fetchone()
        if source is None:
            raise SurveySourceNotFound("survey source was not found")
        cursor.execute(
            """
            SELECT count(DISTINCT s.id),
                   count(*) FILTER (WHERE sl.link_status='LINKED'),
                   count(*) FILTER (WHERE sl.link_status='MANUALLY_MODIFIED'),
                   count(*) FILTER (WHERE sl.link_status='UNLINKED'),
                   count(DISTINCT (sl.layer_id,sl.target_id,COALESCE(sl.vertex_index,-1)))
              FROM gis.survey s
              LEFT JOIN gis.survey_link sl ON sl.survey_id=s.id
             WHERE s.project_id=%s AND s.source_id=%s
            """,
            [project_id, source_id],
        )
        counts = cursor.fetchone()
        cursor.execute(
            "SELECT count(*) FROM gis.survey_source WHERE project_id=%s AND supersedes_id=%s",
            [project_id, source_id],
        )
        child_versions = int(cursor.fetchone()[0])
        shared_objects = 0
        if source[5]:
            cursor.execute(
                "SELECT count(*) FROM gis.survey_source WHERE original_file_key=%s AND id<>%s",
                [source[5], source_id],
            )
            shared_objects = int(cursor.fetchone()[0])

    object_key = str(source[5] or "")
    expected_prefix = f"tenants/{alias}/gis/{project_id}/survey-sources/{source_id}/"
    result = {
        "source_id": source[0],
        "source_group_id": source[1],
        "supersedes_id": source[2],
        "version": int(source[3]),
        "is_active": bool(source[4]),
        "point_count": int(counts[0] or 0),
        "links": {
            "LINKED": int(counts[1] or 0),
            "MANUALLY_MODIFIED": int(counts[2] or 0),
            "UNLINKED": int(counts[3] or 0),
        },
        "linked_target_count": int(counts[4] or 0),
        "child_version_count": child_versions,
        "shared_object_reference_count": shared_objects,
        "has_archived_object": bool(object_key),
        "object_key_valid": not object_key or object_key.startswith(expected_prefix),
    }
    reason = _delete_reason(result)
    result["can_delete"] = reason is None
    result["blocked_reason"] = reason
    return result


def _point_geometry(point: dict[str, Any], source_crs: str | None) -> tuple[str, list[Any]]:
    lon, lat = point.get("longitude"), point.get("latitude")
    if lon is not None and lat is not None:
        return "ST_SetSRID(ST_MakePoint(%s,%s),4326)", [lon, lat]
    raw_x, raw_y = point.get("raw_x"), point.get("raw_y")
    match = _EPSG.fullmatch(str(point.get("raw_crs") or source_crs or "").strip())
    if raw_x is None or raw_y is None or not match:
        raise SyncRejected("each survey point requires longitude/latitude or raw_x/raw_y with EPSG raw_crs")
    srid = int(match.group(1))
    return "ST_Transform(ST_SetSRID(ST_MakePoint(%s,%s),%s),4326)", [raw_x, raw_y, srid]


def _short_text(value: Any, label: str, limit: int) -> str | None:
    if value in (None, ""):
        return None
    result = str(value).strip()
    if len(result) > limit:
        raise SyncRejected(f"{label} must be at most {limit} characters")
    return result or None


def _nonnegative_decimal(value: Any, label: str) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise SyncRejected(f"{label} must be numeric") from exc
    if not result.is_finite() or result < 0:
        raise SyncRejected(f"{label} must be a non-negative finite number")
    return result


def _point_metadata(
    alias: str, point: dict[str, Any], payload: dict[str, Any], index: int
) -> dict[str, Any]:
    unknown = sorted(set(point) - _POINT_FIELDS)
    if unknown:
        raise SyncRejected(f"points[{index}] contains unsupported fields: {', '.join(unknown)}")
    raw_data = point.get("raw_data") or {}
    if not isinstance(raw_data, dict):
        raise SyncRejected(f"points[{index}].raw_data must be an object")
    worker_id = point.get("worker_id", payload.get("worker_id"))
    if worker_id not in (None, ""):
        worker_id = _uuid_text(worker_id, f"points[{index}].worker_id")
        with connections[alias].cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM hr.employee_profile WHERE id=%s AND is_deleted=false",
                [worker_id],
            )
            if cursor.fetchone() is None:
                raise SyncRejected(f"points[{index}].worker_id is not available in this tenant")
    else:
        worker_id = None
    survey_date = point.get("survey_date", payload.get("survey_date"))
    if survey_date not in (None, ""):
        try:
            survey_date = dt.date.fromisoformat(str(survey_date))
        except ValueError as exc:
            raise SyncRejected(f"points[{index}].survey_date must use YYYY-MM-DD") from exc
    else:
        survey_date = None
    row_id = str(point.get("source_row_id") or "").strip()
    raw_code = str(point.get("raw_code") or "").strip() or None
    name = _short_text(point.get("name"), f"points[{index}].name", 30)
    if name is None and len(row_id) <= 30:
        name = row_id
    code = _short_text(point.get("code"), f"points[{index}].code", 30)
    if code is None and raw_code and len(raw_code) <= 30:
        code = raw_code
    return {
        "worker_id": worker_id,
        "survey_date": survey_date,
        "name": name,
        "code": code,
        "solution_info": _short_text(
            point.get("solution_info"), f"points[{index}].solution_info", 200
        ),
        "pdop": _nonnegative_decimal(point.get("pdop"), f"points[{index}].pdop"),
        "antenna_height": _nonnegative_decimal(
            point.get("antenna_height"), f"points[{index}].antenna_height"
        ),
        "raw_data": raw_data,
    }


def import_survey_source(
    alias: str, *, project_id: str, payload: dict[str, Any], actor_ref: str | None = None
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SyncRejected("payload must be an object")
    source_type = str(payload.get("source_type") or "").upper()
    if source_type not in SOURCE_TYPES:
        raise SyncRejected("source_type is invalid")
    file_name = str(payload.get("original_file_name") or "").strip()
    if not file_name:
        raise SyncRejected("original_file_name is required")
    points = payload.get("points")
    if not isinstance(points, list) or not points:
        raise SyncRejected("points must be a non-empty list")
    source_id = _uuid_text(payload.get("id") or uuid.uuid4(), "id")
    source_group_id = _uuid_text(payload.get("source_group_id") or source_id, "source_group_id")
    supersedes_id = payload.get("supersedes_id")
    if supersedes_id:
        supersedes_id = _uuid_text(supersedes_id, "supersedes_id")
    calibration = payload.get("calibration_info") or {}
    if not isinstance(calibration, dict):
        raise SyncRejected("calibration_info must be an object")
    actor_uuid = None
    try:
        actor_uuid = str(uuid.UUID(str(actor_ref))) if actor_ref else None
    except (ValueError, TypeError, AttributeError):
        pass

    with transaction.atomic(using=alias):
        _ensure_project_state(alias, project_id)
        changeset_id, client_id = str(uuid.uuid4()), str(uuid.uuid4())
        if not _reserve_receipt(
            alias,
            project_id=project_id,
            client_id=client_id,
            changeset_id=changeset_id,
            actor_ref=actor_ref,
            base_revision=None,
        ):
            raise ChangesetUnavailable("Survey import receipt could not be reserved")
        with connections[alias].cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", [f"{project_id}:{source_group_id}"])
            cursor.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM gis.survey_source WHERE project_id=%s AND source_group_id=%s",
                [project_id, source_group_id],
            )
            version = int(cursor.fetchone()[0])
            if version > 1 and not supersedes_id:
                raise SyncRejected("supersedes_id is required for a source revision")
            if supersedes_id:
                cursor.execute(
                    "SELECT 1 FROM gis.survey_source WHERE id=%s AND project_id=%s AND source_group_id=%s AND version=%s AND is_active",
                    [supersedes_id, project_id, source_group_id, version - 1],
                )
                if cursor.fetchone() is None:
                    raise SyncConflict([{"resource_kind": "survey_source", "id": supersedes_id, "reason": "superseded_source_missing_or_wrong_group"}])
            cursor.execute(
                "UPDATE gis.survey_source SET is_active=false,updated_at=now() WHERE project_id=%s AND source_group_id=%s AND is_active",
                [project_id, source_group_id],
            )
            cursor.execute(
                """
                INSERT INTO gis.survey_source(
                  id,project_id,source_group_id,supersedes_id,source_type,
                  original_file_name,original_file_key,imported_by,source_crs,
                  geoid_model,calibration_info,version,note
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                [source_id, project_id, source_group_id, supersedes_id, source_type,
                 file_name, payload.get("original_file_key"), actor_uuid,
                 payload.get("source_crs"), payload.get("geoid_model"), Json(calibration),
                 version, str(payload.get("note") or "")],
            )

        seen_rows: set[str] = set()
        events: list[dict[str, Any]] = []
        for index, point in enumerate(points):
            if not isinstance(point, dict):
                raise SyncRejected(f"points[{index}] must be an object")
            row_id = str(point.get("source_row_id") or "").strip()
            if not row_id or row_id in seen_rows:
                raise SyncRejected(f"points[{index}].source_row_id is required and must be unique")
            seen_rows.add(row_id)
            geom_sql, geom_params = _point_geometry(point, payload.get("source_crs"))
            with connections[alias].cursor() as cursor:
                cursor.execute(
                    """
                    SELECT s.id::text,encode(ST_AsBinary(s.geom),'hex'),
                           s.source_id::text,s.source_row_id,s.raw_x,s.raw_y,s.raw_z,
                           s.raw_crs,s.raw_code,s.raw_geoid_model,s.worker_id::text,
                           s.survey_date,s.name,s.code,s.solution_info,s.pdop,
                           s.antenna_height,s.raw_data
                      FROM gis.survey s
                      JOIN gis.survey_source src ON src.id=s.source_id
                     WHERE s.project_id=%s AND src.source_group_id=%s AND s.source_row_id=%s
                     ORDER BY src.version DESC LIMIT 1 FOR UPDATE OF s
                    """,
                    [project_id, source_group_id, row_id],
                )
                existing = cursor.fetchone()
                survey_id = str(existing[0]) if existing else _uuid_text(point.get("id") or uuid.uuid4(), f"points[{index}].id")
                metadata = _point_metadata(alias, point, payload, index)
                common = [
                    source_id, row_id, point.get("raw_x"), point.get("raw_y"), point.get("raw_z"),
                    point.get("raw_crs") or payload.get("source_crs"), point.get("raw_code"),
                    point.get("raw_geoid_model") or payload.get("geoid_model"),
                    point.get("raw_x"), point.get("raw_y"), point.get("raw_z"),
                    metadata["worker_id"], metadata["survey_date"], metadata["name"],
                    metadata["code"], metadata["solution_info"], metadata["pdop"],
                    metadata["antenna_height"], Json(metadata["raw_data"]),
                ]
                if existing:
                    cursor.execute(
                        f"""UPDATE gis.survey SET source_id=%s,source_row_id=%s,raw_x=%s,raw_y=%s,raw_z=%s,
                            raw_crs=%s,raw_code=%s,raw_geoid_model=%s,x=%s,y=%s,z=%s,
                            worker_id=%s,survey_date=%s,name=%s,code=%s,solution_info=%s,
                            pdop=%s,antenna_height=%s,
                            raw_data=%s,raw_geom={geom_sql},geom={geom_sql},updated_at=now()
                            WHERE id=%s AND project_id=%s""",
                        [*common, *geom_params, *geom_params, survey_id, project_id],
                    )
                    action = "update"
                else:
                    cursor.execute(
                        f"""INSERT INTO gis.survey(id,project_id,source_id,source_row_id,raw_x,raw_y,raw_z,
                            raw_crs,raw_code,raw_geoid_model,x,y,z,worker_id,survey_date,name,code,
                            solution_info,pdop,antenna_height,raw_data,raw_geom,geom)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,{geom_sql},{geom_sql})""",
                        [survey_id, project_id, *common, *geom_params, *geom_params],
                    )
                    action = "create"
                cursor.execute(
                    """UPDATE gis.survey
                          SET longitude=ST_X(geom),latitude=ST_Y(geom)
                        WHERE id=%s AND project_id=%s
                    RETURNING ST_AsBinary(geom)""",
                    [survey_id, project_id],
                )
                geom_after = bytes(cursor.fetchone()[0])
            old_values = ({"source_id": existing[2], "source_row_id": existing[3],
                           "raw_x": existing[4], "raw_y": existing[5], "raw_z": existing[6],
                           "raw_crs": existing[7], "raw_code": existing[8],
                           "raw_geoid_model": existing[9], "worker_id": existing[10],
                           "survey_date": existing[11], "name": existing[12], "code": existing[13],
                           "solution_info": existing[14], "pdop": existing[15],
                           "antenna_height": existing[16], "raw_data": existing[17]} if existing else {})
            old_values = _plain_value(old_values)
            new_values = {"source_id": source_id, "source_row_id": row_id,
                          "raw_x": point.get("raw_x"), "raw_y": point.get("raw_y"),
                          "raw_z": point.get("raw_z"),
                          "raw_crs": point.get("raw_crs") or payload.get("source_crs"),
                          "raw_code": point.get("raw_code"),
                          "raw_geoid_model": point.get("raw_geoid_model") or payload.get("geoid_model"),
                          **metadata}
            new_values = _plain_value(new_values)
            events.append({"id": survey_id, "action": action,
                           "before": bytes.fromhex(existing[1]) if existing and existing[1] else None,
                           "after": geom_after, "old_values": old_values, "new_values": new_values})

        first, last, current = _allocate_revisions(alias, project_id, len(events))
        for offset, event in enumerate(events):
            _insert_change_log(
                alias, project_id=project_id, revision=first + offset,
                changeset_id=changeset_id, client_id=client_id, standard_name="SURVEY",
                physical_name="survey", object_id=event["id"], action=event["action"],
                changed_fields=["source_id","source_row_id","raw_x","raw_y","raw_z","raw_crs",
                                "raw_code","worker_id","survey_date","name","code","solution_info",
                                "pdop","antenna_height","raw_data","longitude","latitude","geom"],
                old_values=event["old_values"], new_values=event["new_values"],
                geom_before=event["before"], geom_after=event["after"], actor_ref=actor_ref,
            )
        response = {
            "ok": True, "source_id": source_id, "source_group_id": source_group_id,
            "version": version, "created": sum(e["action"] == "create" for e in events),
            "updated": sum(e["action"] == "update" for e in events),
            "first_revision": first, "last_revision": last, "current_revision": current,
        }
        _complete_receipt(
            alias,
            project_id=project_id,
            client_id=client_id,
            changeset_id=changeset_id,
            first_revision=first,
            last_revision=last,
            change_count=len(events),
            response=response,
        )
        return response


def delete_survey_source(
    alias: str, *, project_id: str, source_id: str, actor_ref: str | None = None
) -> dict[str, Any]:
    source_id = _uuid_text(source_id, "source_id")
    changeset_id, client_id = str(uuid.uuid4()), str(uuid.uuid4())
    object_key = ""
    response: dict[str, Any]

    with transaction.atomic(using=alias):
        _ensure_project_state(alias, project_id)
        precheck = survey_source_delete_precheck(
            alias, project_id=project_id, source_id=source_id, lock=True
        )
        reason = _delete_reason(precheck)
        if reason:
            raise SurveySourceDeleteBlocked(reason, precheck)
        if not _reserve_receipt(
            alias,
            project_id=project_id,
            client_id=client_id,
            changeset_id=changeset_id,
            actor_ref=actor_ref,
            base_revision=None,
        ):
            raise ChangesetUnavailable("Survey source delete receipt could not be reserved")

        with connections[alias].cursor() as cursor:
            cursor.execute(
                "SELECT original_file_key FROM gis.survey_source WHERE id=%s AND project_id=%s",
                [source_id, project_id],
            )
            object_key = str(cursor.fetchone()[0] or "")
            cursor.execute(
                """
                SELECT id::text,ST_AsBinary(geom),source_id::text,source_row_id,
                       raw_x,raw_y,raw_z,raw_crs,raw_code,raw_geoid_model,
                       worker_id::text,survey_date,name,code,solution_info,pdop,
                       antenna_height,raw_data,longitude,latitude
                  FROM gis.survey
                 WHERE project_id=%s AND source_id=%s
                 ORDER BY id
                 FOR UPDATE
                """,
                [project_id, source_id],
            )
            point_rows = cursor.fetchall()

        events = []
        value_names = (
            "source_id", "source_row_id", "raw_x", "raw_y", "raw_z", "raw_crs",
            "raw_code", "raw_geoid_model", "worker_id", "survey_date", "name", "code",
            "solution_info", "pdop", "antenna_height", "raw_data", "longitude", "latitude",
        )
        for row in point_rows:
            events.append({
                "id": row[0],
                "before": bytes(row[1]) if row[1] is not None else None,
                "old_values": _plain_value(dict(zip(value_names, row[2:]))),
            })

        with connections[alias].cursor() as cursor:
            cursor.execute(
                "DELETE FROM gis.survey WHERE project_id=%s AND source_id=%s",
                [project_id, source_id],
            )
            if cursor.rowcount != len(events):
                raise ChangesetUnavailable("Survey source point delete count changed")
            cursor.execute(
                "DELETE FROM gis.survey_source WHERE id=%s AND project_id=%s",
                [source_id, project_id],
            )
            if cursor.rowcount != 1:
                raise ChangesetUnavailable("Survey source could not be deleted")

        first, last, current = _allocate_revisions(alias, project_id, len(events))
        for offset, event in enumerate(events):
            _insert_change_log(
                alias,
                project_id=project_id,
                revision=first + offset,
                changeset_id=changeset_id,
                client_id=client_id,
                standard_name="SURVEY",
                physical_name="survey",
                object_id=event["id"],
                action="delete",
                changed_fields=sorted(event["old_values"]),
                old_values=event["old_values"],
                new_values={},
                geom_before=event["before"],
                geom_after=None,
                actor_ref=actor_ref,
            )
        response = {
            "ok": True,
            "source_id": source_id,
            "deleted_source_id": source_id,
            "deleted_point_count": len(events),
            "deleted_object": not bool(object_key),
            "cleanup_pending": bool(object_key),
            "first_revision": first,
            "last_revision": last,
            "current_revision": current,
        }
        receipt_response = dict(response)
        if object_key:
            receipt_response["cleanup_object_key"] = object_key
        _complete_receipt(
            alias,
            project_id=project_id,
            client_id=client_id,
            changeset_id=changeset_id,
            first_revision=first,
            last_revision=last,
            change_count=len(events),
            response=receipt_response,
        )

    if object_key:
        try:
            get_s3_client().delete_object(Bucket=get_bucket_name(), Key=object_key)
            response["deleted_object"] = True
            response["cleanup_pending"] = False
        except Exception:
            logger.exception("Survey source object cleanup failed for source_id=%s", source_id)
        receipt_response = dict(response)
        if response["cleanup_pending"]:
            receipt_response["cleanup_object_key"] = object_key
        try:
            with transaction.atomic(using=alias):
                _complete_receipt(
                    alias,
                    project_id=project_id,
                    client_id=client_id,
                    changeset_id=changeset_id,
                    first_revision=response["first_revision"],
                    last_revision=response["last_revision"],
                    change_count=response["deleted_point_count"],
                    response=receipt_response,
                )
        except Exception:
            logger.exception(
                "Survey source cleanup receipt refresh failed for source_id=%s", source_id
            )
    return response
