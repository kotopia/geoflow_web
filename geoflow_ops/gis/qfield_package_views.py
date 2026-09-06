from __future__ import annotations

import os

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_GET

from control.gf_authz.permissions import gf_has_perm
from geoflow_ops.services.entity_access import require_tenant_context

from .changeset import changeset_runtime_enabled
from .qfield_auth import (
    hydrate_qfield_package_import_request,
    issue_qfield_ticket,
    qfield_ticket_runtime_enabled,
)
from .qfield_device_views import _project_and_plan, _project_center
from .qfield_package import build_qfield_bootstrap_zip


class _DeletingFile:
    """File wrapper that removes a temporary package after FileResponse closes."""

    def __init__(self, path):
        self.path = str(path)
        self.handle = open(self.path, "rb")

    def __getattr__(self, name):
        return getattr(self.handle, name)

    def close(self):
        try:
            self.handle.close()
        finally:
            try:
                os.remove(self.path)
            except OSError:
                pass


def _safe_filename(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in str(value or ""))
    return cleaned.strip("._") or "project"


def _package_response(request, alias, project, policy, plan):
    if not qfield_ticket_runtime_enabled() or not changeset_runtime_enabled(alias):
        return JsonResponse({"ok": False, "error": "qfield_package_not_enabled"}, status=403)

    group_id = request.session.get("group_id") or request.session.get("group_uuid")
    user = getattr(request, "user", None)
    email = str(
        getattr(user, "email", None)
        or getattr(user, "username", None)
        or ""
    ).strip().lower()
    if not group_id or not email or getattr(user, "pk", None) is None:
        return JsonResponse({"ok": False, "error": "qfield_identity_incomplete"}, status=403)

    token = issue_qfield_ticket(
        project_id=str(project.id),
        alias=alias,
        group_id=str(group_id),
        user_id=str(user.pk),
        email=email,
        roles=request.session.get("gf_roles") or [],
        perms=request.session.get("gf_perms") or [],
        write_authorized=bool(policy.can_webgis_write(project.id)),
    )
    roaming_plan_url = reverse(
        "gis:qfield_roaming_plan_api",
        kwargs={"project_id": project.id},
    )
    roaming_cell_url = reverse(
        "gis:qfield_roaming_cell_api",
        kwargs={"project_id": project.id},
    )
    zip_path, layer_count = build_qfield_bootstrap_zip(
        alias,
        project={
            "id": str(project.id),
            "code": project.code or "",
            "name": project.name or "",
            "status": project.status or "",
        },
        plan=plan,
        server_url=request.build_absolute_uri("/").rstrip("/"),
        token=token,
        roaming_plan_url=roaming_plan_url,
        roaming_cell_url=roaming_cell_url,
        project_center=_project_center(alias, project.id, plan),
    )

    response = FileResponse(
        _DeletingFile(zip_path),
        content_type="application/zip",
        as_attachment=True,
        filename=f"geoflow-qfield-{_safe_filename(project.code or project.id)}.zip",
    )
    response["X-GeoFlow-Project"] = str(project.id)
    response["X-GeoFlow-QField-Package-Version"] = "0.2"
    response["X-GeoFlow-Layer-Count"] = str(layer_count)
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_GET
def qfield_package_api(request, project_id):
    """Browser-session ZIP download retained as a manual fallback."""

    alias = require_tenant_context(request)
    if not gf_has_perm(request, "maps.view"):
        raise PermissionDenied("Permission denied")
    project, policy, plan = _project_and_plan(request, alias, project_id)
    return _package_response(request, alias, project, policy, plan)


@require_GET
def qfield_package_import_api(request, project_id):
    """Package endpoint consumed by qfield://local?import=... .

    QField performs this HTTP GET outside the browser cookie jar, so a
    five-minute purpose-specific signed URL token hydrates the same tenant and
    project authorization boundary.  It is development-PoC only; production
    will use a separately reviewed revocable/one-time device handoff.
    """

    payload = hydrate_qfield_package_import_request(
        request,
        project_id=str(project_id),
    )
    if payload is None:
        return JsonResponse({"ok": False, "error": "invalid_qfield_package_import"}, status=401)

    alias = require_tenant_context(request)
    if not gf_has_perm(request, "maps.view"):
        raise PermissionDenied("Permission denied")
    project, policy, plan = _project_and_plan(request, alias, project_id)
    return _package_response(request, alias, project, policy, plan)
