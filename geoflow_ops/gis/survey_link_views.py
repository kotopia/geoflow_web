from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from control.gf_authz.permissions import gf_has_perm
from geoflow_ops.services.entity_access import require_tenant_context

from .events import publish_project_change_event
from .qfield_auth import qfield_ticket_required
from .qfield_sync_views import _ticket_project_and_plan
from .qgis_sync import SyncConflict, SyncRejected
from .sync_views import _actor_ref, _require_project
from .changeset import ChangesetUnavailable
from .survey_links import apply_survey_link_changeset, list_survey_links


MAX_BODY_BYTES = 5 * 1024 * 1024


def _result_or_error(callback):
    try:
        return callback()
    except SyncConflict as exc:
        return JsonResponse(
            {"ok": False, "error": "survey_link_conflict", "conflicts": exc.conflicts},
            status=409,
            json_dumps_params={"ensure_ascii": False},
        )
    except ChangesetUnavailable as exc:
        return JsonResponse(
            {"ok": False, "error": "survey_link_unavailable", "message": str(exc)},
            status=503,
            json_dumps_params={"ensure_ascii": False},
        )
    except SyncRejected as exc:
        return JsonResponse(
            {"ok": False, "error": "survey_link_rejected", "message": str(exc), "details": exc.details},
            status=400,
            json_dumps_params={"ensure_ascii": False},
        )
    except DatabaseError:
        return JsonResponse({"ok": False, "error": "survey_link_failed"}, status=503)


def _parse_body(request):
    if int(request.META.get("CONTENT_LENGTH") or 0) > MAX_BODY_BYTES:
        raise SyncRejected("Survey-link Changeset body is too large")
    try:
        return json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SyncRejected("Survey-link Changeset body must be valid JSON") from exc


def _query(alias, project_id, plan, request):
    links = list_survey_links(
        alias,
        project_id=str(project_id),
        plan=plan,
        survey_id=request.GET.get("survey_id"),
        standard_name=request.GET.get("layer"),
        target_id=request.GET.get("target_id"),
        limit=request.GET.get("limit", "1000"),
    )
    return JsonResponse(
        {"ok": True, "protocol": "survey_link_v1", "project_id": str(project_id), "links": links},
        json_dumps_params={"ensure_ascii": False},
    )


def _apply(alias, project, plan, request):
    result = apply_survey_link_changeset(
        alias,
        project_id=str(project.id),
        plan=plan,
        payload=_parse_body(request),
        actor_ref=_actor_ref(request),
    )
    if not result.get("replayed"):
        publish_project_change_event(result)
    return JsonResponse(result, json_dumps_params={"ensure_ascii": False})


@login_required
@require_GET
def project_survey_links_api(request, project_id):
    alias = require_tenant_context(request)
    if not gf_has_perm(request, "maps.view"):
        raise PermissionDenied("Permission denied")
    project, _policy, plan = _require_project(request, alias, project_id)
    return _result_or_error(lambda: _query(alias, project.id, plan, request))


@login_required
@require_POST
def project_survey_link_changeset_api(request, project_id):
    alias = require_tenant_context(request)
    if not gf_has_perm(request, "maps.view"):
        raise PermissionDenied("Permission denied")
    project, policy, plan = _require_project(request, alias, project_id)
    if not policy.can_webgis_write(project.id):
        raise PermissionDenied("Permission denied")
    return _result_or_error(lambda: _apply(alias, project, plan, request))


@qfield_ticket_required(write=False)
@require_GET
def qfield_survey_links_api(request, project_id):
    alias = require_tenant_context(request)
    project, plan = _ticket_project_and_plan(request, alias, project_id, require_write=False)
    return _result_or_error(lambda: _query(alias, project.id, plan, request))


@csrf_exempt
@qfield_ticket_required(write=True)
@require_POST
def qfield_survey_link_changeset_api(request, project_id):
    alias = require_tenant_context(request)
    project, plan = _ticket_project_and_plan(request, alias, project_id)
    return _result_or_error(lambda: _apply(alias, project, plan, request))
