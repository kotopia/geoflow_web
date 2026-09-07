from __future__ import annotations

import json

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from geoflow_ops.models import Project
from geoflow_ops.services.entity_access import require_tenant_context

from .changeset import project_current_revision
from .layer_plan import project_layer_plan
from .qfield_auth import (
    QFIELD_HANDOFF_MAX_AGE_SECONDS,
    QFIELD_TICKET_MAX_AGE_SECONDS,
    hydrate_qfield_handoff_request,
    issue_qfield_ticket,
    qfield_ticket_runtime_enabled,
)
from .qfield_package import QFIELD_PACKAGE_VERSION, QFIELD_PLUGIN_RUNTIME_VERSION
from .qfield_persistent import (
    QFIELD_PERSISTENT_PROTOCOL_VERSION,
    qfield_install_id,
    qfield_schema_fingerprint,
)


_MAX_HANDOFF_BODY_BYTES = 64 * 1024


def _package_compatibility(alias: str, project, plan: dict, client: dict) -> dict:
    schema_fingerprint = qfield_schema_fingerprint(alias, plan)
    server = {
        "version": QFIELD_PACKAGE_VERSION,
        "plugin_runtime": QFIELD_PLUGIN_RUNTIME_VERSION,
        "schema_fingerprint": schema_fingerprint,
        "install_id": qfield_install_id(project.id),
        "persistent_protocol": QFIELD_PERSISTENT_PROTOCOL_VERSION,
    }
    reasons = []
    if str(client.get("package_version") or "") != server["version"]:
        reasons.append("package_version_changed")
    if str(client.get("plugin_runtime_version") or "") != server["plugin_runtime"]:
        reasons.append("plugin_runtime_changed")
    if str(client.get("schema_fingerprint") or "") != server["schema_fingerprint"]:
        reasons.append("schema_contract_changed")
    if str(client.get("install_id") or "") not in ("", server["install_id"]):
        reasons.append("install_identity_mismatch")
    server["requires_update"] = bool(reasons)
    server["reason"] = ",".join(reasons)
    return server


@csrf_exempt
@require_POST
def qfield_session_handoff_api(request, project_id):
    """Exchange an explicit GeoFlow-authenticated handoff for one access ticket.

    There is deliberately no persistent refresh credential. A QField access
    ticket expires after 12 hours and cannot be extended by QField activity.
    After expiry the local project can still be opened and edited, but server
    read/write access resumes only after the user authenticates in GeoFlow and
    presses "QField에서 열기" again. The browser supplies a five-minute
    project-scoped handoff token in the Authorization header.
    """

    if not qfield_ticket_runtime_enabled():
        return JsonResponse({"ok": False, "error": "qfield_handoff_not_enabled"}, status=403)
    content_length = int(request.META.get("CONTENT_LENGTH") or 0)
    if content_length > _MAX_HANDOFF_BODY_BYTES:
        return JsonResponse({"ok": False, "error": "handoff_body_too_large"}, status=413)
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"ok": False, "error": "invalid_json"}, status=400)
    if not isinstance(body, dict):
        return JsonResponse({"ok": False, "error": "invalid_handoff_payload"}, status=400)

    payload = hydrate_qfield_handoff_request(request, project_id=str(project_id))
    if payload is None:
        return JsonResponse({"ok": False, "error": "invalid_qfield_handoff"}, status=401)

    alias = require_tenant_context(request)
    project = get_object_or_404(Project.objects.using(alias), id=project_id)
    plan = project_layer_plan(alias, project.id)
    if plan.get("ready") and not plan.get("gis_enabled"):
        return JsonResponse({"ok": False, "error": "qfield_project_not_gis_enabled"}, status=404)

    write_authorized = bool(payload.get("write_authorized"))
    access_token = issue_qfield_ticket(
        project_id=str(project.id),
        alias=alias,
        group_id=str(payload.get("group_id") or ""),
        user_id=str(payload.get("user_id") or ""),
        email=str(payload.get("email") or ""),
        roles=payload.get("roles") or [],
        perms=payload.get("perms") or [],
        write_authorized=write_authorized,
    )
    package = _package_compatibility(alias, project, plan, body)

    response = JsonResponse(
        {
            "ok": True,
            "protocol": "geoflow_qfield_explicit_handoff_v1",
            "project_id": str(project.id),
            "auth": {
                "scheme": "Bearer",
                "token": access_token,
                "expires_in": QFIELD_TICKET_MAX_AGE_SECONDS,
                "renewal": "explicit_geoflow_handoff_only",
                "write_authorized": write_authorized,
                "dev_poc_only": True,
            },
            "handoff": {
                "max_age_seconds": QFIELD_HANDOFF_MAX_AGE_SECONDS,
                "requires_authenticated_geoflow_browser": True,
            },
            "package": package,
            "sync": {
                "current_revision": project_current_revision(alias, str(project.id)),
                "outbox_survives_auth_expiry": True,
                "outbox_survives_package_update": True,
            },
        },
        json_dumps_params={"ensure_ascii": False},
    )
    response["Cache-Control"] = "private, no-store"
    return response
