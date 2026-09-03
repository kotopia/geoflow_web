from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from control.gf_authz.permissions import gf_has_perm
from geoflow_ops.models import Project
from geoflow_ops.services.entity_access import require_tenant_context

from .registry import domain_counts, feature_rows


def _require_gis_view(request):
    alias = require_tenant_context(request)
    if not gf_has_perm(request, "maps.view"):
        raise PermissionDenied("Permission denied")
    return alias


def _project_queryset(alias):
    return Project.objects.using(alias).order_by("-start_date", "name")


@login_required
@require_GET
def dashboard(request):
    alias = _require_gis_view(request)
    projects = list(_project_queryset(alias)[:200])
    rows = feature_rows()
    return render(
        request,
        "geoflow_ops/gis/dashboard.html",
        {
            "projects": projects,
            "features": rows,
            "domain_counts": domain_counts(),
            "feature_count": len(rows),
        },
    )


@login_required
@require_GET
def project_dashboard(request, project_id):
    alias = _require_gis_view(request)
    project = get_object_or_404(_project_queryset(alias), id=project_id)
    rows = feature_rows()
    return render(
        request,
        "geoflow_ops/gis/project_dashboard.html",
        {
            "project": project,
            "features": rows,
            "domain_counts": domain_counts(),
            "feature_count": len(rows),
        },
    )


@login_required
@require_GET
def layer_registry_api(request):
    _require_gis_view(request)
    return JsonResponse({"features": feature_rows()})
