from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from control.gf_authz.permissions import gf_has_perm
from geoflow_ops.models import Project
from geoflow_ops.services.entity_access import require_tenant_context
from geoflow_ops.services.project_access import project_access_policy

from .changeset import changeset_runtime_enabled
from .events import realtime_runtime_enabled
from .layer_plan import project_layer_plan
from .realtime_auth import TICKET_MAX_AGE_SECONDS, issue_realtime_ticket


@login_required
@require_GET
def qgis_project_realtime_ticket_api(request, project_id):
    """Issue a short-lived bearer ticket for the QGIS WebSocket handshake.

    The request itself uses the Connector's authenticated HTTP session.  The
    resulting signed ticket is project/tenant scoped and is used only to
    establish the WebSocket; feature data still flows through Delta.
    """
    alias = require_tenant_context(request)
    if not gf_has_perm(request, "maps.view"):
        raise PermissionDenied("Permission denied")

    project = get_object_or_404(
        Project.objects.using(alias),
        id=project_id,
    )
    policy = project_access_policy(request, alias)
    if not policy.can_webgis_write(project.id):
        raise PermissionDenied("Permission denied")

    plan = project_layer_plan(alias, project.id)
    if plan.get("ready") and not plan.get("gis_enabled"):
        raise Http404("GIS is not enabled by this project's business scope.")
    if not realtime_runtime_enabled() or not changeset_runtime_enabled(alias):
        return JsonResponse(
            {"ok": False, "error": "realtime_not_enabled"},
            status=403,
        )

    token = issue_realtime_ticket(
        project_id=str(project.id),
        alias=alias,
        user_id=getattr(request.user, "pk", ""),
    )
    return JsonResponse(
        {
            "ok": True,
            "project_id": str(project.id),
            "token": token,
            "expires_in": TICKET_MAX_AGE_SECONDS,
        },
        json_dumps_params={"ensure_ascii": False},
    )
