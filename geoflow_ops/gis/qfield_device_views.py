from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.contrib.gis.geos import GEOSGeometry
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, connections
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from control.gf_authz.permissions import gf_has_perm
from geoflow_ops.models import Project
from geoflow_ops.services.entity_access import require_tenant_context
from geoflow_ops.services.project_access import project_access_policy

from .changeset import (
    ChangesetUnavailable,
    apply_project_changeset,
    changeset_runtime_enabled,
    project_current_revision,
    project_delta,
)
from .events import publish_project_change_event
from .gpkg_snapshot_v2 import _layer_specs, project_geopackage_layer_manifest
from .layer_plan import project_layer_plan
from .qfield_auth import (
    QFIELD_TICKET_MAX_AGE_SECONDS,
    issue_qfield_ticket,
    qfield_ticket_required,
    qfield_ticket_runtime_enabled,
)
from .qgis_sync import SyncConflict, SyncRejected


_MAX_CHANGESET_BODY_BYTES = 50 * 1024 * 1024
_QFIELD_PROTECTED_FIELDS = {
    "id",
    "project_id",
    "created_at",
    "updated_at",
    "created_by",
    "updated_by",
}


def _project_and_plan(request, alias, project_id, *, require_write: bool = False):
    project = get_object_or_404(Project.objects.using(alias), id=project_id)
    policy = project_access_policy(request, alias)
    if not policy.can_webgis_read(project.id):
        raise PermissionDenied("Permission denied")
    if require_write and not policy.can_webgis_write(project.id):
        raise PermissionDenied("Permission denied")
    plan = project_layer_plan(alias, project.id)
    if plan.get("ready") and not plan.get("gis_enabled"):
        raise Http404("GIS is not enabled by this project's business scope.")
    return project, policy, plan


def _project_center(alias: str, project_id, plan: dict) -> list[float] | None:
    connection = connections[alias]
    schema = connection.ops.quote_name("gis")
    extents = []
    try:
        with connection.cursor() as cursor:
            for layer in plan.get("layers") or []:
                physical_name = str(layer.get("physical_name") or "")
                if not physical_name:
                    continue
                cursor.execute("SELECT to_regclass(%s)", [f"gis.{physical_name}"])
                if cursor.fetchone()[0] is None:
                    continue
                table = connection.ops.quote_name(physical_name)
                cursor.execute(
                    f"""
                    SELECT ST_XMin(box), ST_YMin(box), ST_XMax(box), ST_YMax(box)
                      FROM (
                        SELECT ST_Extent(geom) AS box
                          FROM {schema}.{table}
                         WHERE project_id=%s AND geom IS NOT NULL
                      ) s
                    """,
                    [project_id],
                )
                row = cursor.fetchone()
                if row and all(value is not None for value in row):
                    extents.append(tuple(float(value) for value in row))
    except DatabaseError:
        return None
    if not extents:
        return None
    minx = min(row[0] for row in extents)
    miny = min(row[1] for row in extents)
    maxx = max(row[2] for row in extents)
    maxy = max(row[3] for row in extents)
    return [(minx + maxx) / 2.0, (miny + maxy) / 2.0]


def _actor_ref(request) -> str | None:
    user = getattr(request, "user", None)
    pk = getattr(user, "pk", None)
    return str(pk) if pk is not None else None


def _geometry_wkt_to_wkb_hex(value) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("geometry_wkt must be a non-empty WKT string")
    try:
        geometry = GEOSGeometry(text)
    except Exception as exc:
        raise ValueError("geometry_wkt is invalid") from exc
    if geometry.empty:
        raise ValueError("geometry_wkt must not be empty")
    if geometry.srid not in (None, 4326):
        raise ValueError("geometry_wkt must use EPSG:4326")
    geometry.srid = 4326
    return bytes(geometry.wkb).hex()


def _geometry_wkb_hex_to_wkt(value) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        geometry = GEOSGeometry(memoryview(bytes.fromhex(text)))
    except Exception:
        return None
    geometry.srid = 4326
    return geometry.wkt


def _normalize_qfield_changeset_payload(alias: str, plan: dict, payload):
    """Translate QField-friendly WKT and discard protected client fields.

    The authoritative Changeset service still performs the final Layer Plan,
    field, UUID, geometry and authorization validation.  This adapter only
    normalizes the native QField payload into that existing contract.
    """

    if not isinstance(payload, dict):
        return payload
    raw_changes = payload.get("changes")
    if not isinstance(raw_changes, list):
        return payload

    by_standard = {
        spec.standard_name.upper(): spec
        for spec in _layer_specs(alias, plan)
    }
    normalized_changes = []
    for raw in raw_changes:
        if not isinstance(raw, dict):
            normalized_changes.append(raw)
            continue
        change = dict(raw)
        standard_name = str(
            change.get("layer") or change.get("standard_name") or ""
        ).upper()
        spec = by_standard.get(standard_name)
        attributes = change.get("attributes")
        if isinstance(attributes, dict) and spec is not None:
            editable = {
                field.name
                for field in spec.fields
                if field.editable and field.name not in _QFIELD_PROTECTED_FIELDS
            }
            change["attributes"] = {
                str(name): value
                for name, value in attributes.items()
                if str(name) in editable
            }

        if "geometry_wkt" in change:
            if str(change.get("action") or "").lower() == "delete":
                change.pop("geometry_wkt", None)
            elif "geometry_wkb" not in change:
                change["geometry_wkb"] = _geometry_wkt_to_wkb_hex(
                    change.get("geometry_wkt")
                )
                change.pop("geometry_wkt", None)
            else:
                change.pop("geometry_wkt", None)
        normalized_changes.append(change)

    return {**payload, "changes": normalized_changes}


def _augment_qfield_delta_geometry(result: dict) -> dict:
    changes = result.get("changes")
    if not isinstance(changes, list):
        return result
    output = []
    for raw in changes:
        if not isinstance(raw, dict):
            output.append(raw)
            continue
        row = dict(raw)
        geometry_wkt = _geometry_wkb_hex_to_wkt(row.get("geometry_wkb"))
        if geometry_wkt:
            row["geometry_wkt"] = geometry_wkt
        output.append(row)
    return {**result, "changes": output}


@login_required
@require_GET
def qfield_bootstrap_api(request, project_id):
    """Issue a short-lived, project-scoped QField PoC session descriptor."""

    alias = require_tenant_context(request)
    if not gf_has_perm(request, "maps.view"):
        raise PermissionDenied("Permission denied")
    project, policy, plan = _project_and_plan(request, alias, project_id)
    if not qfield_ticket_runtime_enabled() or not changeset_runtime_enabled(alias):
        return JsonResponse(
            {"ok": False, "error": "qfield_bootstrap_not_enabled"},
            status=403,
        )

    group_id = request.session.get("group_id") or request.session.get("group_uuid")
    user = getattr(request, "user", None)
    email = str(
        getattr(user, "email", None)
        or getattr(user, "username", None)
        or ""
    ).strip().lower()
    if not group_id or not email or getattr(user, "pk", None) is None:
        return JsonResponse({"ok": False, "error": "qfield_identity_incomplete"}, status=403)

    write_authorized = bool(policy.can_webgis_write(project.id))
    token = issue_qfield_ticket(
        project_id=str(project.id),
        alias=alias,
        group_id=str(group_id),
        user_id=str(user.pk),
        email=email,
        roles=request.session.get("gf_roles") or [],
        perms=request.session.get("gf_perms") or [],
        write_authorized=write_authorized,
    )
    layers = project_geopackage_layer_manifest(alias, plan)
    response = JsonResponse(
        {
            "ok": True,
            "protocol": "qfield_bootstrap_v1",
            "project": {
                "id": str(project.id),
                "code": project.code or "",
                "name": project.name or "",
                "status": project.status or "",
                "start_date": project.start_date.isoformat() if project.start_date else None,
                "end_date": project.end_date.isoformat() if project.end_date else None,
            },
            "profile": plan.get("profile"),
            "capabilities": plan.get("capabilities") or [],
            "layers": layers,
            "initial_center": {
                "priority": ["gps", "last_location", "project_center", "map_fallback"],
                "project_center": _project_center(alias, project.id, plan),
                "crs": "EPSG:4326",
            },
            "roaming": {
                "cell_size_m": 250,
                "active_radius_m": 300,
                "prefetch_radius_m": 750,
                "movement_threshold_m": 100,
                "eviction": "lru_clean_cells_only",
                "dirty_never_evict": True,
                "pending_never_evict": True,
            },
            "auth": {
                "scheme": "Bearer",
                "token": token,
                "expires_in": QFIELD_TICKET_MAX_AGE_SECONDS,
                "dev_poc_only": True,
            },
            "transport": {
                "roaming_plan_url": reverse(
                    "gis:qfield_roaming_plan_api",
                    kwargs={"project_id": project.id},
                ),
                "roaming_cell_url": reverse(
                    "gis:qfield_roaming_cell_api",
                    kwargs={"project_id": project.id},
                ),
                "delta_url": reverse(
                    "gis:qfield_device_delta_api",
                    kwargs={"project_id": project.id},
                ),
                "changeset_url": reverse(
                    "gis:qfield_device_changeset_api",
                    kwargs={"project_id": project.id},
                ),
            },
            "sync": {
                "write_authorized": write_authorized,
                "current_revision": project_current_revision(alias, str(project.id)),
                "strategy": "field_patch_last_successful_server_write_wins",
            },
        },
        json_dumps_params={"ensure_ascii": False},
    )
    response["Cache-Control"] = "private, no-store"
    return response


@qfield_ticket_required(write=False)
@require_GET
def qfield_device_delta_api(request, project_id):
    alias = require_tenant_context(request)
    project, _policy, _plan = _project_and_plan(request, alias, project_id)
    try:
        result = project_delta(
            alias,
            project_id=str(project.id),
            since_revision=int(request.GET.get("since", "0")),
            limit=int(request.GET.get("limit", "1000")),
        )
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "invalid_cursor"}, status=400)
    except ChangesetUnavailable as exc:
        return JsonResponse(
            {"ok": False, "error": "delta_unavailable", "message": str(exc)},
            status=503,
        )
    except SyncRejected as exc:
        return JsonResponse({"ok": False, "error": "delta_rejected", "message": str(exc)}, status=400)
    except DatabaseError:
        return JsonResponse({"ok": False, "error": "delta_failed"}, status=503)
    return JsonResponse(
        _augment_qfield_delta_geometry(result),
        json_dumps_params={"ensure_ascii": False},
    )


@csrf_exempt
@qfield_ticket_required(write=True)
@require_POST
def qfield_device_changeset_api(request, project_id):
    """Bearer-authenticated Changeset endpoint for the QField PoC.

    CSRF is intentionally not used on this native-client-only route; the signed
    Authorization bearer ticket is mandatory and project scoped.
    """

    alias = require_tenant_context(request)
    project, policy, plan = _project_and_plan(request, alias, project_id, require_write=True)
    if not policy.can_webgis_write(project.id):
        raise PermissionDenied("Permission denied")

    content_length = int(request.META.get("CONTENT_LENGTH") or 0)
    if content_length > _MAX_CHANGESET_BODY_BYTES:
        return JsonResponse({"ok": False, "error": "changeset_too_large"}, status=413)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"ok": False, "error": "invalid_json"}, status=400)

    try:
        payload = _normalize_qfield_changeset_payload(alias, plan, payload)
    except ValueError as exc:
        return JsonResponse(
            {"ok": False, "error": "invalid_geometry_wkt", "message": str(exc)},
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
        )
    except ChangesetUnavailable as exc:
        return JsonResponse(
            {"ok": False, "error": "changeset_unavailable", "message": str(exc)},
            status=503,
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
        )
    except DatabaseError:
        return JsonResponse({"ok": False, "error": "changeset_failed"}, status=503)

    if not result.get("replayed"):
        publish_project_change_event(result)
    return JsonResponse(result, json_dumps_params={"ensure_ascii": False})
