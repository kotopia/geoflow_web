from __future__ import annotations

import re
import uuid
from typing import Any

from django.db import connections, transaction
from psycopg2.extras import Json

from .changeset import _allocate_revisions, _ensure_project_state, _insert_change_log, _plain_value, _uuid_text
from .qgis_sync import SyncConflict, SyncRejected


SOURCE_TYPES = frozenset({"GNSS", "GPS", "TOTAL", "CSV", "XLSX", "OTHER"})
_EPSG = re.compile(r"^EPSG:(\d{3,6})$", re.I)


def _source_dict(row) -> dict[str, Any]:
    return {
        "id": str(row[0]), "project_id": str(row[1]), "source_group_id": str(row[2]),
        "supersedes_id": str(row[3]) if row[3] else None, "source_type": row[4],
        "original_file_name": row[5], "original_file_key": row[6],
        "imported_at": row[7].isoformat(), "imported_by": str(row[8]) if row[8] else None,
        "source_crs": row[9], "geoid_model": row[10],
        "calibration_info": row[11] or {}, "version": int(row[12]),
        "is_active": bool(row[13]), "note": row[14] or "",
    }


def list_survey_sources(alias: str, *, project_id: str, include_inactive: bool = False) -> list[dict[str, Any]]:
    with connections[alias].cursor() as cursor:
        cursor.execute(
            """
            SELECT id,project_id,source_group_id,supersedes_id,source_type,
                   original_file_name,original_file_key,imported_at,imported_by,
                   source_crs,geoid_model,calibration_info,version,is_active,note
              FROM gis.survey_source
             WHERE project_id=%s AND (%s OR is_active)
             ORDER BY source_group_id,version DESC
            """,
            [project_id, include_inactive],
        )
        return [_source_dict(row) for row in cursor.fetchall()]


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
                           s.raw_crs,s.raw_code,s.raw_geoid_model
                      FROM gis.survey s
                      JOIN gis.survey_source src ON src.id=s.source_id
                     WHERE s.project_id=%s AND src.source_group_id=%s AND s.source_row_id=%s
                     ORDER BY src.version DESC LIMIT 1 FOR UPDATE OF s
                    """,
                    [project_id, source_group_id, row_id],
                )
                existing = cursor.fetchone()
                survey_id = str(existing[0]) if existing else _uuid_text(point.get("id") or uuid.uuid4(), f"points[{index}].id")
                common = [
                    source_id, row_id, point.get("raw_x"), point.get("raw_y"), point.get("raw_z"),
                    point.get("raw_crs") or payload.get("source_crs"), point.get("raw_code"),
                    point.get("raw_geoid_model") or payload.get("geoid_model"),
                    point.get("raw_x"), point.get("raw_y"), point.get("raw_z"),
                    point.get("longitude"), point.get("latitude"), Json(point.get("raw_data") or {}),
                ]
                if existing:
                    cursor.execute(
                        f"""UPDATE gis.survey SET source_id=%s,source_row_id=%s,raw_x=%s,raw_y=%s,raw_z=%s,
                            raw_crs=%s,raw_code=%s,raw_geoid_model=%s,x=%s,y=%s,z=%s,longitude=%s,latitude=%s,
                            raw_data=%s,raw_geom={geom_sql},geom={geom_sql},updated_at=now()
                            WHERE id=%s AND project_id=%s""",
                        [*common, *geom_params, *geom_params, survey_id, project_id],
                    )
                    action = "update"
                else:
                    cursor.execute(
                        f"""INSERT INTO gis.survey(id,project_id,source_id,source_row_id,raw_x,raw_y,raw_z,
                            raw_crs,raw_code,raw_geoid_model,x,y,z,longitude,latitude,raw_data,raw_geom,geom)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,{geom_sql},{geom_sql})""",
                        [survey_id, project_id, *common, *geom_params, *geom_params],
                    )
                    action = "create"
                cursor.execute("SELECT ST_AsBinary(geom) FROM gis.survey WHERE id=%s", [survey_id])
                geom_after = bytes(cursor.fetchone()[0])
            old_values = ({"source_id": existing[2], "source_row_id": existing[3],
                           "raw_x": existing[4], "raw_y": existing[5], "raw_z": existing[6],
                           "raw_crs": existing[7], "raw_code": existing[8],
                           "raw_geoid_model": existing[9]} if existing else {})
            old_values = _plain_value(old_values)
            new_values = {"source_id": source_id, "source_row_id": row_id,
                          "raw_x": point.get("raw_x"), "raw_y": point.get("raw_y"),
                          "raw_z": point.get("raw_z"),
                          "raw_crs": point.get("raw_crs") or payload.get("source_crs"),
                          "raw_code": point.get("raw_code"),
                          "raw_geoid_model": point.get("raw_geoid_model") or payload.get("geoid_model")}
            events.append({"id": survey_id, "action": action,
                           "before": bytes.fromhex(existing[1]) if existing and existing[1] else None,
                           "after": geom_after, "old_values": old_values, "new_values": new_values})

        first, last, current = _allocate_revisions(alias, project_id, len(events))
        change_id, client_id = str(uuid.uuid4()), str(uuid.uuid4())
        for offset, event in enumerate(events):
            _insert_change_log(
                alias, project_id=project_id, revision=first + offset,
                changeset_id=change_id, client_id=client_id, standard_name="SURVEY",
                physical_name="survey", object_id=event["id"], action=event["action"],
                changed_fields=["source_id","source_row_id","raw_x","raw_y","raw_z","geom"],
                old_values=event["old_values"], new_values=event["new_values"],
                geom_before=event["before"], geom_after=event["after"], actor_ref=actor_ref,
            )
    return {"ok": True, "source_id": source_id, "source_group_id": source_group_id,
            "version": version, "created": sum(e["action"] == "create" for e in events),
            "updated": sum(e["action"] == "update" for e in events),
            "first_revision": first, "last_revision": last, "current_revision": current}
