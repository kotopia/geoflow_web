from __future__ import annotations

import datetime as dt
import json
import uuid
from decimal import Decimal
from urllib.parse import quote

from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, connections
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_GET

from control.gf_authz.permissions import gf_has_perm
from geoflow_ops.models import Project
from geoflow_ops.services.entity_access import require_tenant_context
from geoflow_ops.services.project_access import project_access_policy

from .changeset import changeset_runtime_enabled, project_current_revision
from .gpkg_snapshot_v2 import project_geopackage_layer_manifest
from .layer_plan import project_layer_plan
from .qfield_auth import qfield_session_or_ticket_required
from .qfield_roaming import (
    DEFAULT_ACTIVE_RADIUS_M,
    DEFAULT_CELL_SIZE_M,
    DEFAULT_MAX_CELLS,
    DEFAULT_PREFETCH_RADIUS_M,
    cell_bbox,
    parse_cell_key,
    plan_roaming_cells,
)
from .views import _parse_bbox


MAX_KNOWN_CELLS = 2_000
MAX_LAYERS_PER_CELL = 64
DEFAULT_LIMIT_PER_LAYER = 1_000
MAX_LIMIT_PER_LAYER = 5_000


def _require_project(request, alias, project_id):
    project = get_object_or_404(Project.objects.using(alias), id=project_id)
    policy = project_access_policy(request, alias)
    if not policy.can_webgis_read(project.id):
        raise PermissionDenied("Permission denied")
    plan = project_layer_plan(alias, project.id)
    if plan.get("ready") and not plan.get("gis_enabled"):
        raise Http404("GIS is not enabled by this project's business scope.")
    return project, policy, plan


def _parse_optional_float(value, *, name: str) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc


def _parse_int(value, *, name: str, default: int, minimum: int = 0, maximum: int | None = None) -> int:
    if value in (None, ""):
        result = int(default)
    else:
        try:
            result = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be an integer") from exc
    if result < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    if maximum is not None and result > maximum:
        raise ValueError(f"{name} must be <= {maximum}")
    return result


def _parse_known_cells(value: str | None) -> set[str]:
    if not value:
        return set()
    rows = [item.strip() for item in str(value).split(",") if item.strip()]
    if len(rows) > MAX_KNOWN_CELLS:
        raise ValueError(f"known accepts at most {MAX_KNOWN_CELLS} cells")
    result = set()
    for raw in rows:
        size, ix, iy = parse_cell_key(raw)
        result.add(f"{size}:{ix}:{iy}")
    return result


def _parse_layer_filter(value: str | None) -> set[str]:
    if not value:
        return set()
    rows = [item.strip().upper() for item in str(value).split(",") if item.strip()]
    if len(rows) > MAX_LAYERS_PER_CELL:
        raise ValueError(f"layers accepts at most {MAX_LAYERS_PER_CELL} values")
    return set(rows)


def _json_value(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__bytes__": bytes(value).hex()}
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return str(value)


def _current_revision(alias: str, project_id) -> int:
    if not changeset_runtime_enabled(alias):
        return 0
    return project_current_revision(alias, str(project_id))


def _layer_rows(alias: str, plan: dict, requested_names: set[str]) -> list[dict]:
    rows = project_geopackage_layer_manifest(alias, plan)
    if not requested_names:
        return rows
    selected = []
    matched = set()
    for row in rows:
        standard = str(row.get("standard_name") or "").upper()
        physical = str(row.get("physical_name") or "").upper()
        if standard in requested_names or physical in requested_names:
            selected.append(row)
            matched.add(standard)
            matched.add(physical)
    unknown = requested_names - matched
    if unknown:
        raise ValueError("Unknown or disabled GIS layer: " + ", ".join(sorted(unknown)))
    return selected


@qfield_session_or_ticket_required
@require_GET
def qfield_roaming_plan_api(request, project_id):
    alias = require_tenant_context(request)
    if not gf_has_perm(request, "maps.view"):
        raise PermissionDenied("Permission denied")
    project, policy, plan = _require_project(request, alias, project_id)

    try:
        longitude = _parse_optional_float(request.GET.get("lon"), name="lon")
        latitude = _parse_optional_float(request.GET.get("lat"), name="lat")
        viewport = _parse_bbox(request.GET.get("viewport"))
        known = _parse_known_cells(request.GET.get("known"))
        cell_size_m = _parse_int(
            request.GET.get("cell_size_m"),
            name="cell_size_m",
            default=DEFAULT_CELL_SIZE_M,
            minimum=1,
        )
        active_radius_m = _parse_int(
            request.GET.get("active_radius_m"),
            name="active_radius_m",
            default=DEFAULT_ACTIVE_RADIUS_M,
            minimum=0,
        )
        prefetch_radius_m = _parse_int(
            request.GET.get("prefetch_radius_m"),
            name="prefetch_radius_m",
            default=DEFAULT_PREFETCH_RADIUS_M,
            minimum=0,
        )
        max_cells = _parse_int(
            request.GET.get("max_cells"),
            name="max_cells",
            default=DEFAULT_MAX_CELLS,
            minimum=1,
            maximum=512,
        )
        roaming = plan_roaming_cells(
            longitude=longitude,
            latitude=latitude,
            viewport_bbox=viewport,
            cell_size_m=cell_size_m,
            active_radius_m=active_radius_m,
            prefetch_radius_m=prefetch_radius_m,
            known_cells=known,
            max_cells=max_cells,
        )
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    cell_base_url = reverse(
        "gis:qfield_roaming_cell_api",
        kwargs={"project_id": project.id},
    )
    cells = [
        {
            "key": cell.key,
            "priority": cell.priority,
            "bbox": list(cell.bbox),
            "distance_m": cell.distance_m,
            "url": f"{cell_base_url}?cell={quote(cell.key, safe='')}",
        }
        for cell in roaming.pop("cells")
    ]
    layer_rows = project_geopackage_layer_manifest(alias, plan)

    response = JsonResponse(
        {
            "ok": True,
            "protocol": "qfield_roaming_v1",
            "project": {
                "id": str(project.id),
                "code": project.code or "",
                "name": project.name or "",
                "status": project.status or "",
            },
            "current_revision": _current_revision(alias, project.id),
            "write_authorized": bool(policy.can_webgis_write(project.id)),
            "layers": [
                {
                    "standard_name": row.get("standard_name"),
                    "physical_name": row.get("physical_name"),
                    "geometry_kind": row.get("geometry_kind"),
                    "domain": row.get("domain"),
                }
                for row in layer_rows
            ],
            "roaming": {
                **roaming,
                "cells": cells,
                "eviction": {
                    "strategy": "lru_clean_cells_only",
                    "dirty_never_evict": True,
                    "pending_never_evict": True,
                },
            },
            "transport": {
                "cell_url": cell_base_url,
                "delta_url": reverse(
                    "gis:project_delta_api",
                    kwargs={"project_id": project.id},
                ),
                "changeset_url": reverse(
                    "gis:project_changeset_api",
                    kwargs={"project_id": project.id},
                ),
            },
        },
        json_dumps_params={"ensure_ascii": False},
    )
    response["Cache-Control"] = "private, no-store"
    return response


@qfield_session_or_ticket_required
@require_GET
def qfield_roaming_cell_api(request, project_id):
    alias = require_tenant_context(request)
    if not gf_has_perm(request, "maps.view"):
        raise PermissionDenied("Permission denied")
    project, _policy, plan = _require_project(request, alias, project_id)

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
                    attrs = {
                        str(name): _json_value(value)
                        for name, value in record.items()
                    }
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
        return JsonResponse(
            {"ok": False, "error": "QField roaming cell query failed."},
            status=503,
        )

    response = JsonResponse(
        {
            "ok": True,
            "protocol": "qfield_roaming_cell_v1",
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
