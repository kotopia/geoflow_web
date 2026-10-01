from __future__ import annotations

import json
import re
import uuid

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, connections
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from control.gf_authz.permissions import gf_has_perm
from geoflow_ops.services.entity_access import require_tenant_context
from geoflow_ops.services.s3_service import (
    S3ObjectVerificationError, extract_extension, generate_presigned_put_url, head_private_object,
)

from .qgis_sync import SyncConflict, SyncRejected
from .changeset import _uuid_text
from .sync_views import _actor_ref, _require_project
from .survey_reapply import apply_survey_reapply, preview_survey_reapply
from .survey_sources import import_survey_source, list_survey_sources


MAX_BODY_BYTES = 20 * 1024 * 1024
_SAFE_ALIAS = re.compile(r"^[A-Za-z0-9_-]+$")


def _body(request):
    if int(request.META.get("CONTENT_LENGTH") or 0) > MAX_BODY_BYTES:
        raise SyncRejected("request body is too large")
    if len(request.body) > MAX_BODY_BYTES:
        raise SyncRejected("request body is too large")
    try:
        value = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SyncRejected("request body must be valid JSON") from exc
    if not isinstance(value, dict):
        raise SyncRejected("request body must be an object")
    return value


def _response(callback):
    try:
        return JsonResponse(callback(), json_dumps_params={"ensure_ascii": False})
    except SyncConflict as exc:
        return JsonResponse({"ok": False, "error": "survey_conflict", "conflicts": exc.conflicts}, status=409)
    except SyncRejected as exc:
        return JsonResponse({"ok": False, "error": "survey_rejected", "message": str(exc), "details": exc.details}, status=400)
    except DatabaseError:
        return JsonResponse({"ok": False, "error": "survey_failed"}, status=503)
    except S3ObjectVerificationError:
        return JsonResponse({"ok": False, "error": "survey_source_object_invalid"}, status=400)


def _context(request, project_id, *, write=False):
    alias = require_tenant_context(request)
    if not gf_has_perm(request, "maps.view"):
        raise PermissionDenied("Permission denied")
    project, policy, plan = _require_project(request, alias, project_id)
    if write and not policy.can_webgis_write(project.id):
        raise PermissionDenied("Permission denied")
    return alias, project, plan


@login_required
@require_http_methods(["GET", "POST"])
def project_survey_sources_api(request, project_id):
    alias, project, _plan = _context(request, project_id, write=request.method == "POST")
    if request.method == "GET":
        return _response(lambda: {"ok": True, "project_id": str(project.id), "sources": list_survey_sources(
            alias, project_id=str(project.id), include_inactive=request.GET.get("include_inactive") == "1")})
    payload = _body(request)
    if payload.get("action") == "presign":
        if not _SAFE_ALIAS.fullmatch(alias):
            raise PermissionDenied("Permission denied")
        source_id = _uuid_text(payload.get("id") or uuid.uuid4(), "id")
        filename = str(payload.get("original_file_name") or "source.bin")
        key = (f"tenants/{alias}/gis/{project.id}/survey-sources/{source_id}/"
               f"{uuid.uuid4().hex}.{extract_extension(filename)}")
        signed = generate_presigned_put_url(key, mime_type=payload.get("mime_type"), expires_in=900)
        return JsonResponse({"ok": True, "id": source_id, "object_key": key, **signed})
    object_key = str(payload.get("original_file_key") or "")
    def finalize():
        if object_key:
            prefix = f"tenants/{alias}/gis/{project.id}/survey-sources/"
            if not object_key.startswith(prefix):
                raise PermissionDenied("Permission denied")
            uploaded = head_private_object(object_key)
            if uploaded.size_bytes <= 0 or not uploaded.encryption_matches:
                raise S3ObjectVerificationError("invalid survey source object")
        return import_survey_source(
            alias, project_id=str(project.id), payload=payload, actor_ref=_actor_ref(request))
    return _response(finalize)


@login_required
@require_GET
def project_survey_points_api(request, project_id):
    alias, project, _plan = _context(request, project_id)
    source_id = request.GET.get("source_id")
    params = [str(project.id)]
    where = ["s.project_id=%s"]
    if source_id:
        where.append("s.source_id=%s")
        params.append(source_id)
    with connections[alias].cursor() as cursor:
        cursor.execute(f"""
            SELECT s.id::text,s.source_id::text,s.source_row_id,s.raw_x,s.raw_y,s.raw_z,
                   s.raw_crs,s.raw_code,s.raw_geoid_model,s.x,s.y,s.z,
                   ST_X(s.geom),ST_Y(s.geom),s.updated_at
              FROM gis.survey s WHERE {' AND '.join(where)} ORDER BY s.source_row_id,s.id LIMIT 5000
        """, params)
        rows = cursor.fetchall()
    points = [{"id": r[0], "source_id": r[1], "source_row_id": r[2],
               "raw_x": r[3], "raw_y": r[4], "raw_z": r[5], "raw_crs": r[6],
               "raw_code": r[7], "raw_geoid_model": r[8], "x": r[9], "y": r[10],
               "z": r[11], "longitude": r[12], "latitude": r[13],
               "updated_at": r[14].isoformat() if r[14] else None} for r in rows]
    return JsonResponse({"ok": True, "project_id": str(project.id), "points": points},
                        json_dumps_params={"ensure_ascii": False})


@login_required
@require_POST
def project_survey_reapply_preview_api(request, project_id):
    alias, project, plan = _context(request, project_id, write=True)
    return _response(lambda: preview_survey_reapply(
        alias, project_id=str(project.id), plan=plan, payload=_body(request)))


@login_required
@require_POST
def project_survey_reapply_api(request, project_id):
    alias, project, plan = _context(request, project_id, write=True)
    return _response(lambda: apply_survey_reapply(
        alias, project_id=str(project.id), plan=plan, payload=_body(request), actor_ref=_actor_ref(request)))
