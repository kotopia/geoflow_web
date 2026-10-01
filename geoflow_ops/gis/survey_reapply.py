from __future__ import annotations

import uuid
from typing import Any

from django.db import connections, transaction

from .changeset import _allocate_revisions, _ensure_project_state, _insert_change_log, _uuid_text
from .qgis_sync import SyncConflict, SyncRejected, _quote_ident


def _selection(payload: dict[str, Any]) -> tuple[str | None, list[str]]:
    source_id = payload.get("source_id")
    if source_id:
        source_id = _uuid_text(source_id, "source_id")
    survey_ids = payload.get("survey_ids") or []
    if not isinstance(survey_ids, list):
        raise SyncRejected("survey_ids must be a list")
    survey_ids = [_uuid_text(item, "survey_ids[]") for item in survey_ids]
    if not source_id and not survey_ids:
        raise SyncRejected("source_id or survey_ids is required")
    return source_id, survey_ids


def _mapping_rows(alias: str, *, project_id: str, payload: dict[str, Any], lock: bool = False):
    source_id, survey_ids = _selection(payload)
    suffix = " FOR UPDATE OF sl,s" if lock else ""
    filters = ["s.project_id=%s"]
    params: list[Any] = [project_id]
    if source_id:
        filters.append("s.source_id=%s")
        params.append(source_id)
    else:
        filters.append("s.id=ANY(%s::uuid[])")
        params.append(survey_ids)
    mapping_ids = payload.get("mapping_ids") or []
    if mapping_ids:
        if not isinstance(mapping_ids, list):
            raise SyncRejected("mapping_ids must be a list")
        filters.append("sl.id=ANY(%s::uuid[])")
        params.append([_uuid_text(item, "mapping_ids[]") for item in mapping_ids])
    with connections[alias].cursor() as cursor:
        cursor.execute(
            f"""
            SELECT sl.id::text,sl.survey_id::text,sl.layer_id::text,sl.target_id::text,
                   sl.vertex_index,sl.link_role,sl.link_status
              FROM gis.survey_link sl JOIN gis.survey s ON s.id=sl.survey_id
             WHERE {' AND '.join(filters)} ORDER BY sl.id{suffix}
            """, params,
        )
        return cursor.fetchall()


def _target_preview_info(alias: str, *, project_id: str, table: str, survey_id: str, feature_id: str):
    with connections[alias].cursor() as cursor:
        cursor.execute(
            f'''SELECT GeometryType(f.geom),ST_NPoints(f.geom),s.geom IS NOT NULL
                  FROM "gis".{_quote_ident(table)} f
                  JOIN gis.survey s ON s.project_id=f.project_id AND s.id=%s
                 WHERE f.project_id=%s AND f.id=%s''',
            [survey_id, project_id, feature_id],
        )
        return cursor.fetchone()


def preview_survey_reapply(alias: str, *, project_id: str, plan: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    layers = {str(row["id"]): row for row in plan.get("layers", [])}
    items, counts = [], {"applicable": 0, "manually_modified": 0, "unlinked": 0, "invalid": 0}
    for row in _mapping_rows(alias, project_id=project_id, payload=payload):
        layer = layers.get(str(row[2]))
        status, reason = str(row[6]), None
        classification = "applicable"
        if status == "MANUALLY_MODIFIED": classification = "manually_modified"
        elif status == "UNLINKED": classification = "unlinked"
        elif layer is None:
            classification, reason = "invalid", "layer_outside_current_plan"
        else:
            geometry = _target_preview_info(
                alias, project_id=project_id, table=str(layer["physical_name"]),
                survey_id=str(row[1]), feature_id=str(row[3]),
            )
            if geometry is None:
                classification, reason = "invalid", "survey_or_target_missing"
            elif not geometry[2]:
                classification, reason = "invalid", "survey_geometry_missing"
            elif str(row[5]) == "POINT" and (row[4] is not None or str(geometry[0]).upper() != "POINT"):
                classification, reason = "invalid", "point_role_geometry_mismatch"
            elif str(row[5]) == "VERTEX" and (
                str(geometry[0]).upper() != "LINESTRING" or row[4] is None or
                int(row[4]) < 0 or int(row[4]) >= int(geometry[1] or 0)
            ):
                classification, reason = "invalid", "vertex_out_of_range_or_not_linestring"
        counts[classification] += 1
        items.append({
            "mapping_id": str(row[0]), "survey_id": str(row[1]), "layer_id": str(row[2]),
            "layer": str(layer.get("standard_name")) if layer else None,
            "feature_id": str(row[3]), "vertex_index": row[4], "link_role": row[5],
            "link_status": status, "classification": classification, "reason": reason,
        })
    return {"ok": True, "project_id": project_id, "counts": counts, "items": items}


def apply_survey_reapply(
    alias: str, *, project_id: str, plan: dict[str, Any], payload: dict[str, Any], actor_ref: str | None = None
) -> dict[str, Any]:
    layers = {str(row["id"]): row for row in plan.get("layers", [])}
    client_id = _uuid_text(payload.get("client_id") or uuid.uuid4(), "client_id")
    changeset_id = _uuid_text(payload.get("changeset_id") or uuid.uuid4(), "changeset_id")
    events, skipped = [], []
    with transaction.atomic(using=alias):
        _ensure_project_state(alias, project_id)
        for row in _mapping_rows(alias, project_id=project_id, payload=payload, lock=True):
            mapping_id, survey_id, layer_id, feature_id = map(str, row[:4])
            vertex_index, role, status = row[4], str(row[5]), str(row[6])
            if status != "LINKED":
                skipped.append({"mapping_id": mapping_id, "reason": status.lower()})
                continue
            layer = layers.get(layer_id)
            if layer is None:
                skipped.append({"mapping_id": mapping_id, "reason": "layer_outside_current_plan"})
                continue
            table = _quote_ident(str(layer["physical_name"]))
            with connections[alias].cursor() as cursor:
                cursor.execute(
                    f'SELECT ST_AsBinary(f.geom),GeometryType(f.geom),ST_NPoints(f.geom) '
                    f'FROM "gis".{table} f WHERE f.project_id=%s AND f.id=%s FOR UPDATE',
                    [project_id, feature_id],
                )
                target = cursor.fetchone()
                if target is None:
                    raise SyncConflict([{"resource_kind": "relation", "id": mapping_id, "reason": "target_outside_project_or_missing"}])
                before = bytes(target[0]) if target[0] is not None else None
                if role == "POINT":
                    if vertex_index is not None or str(target[1]).upper() != "POINT":
                        raise SyncRejected(f"mapping {mapping_id}: POINT requires a point feature and no vertex_index")
                    expression, expression_params = "s.geom", []
                elif role == "VERTEX":
                    if str(target[1]).upper() != "LINESTRING" or vertex_index is None or int(vertex_index) >= int(target[2] or 0):
                        raise SyncRejected(f"mapping {mapping_id}: vertex_index is outside a LineString")
                    expression, expression_params = "ST_SetPoint(f.geom,%s,s.geom)", [int(vertex_index)]
                else:
                    raise SyncRejected(f"mapping {mapping_id}: unsupported link_role")
                cursor.execute(
                    f"""UPDATE "gis".{table} f SET geom={expression},updated_at=now()
                          FROM gis.survey s
                         WHERE f.project_id=%s AND f.id=%s AND s.project_id=%s AND s.id=%s
                           AND s.geom IS NOT NULL AND ST_IsValid({expression})
                     RETURNING ST_AsBinary(f.geom)""",
                    [*expression_params, project_id, feature_id, project_id, survey_id, *expression_params],
                )
                changed = cursor.fetchone()
                if changed is None:
                    raise SyncRejected(f"mapping {mapping_id}: survey geometry is missing or result is invalid")
                after = bytes(changed[0])
            events.append({"mapping_id": mapping_id, "survey_id": survey_id, "feature_id": feature_id,
                           "layer": layer, "before": before, "after": after})

        first, last, current = _allocate_revisions(alias, project_id, len(events))
        for offset, event in enumerate(events):
            _insert_change_log(
                alias, project_id=project_id, revision=first + offset,
                changeset_id=changeset_id, client_id=client_id,
                standard_name=str(event["layer"]["standard_name"]),
                physical_name=str(event["layer"]["physical_name"]), object_id=event["feature_id"],
                action="update", changed_fields=["geom"], old_values={},
                new_values={"survey_mapping_id": event["mapping_id"], "survey_id": event["survey_id"]},
                geom_before=event["before"], geom_after=event["after"], actor_ref=actor_ref,
            )
    return {"ok": True, "project_id": project_id, "applied": len(events), "skipped": skipped,
            "first_revision": first, "last_revision": last, "current_revision": current}
