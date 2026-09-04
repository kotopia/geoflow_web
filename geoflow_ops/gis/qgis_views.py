from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_GET

from control.gf_authz.permissions import gf_has_perm
from geoflow_ops.models import Project
from geoflow_ops.services.entity_access import require_tenant_context
from geoflow_ops.services.project_access import project_access_policy

from .layer_plan import gis_enabled_project_ids, project_layer_plan
from .qgis_manifest import build_qgis_manifest


def _require_qgis_context(request):
    alias = require_tenant_context(request)
    if not gf_has_perm(request, "maps.view"):
        raise PermissionDenied("Permission denied")
    return alias


def _project_queryset(alias):
    return Project.objects.using(alias).order_by("-start_date", "name")


def _require_project(request, alias, project_id):
    project = get_object_or_404(_project_queryset(alias), id=project_id)
    policy = project_access_policy(request, alias)
    if not policy.can_webgis_read(project.id):
        raise PermissionDenied("Permission denied")
    plan = project_layer_plan(alias, project.id)
    if plan.get("ready") and not plan.get("gis_enabled"):
        raise Http404("GIS is not enabled by this project's business scope.")
    return project, policy, plan


@login_required
@require_GET
def qgis_projects_api(request):
    """Return only GIS-enabled projects visible to the authenticated QGIS user."""

    alias = _require_qgis_context(request)
    policy = project_access_policy(request, alias)
    queryset = _project_queryset(alias)

    visible_ids = policy.visible_project_ids()
    if visible_ids is not None:
        queryset = queryset.filter(pk__in=visible_ids)

    enabled_ids = gis_enabled_project_ids(alias)
    if enabled_ids is not None:
        queryset = queryset.filter(pk__in=enabled_ids)

    results = []
    for project in queryset[:200]:
        plan = project_layer_plan(alias, project.id)
        if plan.get("ready") and not plan.get("gis_enabled"):
            continue
        member = policy.membership(project.id)
        results.append(
            {
                "id": str(project.id),
                "code": project.code or "",
                "name": project.name or "",
                "status": project.status or "",
                "member_role": member["member_role"] if member else None,
                "can_write": policy.can_webgis_write(project.id),
                "profile": plan.get("profile"),
                "capabilities": plan.get("capabilities") or [],
                "layer_count": len(plan.get("layers") or []),
                "manifest_url": reverse(
                    "gis:qgis_project_manifest_api",
                    kwargs={"project_id": project.id},
                ),
            }
        )

    return JsonResponse(
        {
            "results": results,
            "count": len(results),
            "scope": policy.mode,
        },
        json_dumps_params={"ensure_ascii": False},
    )


@login_required
@require_GET
def qgis_project_manifest_api(request, project_id):
    """Materialization manifest consumed by the GeoFlow QGIS Connector MVP."""

    alias = _require_qgis_context(request)
    project, policy, plan = _require_project(request, alias, project_id)
    geojson_path = reverse(
        "gis:project_layer_geojson_api",
        kwargs={"project_id": project.id},
    )
    manifest = build_qgis_manifest(
        project={
            "id": project.id,
            "code": project.code,
            "name": project.name,
            "status": project.status,
        },
        plan=plan,
        can_write=policy.can_webgis_write(project.id),
        layer_geojson_path=geojson_path,
    )
    return JsonResponse(manifest, json_dumps_params={"ensure_ascii": False})
