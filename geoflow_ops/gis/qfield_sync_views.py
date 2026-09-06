from __future__ import annotations

import datetime as dt
import json
from typing import Any

from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, connections, transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .changeset import ChangesetUnavailable, apply_project_changeset
from .events import publish_project_change_event
from .gpkg_snapshot_v2 import _layer_specs
from .qfield_auth import qfield_ticket_required
from .qfield_device_views import (
    _MAX_CHANGESET_BODY_BYTES,
    _actor_ref,
    _normalize_qfield_changeset_payload,
    _project_and_plan,
)
from .qgis_sync import SyncConflict, SyncRejected
from geoflow_ops.services.entity_access import require_tenant_context


_QFIELD_CHANGESET_PROTOCOL = "geoflow_qfield_changeset_v2"


def _parse_timestamp(value: Any) -> dt.datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, dt.datetime):
        parsed = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = dt.datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _timestamps_match(expected: Any, actual: Any) -> bool:
    left = _parse_timestamp(expected)
    right = _parse_timestamp(actual)
    if left is None or right is None:
        return str(expected or "") == str(actual or "") and bool(expected)
    # QField/Qt can expose a database timestamp at millisecond precision while
    # PostgreSQL stores microseconds.  A sub-millisecond representation delta
    # is the same snapshot version, not a concurrent edit.
    return abs((left - right).total_seconds()) < 0.001


def _latest_feature_revision(alias: str, project_id: str, standard_name: str, object_id: str) -> int:
    with connections[alias].cursor() as cursor:
        cursor.execute(
            """
            SELECT max(revision)
              FROM gis.feature_change_log
             WHERE project_id=%s AND standard_name=%s AND object_id=%s
            """,
            [project_id, standard_name, object_id],
        )
        row = cursor.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _validate_qfield_concurrency(
    alias: str,
    *,
    project_id: str,
    plan: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    """Lock edited server rows and reject stale QField snapshots.

    QField v2 sends the source feature's ``updated_at`` whenever it is
    available.  That protects against edits made by any GeoFlow/QGIS path,
    including writes which did not create a Changeset revision.  The project
    revision is retained as a compatibility fallback for packages where the
    profile did not expose ``updated_at`` yet.
    """

    if not isinstance(payload, dict) or payload.get("protocol") != _QFIELD_CHANGESET_PROTOCOL:
        return

    try:
        base_revision = int(payload.get("base_revision") or 0)
    except (TypeError, ValueError) as exc:
        raise SyncRejected("base_revision must be an integer") from exc

    specs = {spec.standard_name.upper(): spec for spec in _layer_specs(alias, plan)}
    connection = connections[alias]
    schema = connection.ops.quote_name("gis")
    conflicts: list[dict[str, Any]] = []

    for raw in payload.get("changes") or []:
        if not isinstance(raw, dict):
            continue
        action = str(raw.get("action") or "").lower()
        if action not in {"update", "delete"}:
            continue
        standard_name = str(raw.get("layer") or raw.get("standard_name") or "").upper()
        spec = specs.get(standard_name)
        if spec is None:
            continue
        object_id = str(raw.get("id") or "")
        table = connection.ops.quote_name(spec.physical_name)
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT updated_at FROM {schema}.{table} WHERE project_id=%s AND id=%s FOR UPDATE",
                [project_id, object_id],
            )
            row = cursor.fetchone()
        if row is None:
            # The authoritative Changeset service will return the canonical
            # missing-object conflict payload.
            continue

        server_updated_at = row[0]
        base_updated_at = raw.get("base_updated_at")
        if base_updated_at:
            if not _timestamps_match(base_updated_at, server_updated_at):
                conflicts.append(
                    {
                        "layer": standard_name,
                        "id": object_id,
                        "reason": "server_object_changed",
                        "base_updated_at": str(base_updated_at),
                        "server_updated_at": server_updated_at.isoformat() if hasattr(server_updated_at, "isoformat") else str(server_updated_at),
                    }
                )
            continue

        server_revision = _latest_feature_revision(alias, project_id, standard_name, object_id)
        if server_revision > base_revision:
            conflicts.append(
                {
                    "layer": standard_name,
                    "id": object_id,
                    "reason": "server_changed_since_base_revision",
                    "base_revision": base_revision,
                    "server_revision": server_revision,
                }
            )

    if conflicts:
        raise SyncConflict(conflicts)


def _enrich_applied_versions(alias: str, *, project_id: str, plan: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    specs = {spec.standard_name.upper(): spec for spec in _layer_specs(alias, plan)}
    connection = connections[alias]
    schema = connection.ops.quote_name("gis")
    applied = []
    for raw in result.get("applied") or []:
        row = dict(raw)
        if str(row.get("action") or "") != "delete":
            standard_name = str(row.get("layer") or "").upper()
            spec = specs.get(standard_name)
            if spec is not None:
                table = connection.ops.quote_name(spec.physical_name)
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"SELECT updated_at FROM {schema}.{table} WHERE project_id=%s AND id=%s",
                        [project_id, row.get("id")],
                    )
                    version_row = cursor.fetchone()
                if version_row and version_row[0] is not None:
                    value = version_row[0]
                    row["updated_at"] = value.isoformat() if hasattr(value, "isoformat") else str(value)
        applied.append(row)
    return {
        **result,
        "strategy": "feature_updated_at_optimistic_concurrency",
        "applied": applied,
    }


@csrf_exempt
@qfield_ticket_required(write=True)
@require_POST
def qfield_device_changeset_api(request, project_id):
    """Bearer-authenticated, offline-safe QField Changeset endpoint."""

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
        # Keep the optimistic-lock SELECT ... FOR UPDATE locks until the
        # Changeset has committed.  apply_project_changeset() uses a nested
        # atomic block on the same tenant connection.
        with transaction.atomic(using=alias):
            _validate_qfield_concurrency(
                alias,
                project_id=str(project.id),
                plan=plan,
                payload=payload,
            )
            result = apply_project_changeset(
                alias,
                project_id=str(project.id),
                plan=plan,
                payload=payload,
                actor_ref=_actor_ref(request),
            )
            result = _enrich_applied_versions(
                alias,
                project_id=str(project.id),
                plan=plan,
                result=result,
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
        return JsonResponse({"ok": False, "error": "changeset_failed"}, status=503)

    if not result.get("replayed"):
        publish_project_change_event(result)
    return JsonResponse(result, json_dumps_params={"ensure_ascii": False})
