"""Project-scoped, read-only GIS photo policy delivery to WebGIS/QGIS."""
from __future__ import annotations

import re

from django.contrib.auth.decorators import login_required
from django.db import connections, DatabaseError
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from control.services import gis_photo_policy as definitions
from .qgis_views import _require_project, _require_qgis_context

_SAFE_TABLE = re.compile(r"^[a-z_][a-z0-9_]*$")


def central_photo_snapshot():
    with connections["default"].cursor() as cur:
        return definitions.snapshot(cur) if definitions.ready(cur) else None


def _paired_scopes(alias, project_id):
    with connections[alias].cursor() as cur:
        cur.execute("SELECT lv2_id::text,lv3_id::text FROM prj.scope_item WHERE project_id=%s", [project_id])
        return cur.fetchall()


def _feature_ext_data(alias, project_id, layer, feature_id):
    physical = str(layer["physical_name"])
    if not _SAFE_TABLE.fullmatch(physical):
        raise definitions.PhotoPolicyError("레이어 식별자가 올바르지 않습니다.")
    with connections[alias].cursor() as cur:
        cur.execute(f'SELECT ext_data FROM gis."{physical}" WHERE id=%s AND project_id=%s',
                    [feature_id, project_id])
        row = cur.fetchone()
    if row is None:
        raise definitions.PhotoPolicyError("프로젝트 객체를 찾을 수 없습니다.")
    return row[0]


@login_required
@require_GET
def project_photo_policies_api(request, project_id):
    alias = _require_qgis_context(request)
    project, _policy, plan = _require_project(request, alias, project_id)
    try:
        data = central_photo_snapshot()
        if data is None:
            return JsonResponse({"ok":False,"error":"photo_policy_schema_pending"}, status=503)
        scopes = _paired_scopes(alias, project.id)
        selected = {str(layer["id"]):layer for layer in plan["layers"]}
        requested = request.GET.get("layer_id")
        feature_id = request.GET.get("feature_id")
        if requested and requested not in selected:
            return JsonResponse({"ok":False,"error":"layer_not_in_project"}, status=404)
        if feature_id and not requested:
            return JsonResponse({"ok":False,"error":"layer_id_required"}, status=400)
        if feature_id:
            feature_id = definitions.uid(feature_id,"객체")
        output = []
        for layer_id, layer in selected.items():
            if requested and layer_id != requested:
                continue
            ext_data = _feature_ext_data(alias,project.id,layer,feature_id) if feature_id else {}
            result = definitions.resolve(data,scopes,layer_id,ext_data)
            output.append({"layer_id":layer_id,"standard_name":layer["standard_name"],
                           "feature_id":feature_id,"policy":result})
        response = JsonResponse({"ok":True,"project_id":str(project.id),
            "photo_policy_revision":data["revision"],"layers":output},
            json_dumps_params={"ensure_ascii":False})
        response["Cache-Control"] = "private, no-store"
        return response
    except definitions.PhotoPolicyConflict as exc:
        return JsonResponse({"ok":False,"error":exc.code,"detail":str(exc)}, status=409)
    except definitions.PhotoPolicyError as exc:
        return JsonResponse({"ok":False,"error":str(exc)}, status=409)
    except DatabaseError:
        return JsonResponse({"ok":False,"error":"photo_policy_unavailable"}, status=503)
