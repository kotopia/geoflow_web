from __future__ import annotations

import json
import logging
import uuid

from django.db import DatabaseError, connections
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from geoflow_ops.models import Project
from geoflow_ops.services.entity_access import require_tenant_context

from .changeset import changeset_runtime_enabled, project_current_revision
from .layer_plan import project_layer_plan
from .qfield_auth import qfield_ticket_required
from .qfield_roaming import cell_bbox, parse_cell_key
from .qfield_views import (
    DEFAULT_LIMIT_PER_LAYER,
    MAX_LIMIT_PER_LAYER,
    _json_value,
    _layer_rows,
    _parse_int,
    _parse_layer_filter,
)


logger = logging.getLogger(__name__)


def _ticket_project_and_plan(request, alias: str, project_id):
    payload = getattr(request, "_qfield_ticket_payload", None) or {}
    try:
        ticket_project_id = str(uuid.UUID(str(payload.get("project_id"))))
        requested_project_id = str(uuid.UUID(str(project_id)))
    except (TypeError, ValueError, AttributeError):
        return None, None, JsonResponse(
            {"ok": False, "error": "invalid_qfield_project_scope"}, status=403
        )
    if ticket_project_id != requested_project_id:
        return None, None, JsonResponse(
            {"ok": False, "error": "qfield_project_scope_mismatch"}, status=403
        )
    if "maps.view" not in {str(value) for value in (payload.get("perms") or [])}:
        logger.warning(
            "DEV-QFIELD-TICKET read denied project_id=%s reason=maps.view_missing perms=%s",
            requested_project_id,
            payload.get("perms") or [],
        )
        return None, None, JsonResponse(
            {"ok": False, "error": "qfield_maps_view_required"}, status=403
        )

    project = get_object_or_404(Project.objects.using(alias), id=project_id)
    plan = project_layer_plan(alias, project.id)
    if plan.get("ready") and not plan.get("gis_enabled"):
        raise Http404("GIS is not enabled by this project's business scope.")
    return project, plan, None


def _current_revision(alias: str, project_id) -> int:
    if not changeset_runtime_enabled(alias):
        return 0
    return project_current_revision(alias, str(project_id))


@qfield_ticket_required(write=False)
@require_GET
def qfield_ticket_roaming_cell_api(request, project_id):
    """Read one roaming cell using only the signed project-scoped QField ticket.

    The package ticket was issued only after browser-session project authorization
    succeeded, and every native request revalidates the central user/group
    membership in qfield_ticket_required().  Re-running employee/project policy
    resolution for each cell made native requests depend on browser/session
    state and caused false 403 responses.  This endpoint therefore enforces the
    signed project scope and maps.view claim directly.
    """

    alias = require_tenant_context(request)
    project, plan, error = _ticket_project_and_plan(request, alias, project_id)
    if error is not None:
        return error

    try:
        size, ix, iy = parse_cell_key(request.GET.get("cell") or "")
        bbox = cell_bbox(size, ix, iy)
        requested_layers = _parse_layer_filter(request.GET.get("layers"))
        layer_rows = _layer_rows(alias, plan, requested_layers)
        limit_per_layer = _parse_int(
            request.GET.get("limit_per_layer"),
            name="limit_per_layer",
            default=DEFAULT_LIMIT_PER_LAYER,
            minimum=1,
            maximum=MAX_LIMIT_PER_LAYER,
        )
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    connection = connections[alias]
    schema_name = connection.ops.quote_name("gis")
    payload_layers = []
    minx, miny, maxx, maxy = bbox

    try:
        with connection.cursor() as cursor:
            for layer in layer_rows:
                physical_name = str(layer.get("physical_name") or "")
                standard_name = str(layer.get("standard_name") or physical_name.upper())
                if not physical_name:
                    continue

                cursor.execute("SELECT to_regclass(%s)", [f"gis.{physical_name}"])
                if cursor.fetchone()[0] is None:
                    payload_layers.append(
                        {
                            "standard_name": standard_name,
                            "physical_name": physical_name,
                            "features": [],
                            "returned": 0,
                            "truncated": False,
                            "physical_status": "NOT_APPLIED",
                        }
                    )
                    continue

                field_names = [
                    str(field.get("name") or "")
                    for field in (layer.get("fields") or [])
                    if field.get("name") and str(field.get("name")) != "geom"
                ]
                quoted_table = connection.ops.quote_name(physical_name)
                select_parts = [
                    "ST_AsGeoJSON(geom, 8) AS geometry_json",
                    "ST_AsText(geom) AS geometry_wkt",
                ]
                for field_name in field_names:
                    quoted = connection.ops.quote_name(field_name)
                    select_parts.append(f"{quoted} AS {quoted}")

                cursor.execute(
                    f"""
                    SELECT {', '.join(select_parts)}
                      FROM {schema_name}.{quoted_table}
                     WHERE project_id=%s
                       AND geom IS NOT NULL
                       AND geom && ST_MakeEnvelope(%s,%s,%s,%s,4326)
                       AND ST_Intersects(geom, ST_MakeEnvelope(%s,%s,%s,%s,4326))
                     ORDER BY id
                     LIMIT %s
                    """,
                    [
                        project.id,
                        minx,
                        miny,
                        maxx,
                        maxy,
                        minx,
                        miny,
                        maxx,
                        maxy,
                        limit_per_layer + 1,
                    ],
                )
                columns = [item[0] for item in cursor.description]
                records = [dict(zip(columns, row)) for row in cursor.fetchall()]
                truncated = len(records) > limit_per_layer
                records = records[:limit_per_layer]
                features = []
                for record in records:
                    geometry_json = record.pop("geometry_json", None)
                    geometry_wkt = record.pop("geometry_wkt", None)
                    if not geometry_json:
                        continue
                    attrs = {str(name): _json_value(value) for name, value in record.items()}
                    features.append(
                        {
                            "type": "Feature",
                            "id": attrs.get("id"),
                            "geometry": json.loads(geometry_json),
                            "geometry_wkt": geometry_wkt,
                            "properties": attrs,
                        }
                    )
                payload_layers.append(
                    {
                        "standard_name": standard_name,
                        "physical_name": physical_name,
                        "geometry_kind": layer.get("geometry_kind"),
                        "features": features,
                        "returned": len(features),
                        "truncated": truncated,
                        "physical_status": "READY",
                    }
                )
    except DatabaseError:
        logger.exception(
            "DEV-QFIELD-CELL query failed project_id=%s cell=%s:%s:%s",
            project.id,
            size,
            ix,
            iy,
        )
        return JsonResponse(
            {"ok": False, "error": "qfield_roaming_cell_query_failed"},
            status=503,
        )

    response = JsonResponse(
        {
            "ok": True,
            "protocol": "qfield_roaming_cell_v2",
            "project_id": str(project.id),
            "current_revision": _current_revision(alias, project.id),
            "cell": {
                "key": f"{size}:{ix}:{iy}",
                "cell_size_m": size,
                "bbox": list(bbox),
            },
            "limit_per_layer": limit_per_layer,
            "layers": payload_layers,
        },
        json_dumps_params={"ensure_ascii": False},
    )
    response["Cache-Control"] = "private, no-store"
    return response
