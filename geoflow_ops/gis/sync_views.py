from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from control.gf_authz.permissions import gf_has_perm
from geoflow_ops.models import Project
from geoflow_ops.services.entity_access import require_tenant_context
from geoflow_ops.services.project_access import project_access_policy

from .changeset import ChangesetUnavailable, apply_project_changeset, project_delta
from .events import publish_project_change_event
from .layer_plan import project_layer_plan
from .qgis_sync import SyncConflict, SyncRejected


_MAX_CHANGESET_BODY_BYTES = 50 * 1024 * 1024


def _require_context(request):
    alias = require_tenant_context(request)
    if not gf_has_perm(request, "maps.view"):
        raise PermissionDenied("Permission denied")
    return alias


def _require_project(request, alias, project_id):
    project = get_object_or_404(
        Project.objects.using(alias).order_by("-start_date", "name"),
        id=project_id,
    )
    policy = project_access_policy(request, alias)
    if not policy.can_webgis_read(project.id):
        raise PermissionDenied("Permission denied")
    plan = project_layer_plan(alias, project.id)
    if plan.get("ready") and not plan.get("gis_enabled"):
        raise Http404("GIS is not enabled by this project's business scope.")
    return project, policy, plan


def _actor_ref(request) -> str | None:
    user = getattr(request, "user", None)
    pk = getattr(user, "pk", None)
    return str(pk) if pk is not None else None


@login_required
@require_POST
def project_changeset_api(request, project_id):
    alias = _require_context(request)
    project, policy, plan = _require_project(request, alias, project_id)
    if not policy.can_webgis_write(project.id):
        raise PermissionDenied("Permission denied")

    content_length = int(request.META.get("CONTENT_LENGTH") or 0)
    if content_length > _MAX_CHANGESET_BODY_BYTES:
        return JsonResponse(
            {"ok": False, "error": "changeset_too_large"},
            status=413,
        )
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse(
            {"ok": False, "error": "invalid_json", "message": "Changeset body must be valid JSON."},
            status=400,
        )

    try:
        result = apply_project_changeset(
            alias,
            project_id=str(project.id),
            plan=plan,
            payload=payload,
            actor_ref=_actor_ref(request),
        )
    except SyncConflict as exc:
        return JsonResponse(
            {
                "ok": False,
                "error": "changeset_conflict",
                "message": "Changeset conflicts with current server object state.",
                "conflicts": exc.conflicts,
            },
            status=409,
            json_dumps_params={"ensure_ascii": False},
        )
    except ChangesetUnavailable as exc:
        return JsonResponse(
            {"ok": False, "error": "changeset_unavailable", "message": str(exc)},
            status=503,
            json_dumps_params={"ensure_ascii": False},
        )
    except SyncRejected as exc:
        return JsonResponse(
            {
                "ok": False,
                "error": "changeset_rejected",
                "message": str(exc),
                "details": exc.details,
            },
            status=400,
            json_dumps_params={"ensure_ascii": False},
        )
    except DatabaseError:
        return JsonResponse(
            {
                "ok": False,
                "error": "changeset_failed",
                "message": "GeoFlow Changeset processing failed.",
            },
            status=503,
        )

    if not result.get("replayed"):
        publish_project_change_event(result)
    return JsonResponse(result, json_dumps_params={"ensure_ascii": False})


@login_required
@require_GET
def project_delta_api(request, project_id):
    alias = _require_context(request)
    project, _policy, _plan = _require_project(request, alias, project_id)

    raw_since = request.GET.get("since", "0")
    raw_limit = request.GET.get("limit", "1000")
    try:
        result = project_delta(
            alias,
            project_id=str(project.id),
            since_revision=int(raw_since),
            limit=int(raw_limit),
        )
    except (TypeError, ValueError):
        return JsonResponse(
            {"ok": False, "error": "invalid_cursor", "message": "since and limit must be integers."},
            status=400,
        )
    except ChangesetUnavailable as exc:
        return JsonResponse(
            {"ok": False, "error": "delta_unavailable", "message": str(exc)},
            status=503,
            json_dumps_params={"ensure_ascii": False},
        )
    except SyncRejected as exc:
        return JsonResponse(
            {"ok": False, "error": "delta_rejected", "message": str(exc)},
            status=400,
            json_dumps_params={"ensure_ascii": False},
        )
    except DatabaseError:
        return JsonResponse(
            {"ok": False, "error": "delta_failed", "message": "GeoFlow Delta processing failed."},
            status=503,
        )

    return JsonResponse(result, json_dumps_params={"ensure_ascii": False})
