from __future__ import annotations

import os
from urllib.parse import quote, urlencode

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
    issue_qfield_package_import_token,
    issue_qfield_refresh_token,
    issue_qfield_ticket,
    qfield_ticket_runtime_enabled,
)
from .qfield_device_views import _project_and_plan, _project_center
from .qfield_package import (
    QFIELD_PACKAGE_VERSION,
    QFIELD_PLUGIN_RUNTIME_VERSION,
    build_qfield_bootstrap_zip,
)
from .qfield_persistent import (
    QFIELD_PERSISTENT_PROTOCOL_VERSION,
    qfield_install_id,
    qfield_schema_fingerprint,
    upgrade_qfield_bootstrap_zip,
)


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


def _browser_identity(request, alias, project, policy) -> dict | None:
    group_id = request.session.get("group_id") or request.session.get("group_uuid")
    user = getattr(request, "user", None)
    email = str(
        getattr(user, "email", None)
        or getattr(user, "username", None)
        or ""
    ).strip().lower()
    if not group_id or not email or getattr(user, "pk", None) is None:
        return None
    return {
        "project_id": str(project.id),
        "alias": alias,
        "group_id": str(group_id),
        "user_id": str(user.pk),
        "email": email,
        "roles": request.session.get("gf_roles") or [],
        "perms": request.session.get("gf_perms") or [],
        "write_authorized": bool(policy.can_webgis_write(project.id)),
    }


def _fresh_install_url(request, alias, project, policy) -> str:
    identity = _browser_identity(request, alias, project, policy)
    if identity is None:
        return ""
    token = issue_qfield_package_import_token(
        project_id=identity["project_id"],
        alias=identity["alias"],
        group_id=identity["group_id"],
        user_id=identity["user_id"],
        email=identity["email"],
        roles=identity["roles"],
        perms=identity["perms"],
    )
    import_path = reverse(
        "gis:qfield_package_import_api",
        kwargs={"project_id": project.id},
    )
    package_url = request.build_absolute_uri(
        f"{import_path}?{urlencode({'token': token})}"
    )
    return "qfield://local?import=" + quote(package_url, safe="")


def _launch_url(project) -> str:
    # QField's qfield:// scheme opens the native app. The GeoFlow project
    # plugin consumes this project-scoped action when it is already loaded;
    # on cold start QField will restore its last local project and that project
    # refreshes its own session automatically.
    return "qfield://geoflow?" + urlencode({"project": str(project.id)})


def _package_response(request, alias, project, policy, plan):
    if not qfield_ticket_runtime_enabled() or not changeset_runtime_enabled(alias):
        return JsonResponse({"ok": False, "error": "qfield_package_not_enabled"}, status=403)

    identity = _browser_identity(request, alias, project, policy)
    if identity is None:
        return JsonResponse({"ok": False, "error": "qfield_identity_incomplete"}, status=403)

    token = issue_qfield_ticket(**identity)
    refresh_token = issue_qfield_refresh_token(**identity)
    roaming_plan_url = reverse(
        "gis:qfield_roaming_plan_api",
        kwargs={"project_id": project.id},
    )
    roaming_cell_url = reverse(
        "gis:qfield_roaming_cell_api",
        kwargs={"project_id": project.id},
    )
    session_refresh_url = reverse(
        "gis:qfield_session_refresh_api",
        kwargs={"project_id": project.id},
    )
    schema_fingerprint = qfield_schema_fingerprint(alias, plan)
    install_id = qfield_install_id(project.id)
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
    upgrade_qfield_bootstrap_zip(
        zip_path,
        refresh_token=refresh_token,
        session_refresh_url=session_refresh_url,
        schema_fingerprint=schema_fingerprint,
        install_id=install_id,
    )

    response = FileResponse(
        _DeletingFile(zip_path),
        content_type="application/zip",
        as_attachment=True,
        filename=f"geoflow-qfield-{_safe_filename(project.code or project.id)}.zip",
    )
    response["X-GeoFlow-Project"] = str(project.id)
    response["X-GeoFlow-QField-Install-ID"] = install_id
    response["X-GeoFlow-QField-Package-Version"] = QFIELD_PACKAGE_VERSION
    response["X-GeoFlow-QField-Plugin-Version"] = QFIELD_PLUGIN_RUNTIME_VERSION
    response["X-GeoFlow-QField-Schema-Fingerprint"] = schema_fingerprint
    response["X-GeoFlow-QField-Persistent-Protocol"] = QFIELD_PERSISTENT_PROTOCOL_VERSION
    response["X-GeoFlow-Layer-Count"] = str(layer_count)
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_GET
def qfield_install_status_api(request, project_id):
    """Describe install/open/update state for the browser-side device marker.

    A normal browser cannot inspect QField's Android sandbox, so the same-phone
    browser stores the last successfully requested install contract in
    localStorage. QField itself remains authoritative for data/session state.
    The user can explicitly clear the marker when removing the local project.
    """

    alias = require_tenant_context(request)
    if not gf_has_perm(request, "maps.view"):
        raise PermissionDenied("Permission denied")
    project, policy, plan = _project_and_plan(request, alias, project_id)
    if not qfield_ticket_runtime_enabled() or not changeset_runtime_enabled(alias):
        return JsonResponse({"ok": False, "error": "qfield_install_not_enabled"}, status=403)

    install_url = _fresh_install_url(request, alias, project, policy)
    if not install_url:
        return JsonResponse({"ok": False, "error": "qfield_identity_incomplete"}, status=403)
    schema_fingerprint = qfield_schema_fingerprint(alias, plan)
    response = JsonResponse(
        {
            "ok": True,
            "project": {
                "id": str(project.id),
                "code": project.code or "",
                "name": project.name or "",
            },
            "install": {
                "install_id": qfield_install_id(project.id),
                "package_version": QFIELD_PACKAGE_VERSION,
                "plugin_runtime_version": QFIELD_PLUGIN_RUNTIME_VERSION,
                "schema_fingerprint": schema_fingerprint,
                "persistent_protocol": QFIELD_PERSISTENT_PROTOCOL_VERSION,
                "install_url": install_url,
                "launch_url": _launch_url(project),
                "one_project_folder_per_project_id": True,
                "ordinary_data_change_requires_reinstall": False,
                "outbox_survives_package_update": True,
            },
        },
        json_dumps_params={"ensure_ascii": False},
    )
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
    """First-install/update package endpoint consumed by qfield://local?import=... ."""

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
