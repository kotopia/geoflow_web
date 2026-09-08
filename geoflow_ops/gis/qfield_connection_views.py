"""Strict-development browser-authorized install-claim recovery."""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from control.gf_authz.permissions import gf_has_perm
from geoflow_ops.services.entity_access import require_tenant_context
from .changeset import changeset_runtime_enabled
from .qfield_auth import issue_qfield_claim_token, qfield_ticket_runtime_enabled


def _project_identity(request, alias, project_id):
    from .qfield_package_views import _project_and_plan, _browser_identity
    project, policy, _plan = _project_and_plan(request, alias, project_id)
    return project, _browser_identity(request, alias, project, policy)


@login_required
@require_GET
def qfield_connection_recovery_api(request, project_id):
    """Development-only replacement claim; grants no GIS access or pending handoff."""
    alias = require_tenant_context(request)
    if not gf_has_perm(request, "maps.view"):
        raise PermissionDenied("Permission denied")
    if not qfield_ticket_runtime_enabled() or not changeset_runtime_enabled(alias):
        return JsonResponse({"ok": False, "error": "qfield_recovery_not_enabled"}, status=403)
    project, identity = _project_identity(request, alias, project_id)
    if identity is None:
        return JsonResponse({"ok": False, "error": "qfield_identity_incomplete"}, status=403)
    token = issue_qfield_claim_token(**{
        key: identity[key] for key in ("project_id", "alias", "group_id", "user_id", "email")
    })
    response = JsonResponse({
        "format": "geoflow_qfield_claim_recovery_v1",
        "project_id": str(project.id),
        "server_url": request.build_absolute_uri("/").rstrip("/"),
        "claim_token": token,
    })
    response["Cache-Control"] = "private, no-store"
    response["Content-Disposition"] = 'attachment; filename="geoflow-qfield-connection.json"'
    response["X-Content-Type-Options"] = "nosniff"
    return response
