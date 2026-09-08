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
    bearer_token_from_request,
    hydrate_qfield_handoff_request,
    hydrate_qfield_handoff_token,
    issue_qfield_ticket,
    parse_qfield_claim_token,
    qfield_ticket_runtime_enabled,
)
from .qfield_handoff import consume_pending_handoff
from .qfield_package import QFIELD_PACKAGE_VERSION, QFIELD_PLUGIN_RUNTIME_VERSION
from .qfield_persistent import (
    QFIELD_PERSISTENT_PROTOCOL_VERSION,
    qfield_install_id,
    qfield_schema_fingerprint,
)


_MAX_HANDOFF_BODY_BYTES = 64 * 1024


def _json_body(request) -> dict | None:
    content_length = int(request.META.get("CONTENT_LENGTH") or 0)
    if content_length > _MAX_HANDOFF_BODY_BYTES:
        return None
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return body if isinstance(body, dict) else None


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


def _issue_session_response(request, project_id, payload: dict, body: dict):
    alias = require_tenant_context(request)
    project = get_object_or_404(Project.objects.using(alias), id=project_id)
    plan = project_layer_plan(alias, project.id)
    if not plan.get("ready"):
        return JsonResponse(
            {"ok": False, "error": "qfield_gis_foundation_unavailable"}, status=503
        )
    if not plan.get("gis_enabled"):
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
            "protocol": "geoflow_qfield_explicit_handoff_v2",
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


@csrf_exempt
@require_POST
def qfield_session_handoff_api(request, project_id):
    """Warm-app direct handoff exchange retained as a compatibility fallback."""

    if not qfield_ticket_runtime_enabled():
        return JsonResponse({"ok": False, "error": "qfield_handoff_not_enabled"}, status=403)
    body = _json_body(request)
    if body is None:
        return JsonResponse({"ok": False, "error": "invalid_handoff_payload"}, status=400)
    payload = hydrate_qfield_handoff_request(request, project_id=str(project_id))
    if payload is None:
        return JsonResponse({"ok": False, "error": "invalid_qfield_handoff"}, status=401)
    return _issue_session_response(request, project_id, payload, body)


@csrf_exempt
@require_POST
def qfield_session_claim_api(request, project_id):
    """Claim a handoff staged by an authenticated GeoFlow browser.

    QField calls this only after the local project/plugin is loaded. The claim
    token stored in the package grants no GIS access and cannot create a pending
    handoff. Without a preceding GeoFlow login + QField-open action this returns
    204 and never mints a fresh access ticket.
    """

    if not qfield_ticket_runtime_enabled():
        return JsonResponse({"ok": False, "error": "qfield_claim_not_enabled"}, status=403)
    body = _json_body(request)
    if body is None:
        return JsonResponse({"ok": False, "error": "invalid_claim_payload"}, status=400)

    claim_token = bearer_token_from_request(request)
    claim = parse_qfield_claim_token(claim_token, project_id=str(project_id))
    if claim is None:
        return JsonResponse({"ok": False, "error": "invalid_qfield_claim"}, status=401)

    expected_install_id = qfield_install_id(project_id)
    install_id = str(body.get("install_id") or "")
    if install_id != expected_install_id:
        return JsonResponse({"ok": False, "error": "qfield_install_identity_mismatch"}, status=409)

    handoff_token = consume_pending_handoff(
        project_id=str(project_id),
        user_id=str(claim.get("user_id") or ""),
        group_id=str(claim.get("group_id") or ""),
        install_id=install_id,
    )
    if not handoff_token:
        response = JsonResponse(
            {"ok": True, "pending": False, "project_id": str(project_id)},
            status=200,
        )
        response["Cache-Control"] = "private, no-store"
        return response

    payload = hydrate_qfield_handoff_token(
        request,
        project_id=str(project_id),
        token=handoff_token,
    )
    if payload is None:
        return JsonResponse({"ok": False, "error": "invalid_pending_qfield_handoff"}, status=401)

    # A claim credential is identity-bound. Never allow another user/group's
    # staged handoff to be consumed even if a cache key collision were possible.
    if (
        str(payload.get("user_id") or "") != str(claim.get("user_id") or "")
        or str(payload.get("group_id") or "") != str(claim.get("group_id") or "")
        or str(payload.get("alias") or "") != str(claim.get("alias") or "")
    ):
        return JsonResponse({"ok": False, "error": "qfield_claim_identity_mismatch"}, status=403)

    return _issue_session_response(request, project_id, payload, body)
