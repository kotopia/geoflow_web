"""Project-authorized read-only reference preview and secret-free background tiles."""

import json

from django.contrib.auth.decorators import login_required
from django.db import DatabaseError, connections
from django.http import Http404, HttpResponse, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from control.services import gis_reference_files as files
from control.services import gis_reference_vworld as vworld
from control.services import gis_references as refs


def _context(request, project_id):
    from .qgis_views import _require_project, _require_qgis_context

    alias = _require_qgis_context(request)
    project, _policy, plan = _require_project(request, alias, project_id)
    return alias, project, plan


def _target(alias, project, plan, payload):
    layer = next(
        (
            row
            for row in plan.get("layers", [])
            if row["standard_name"] == payload.get("feature_layer")
        ),
        None,
    )
    if not layer or layer.get("scope_type", "PROJECT") != "PROJECT":
        raise Http404("Project layer unavailable")
    connection = connections[alias]
    table = connection.ops.quote_name(layer["physical_name"])
    extra = " AND deleted_at IS NULL" if layer["physical_name"] == "survey" else ""
    with connection.cursor() as cur:
        cur.execute(
            f"SELECT ST_AsGeoJSON(ST_Transform(geom,4326)) FROM gis.{table} "
            "WHERE project_id=%s AND id=%s AND geom IS NOT NULL" + extra,
            [project.id, refs.identifier(payload.get("feature_id"))],
        )
        found = cur.fetchone()
    if not found:
        raise Http404("Project feature unavailable")
    return json.loads(found[0])


@login_required
@require_GET
@never_cache
def project_reference_options(request, project_id):
    _context(request, project_id)
    from control.services import gis_reference_lookup as engine

    try:
        with connections["default"].cursor() as cur:
            result = engine.options(cur)
        return JsonResponse({"ok": True, "datasets": result})
    except DatabaseError:
        return JsonResponse(
            {"ok": False, "error": "참조자료 목록을 읽지 못했습니다."}, status=503
        )


@login_required
@require_POST
@csrf_protect
@never_cache
def project_reference_lookup(request, project_id):
    alias, project, plan = _context(request, project_id)
    from control.services import gis_reference_lookup as engine

    try:
        if len(request.body) > 16000:
            raise refs.ReferenceError("조회 설정이 너무 큽니다.")
        payload = json.loads(request.body)
        if not isinstance(payload, dict):
            raise refs.ReferenceError("조회 설정은 객체여야 합니다.")
        payload["geometry"] = _target(alias, project, plan, payload)
        payload["crs"] = "EPSG:4326"
        with connections["default"].cursor() as cur:
            if payload.get("action") == "inspect":
                result = {
                    "layers": engine.inspect_file(
                        engine.dataset(
                            cur, payload.get("dataset_id"), payload.get("version_id")
                        )
                    )
                }
            else:
                result = engine.lookup(cur, payload)
        return JsonResponse({"ok": True, **result})
    except (refs.ReferenceError, ValueError, files.ReferenceStorageError):
        return JsonResponse(
            {
                "ok": False,
                "error": "참조자료·필드·공간조회 설정 또는 API 연결 상태를 확인하세요.",
            },
            status=400,
        )
    except DatabaseError:
        return JsonResponse(
            {"ok": False, "error": "참조자료 조회를 처리하지 못했습니다."}, status=503
        )


@login_required
@require_GET
def project_reference_tile(request, project_id, style, z, y, x):
    _context(request, project_id)
    try:
        # Validate tile bounds before reading credentials or contacting the provider.
        if (
            style not in {"Base", "Satellite", "Hybrid"}
            or not 0 <= z <= 19
            or not (0 <= x < 2**z and 0 <= y < 2**z)
        ):
            raise Http404("Tile unavailable")
        with connections["default"].cursor() as cur:
            key, domain = vworld.credential(cur)
        value, content_type = vworld.tile(style, z, y, x, key, domain)
        response = HttpResponse(value, content_type=content_type)
        response["Cache-Control"] = "private, max-age=300"
        response["X-Content-Type-Options"] = "nosniff"
        return response
    except (refs.ReferenceError, DatabaseError):
        return HttpResponse(status=503)
