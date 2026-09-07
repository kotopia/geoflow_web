from __future__ import annotations

import logging
import os
import re
import sqlite3

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, connections
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from control.gf_authz.permissions import gf_has_perm
from geoflow_ops.models import Project
from geoflow_ops.services.entity_access import require_tenant_context
from geoflow_ops.services.project_access import project_access_policy

from .changeset import changeset_runtime_enabled, project_current_revision
from .gpkg import project_geopackage_layer_manifest
from .gpkg_syncable import build_syncable_project_geopackage
from .layer_plan import gis_enabled_project_ids, project_layer_plan
from .qgis_manifest import build_qgis_manifest
from .qgis_sync import SyncConflict, SyncRejected, sync_runtime_enabled
from .qgis_sync_v2 import sync_project_geopackage_v2
from .server_snapshot_cache import get_or_build_server_snapshot


logger = logging.getLogger(__name__)
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_MAX_SYNC_PACKAGE_BYTES = 250 * 1024 * 1024


def _dev_sync_diag_enabled() -> bool:
    return settings.DEBUG and os.getenv("GEOFLOW_DEV_RUNTIME_STRICT") == "1"


def _dev_sync_diag(stage: str, **fields) -> None:
    if not _dev_sync_diag_enabled():
        return
    suffix = " ".join(f"{key}={value}" for key, value in fields.items())
    logger.warning("DEV-QGIS-SYNC %s%s", stage, f" {suffix}" if suffix else "")


def _dev_snapshot_diag(stage: str, **fields) -> None:
    if not _dev_sync_diag_enabled():
        return
    suffix = " ".join(f"{key}={value}" for key, value in fields.items())
    logger.warning("DEV-QGIS-SNAPSHOT %s%s", stage, f" {suffix}" if suffix else "")


def _require_qgis_context(request):
    alias = require_tenant_context(request)
    if not gf_has_perm(request, "maps.view"):
        raise PermissionDenied("Permission denied")
    return alias


def _project_queryset(alias):
    return Project.objects.using(alias).order_by("-start_date", "name")


def _require_project(request, alias, project_id):
    project = get_object_or_404(_project_queryset(alias), id=project_id)
    policy = project_access_policy(request, alias)
    if not policy.can_webgis_read(project.id):
        raise PermissionDenied("Permission denied")
    plan = project_layer_plan(alias, project.id)
    if plan.get("ready") and not plan.get("gis_enabled"):
        raise Http404("GIS is not enabled by this project's business scope.")
    return project, policy, plan


def _project_layer_counts(alias: str, project_id, plan: dict) -> dict[str, int | None]:
    connection = connections[alias]
    schema_name = connection.ops.quote_name("gis")
    counts: dict[str, int | None] = {}
    with connection.cursor() as cursor:
        for row in plan.get("layers") or []:
            standard_name = str(row.get("standard_name") or "")
            physical_name = str(row.get("physical_name") or "")
            if not standard_name or not physical_name:
                continue

            cursor.execute("SELECT to_regclass(%s)", [f"gis.{physical_name}"])
            if cursor.fetchone()[0] is None:
                counts[standard_name] = None
                continue

            quoted_table = connection.ops.quote_name(physical_name)
            cursor.execute(
                f"SELECT count(*) FROM {schema_name}.{quoted_table} WHERE project_id=%s",
                [project_id],
            )
            counts[standard_name] = int(cursor.fetchone()[0])
    return counts


def _package_filename(project) -> str:
    code = _SAFE_FILENAME_RE.sub("_", str(project.code or project.id)).strip("._")
    return f"geoflow-{code or project.id}.gpkg"


def _set_package_headers(
    response,
    *,
    project,
    layer_count: int,
    content_length: int,
    snapshot_revision: int | None,
    cache_status: str,
):
    response["Content-Length"] = str(int(content_length))
    response["X-GeoFlow-Project"] = str(project.id)
    response["X-GeoFlow-Layer-Count"] = str(int(layer_count))
    response["X-GeoFlow-Package-Version"] = "0.6"
    if snapshot_revision is not None:
        response["X-GeoFlow-Snapshot-Revision"] = str(int(snapshot_revision))
    response["X-GeoFlow-Snapshot-Cache"] = str(cache_status)
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_GET
def qgis_projects_api(request):
    alias = _require_qgis_context(request)
    policy = project_access_policy(request, alias)
    queryset = _project_queryset(alias)

    visible_ids = policy.visible_project_ids()
    if visible_ids is not None:
        queryset = queryset.filter(pk__in=visible_ids)

    enabled_ids = gis_enabled_project_ids(alias)
    if enabled_ids is not None:
        queryset = queryset.filter(pk__in=enabled_ids)

    results = []
    for project in queryset[:200]:
        plan = project_layer_plan(alias, project.id)
        if plan.get("ready") and not plan.get("gis_enabled"):
            continue
        member = policy.membership(project.id)
        results.append(
            {
                "id": str(project.id),
                "code": project.code or "",
                "name": project.name or "",
                "status": project.status or "",
                "member_role": member["member_role"] if member else None,
                "can_write": policy.can_webgis_write(project.id),
                "profile": plan.get("profile"),
                "capabilities": plan.get("capabilities") or [],
                "layer_count": len(plan.get("layers") or []),
                "manifest_url": reverse(
                    "gis:qgis_project_manifest_api",
                    kwargs={"project_id": project.id},
                ),
            }
        )

    return JsonResponse(
        {"results": results, "count": len(results), "scope": policy.mode},
        json_dumps_params={"ensure_ascii": False},
    )


@login_required
@require_GET
def qgis_project_manifest_api(request, project_id):
    alias = _require_qgis_context(request)
    project, policy, plan = _require_project(request, alias, project_id)
    layer_counts = _project_layer_counts(alias, project.id, plan)
    package_layers = project_geopackage_layer_manifest(alias, plan)
    package_url = reverse(
        "gis:qgis_project_package_api",
        kwargs={"project_id": project.id},
    )
    sync_url = reverse(
        "gis:qgis_project_sync_api",
        kwargs={"project_id": project.id},
    )
    changeset_url = reverse(
        "gis:project_changeset_api",
        kwargs={"project_id": project.id},
    )
    delta_url = reverse(
        "gis:project_delta_api",
        kwargs={"project_id": project.id},
    )
    changeset_supported = changeset_runtime_enabled(alias)
    manifest = build_qgis_manifest(
        project={
            "id": project.id,
            "code": project.code,
            "name": project.name,
            "status": project.status,
        },
        plan=plan,
        can_write=policy.can_webgis_write(project.id),
        package_url=package_url,
        package_layers=package_layers,
        layer_counts=layer_counts,
        sync_url=sync_url,
        sync_supported=sync_runtime_enabled(alias) and not changeset_supported,
        changeset_url=changeset_url,
        delta_url=delta_url,
        changeset_supported=changeset_supported,
        current_revision=(
            project_current_revision(alias, str(project.id))
            if changeset_supported
            else 0
        ),
    )
    return JsonResponse(manifest, json_dumps_params={"ensure_ascii": False})


@login_required
@require_GET
def qgis_project_package_api(request, project_id):
    alias = _require_qgis_context(request)
    project, _policy, plan = _require_project(request, alias, project_id)
    changeset_supported = changeset_runtime_enabled(alias)

    if changeset_supported:
        requested_revision = project_current_revision(alias, str(project.id))
        layer_manifest = project_geopackage_layer_manifest(alias, plan)
        try:
            artifact = get_or_build_server_snapshot(
                alias=alias,
                project_id=str(project.id),
                plan=plan,
                layer_manifest=layer_manifest,
                requested_revision=requested_revision,
            )
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=422)

        cache_status = "HIT" if artifact.cache_hit else "MISS"
        _dev_snapshot_diag(
            cache_status,
            project_id=project.id,
            revision=artifact.snapshot_revision,
            bytes=artifact.path.stat().st_size,
            layers=len(artifact.layer_meta),
        )
        response = FileResponse(
            artifact.path.open("rb"),
            content_type="application/geopackage+sqlite3",
            as_attachment=True,
            filename=_package_filename(project),
        )
        return _set_package_headers(
            response,
            project=project,
            layer_count=len(artifact.layer_meta),
            content_length=artifact.path.stat().st_size,
            snapshot_revision=artifact.snapshot_revision,
            cache_status=cache_status,
        )

    # Legacy/fallback runtime keeps the compatibility bytes response. Normal
    # Changeset operation above is file-backed and streamed, so large snapshots
    # no longer require a second whole-file Python memory copy.
    try:
        payload, layer_meta = build_syncable_project_geopackage(
            alias,
            project_id=str(project.id),
            plan=plan,
        )
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=422)

    response = HttpResponse(payload, content_type="application/geopackage+sqlite3")
    response["Content-Disposition"] = (
        f'attachment; filename="{_package_filename(project)}"'
    )
    return _set_package_headers(
        response,
        project=project,
        layer_count=len(layer_meta),
        content_length=len(payload),
        snapshot_revision=None,
        cache_status="BYPASS",
    )


@login_required
@require_POST
def qgis_project_sync_api(request, project_id):
    alias = _require_qgis_context(request)
    project, policy, plan = _require_project(request, alias, project_id)
    if not policy.can_webgis_write(project.id):
        _dev_sync_diag("PERMISSION_DENIED", project_id=project.id, alias=alias)
        raise PermissionDenied("Permission denied")
    if changeset_runtime_enabled(alias):
        _dev_sync_diag("LEGACY_DISABLED", project_id=project.id, alias=alias)
        return JsonResponse(
            {
                "ok": False,
                "error": "legacy_sync_disabled",
                "message": "Whole-GeoPackage sync is disabled because Changeset v1 is active.",
            },
            status=409,
        )
    if not sync_runtime_enabled(alias):
        _dev_sync_diag("RUNTIME_DISABLED", project_id=project.id, alias=alias)
        return JsonResponse(
            {
                "ok": False,
                "error": "sync_not_enabled",
                "message": "QGIS sync is development-gated.",
            },
            status=403,
        )

    upload = request.FILES.get("package")
    if upload is None:
        _dev_sync_diag("PACKAGE_MISSING", project_id=project.id, alias=alias)
        return JsonResponse({"ok": False, "error": "package_missing"}, status=400)

    upload_size = int(getattr(upload, "size", 0) or 0)
    _dev_sync_diag(
        "REQUEST",
        project_id=project.id,
        alias=alias,
        bytes=upload_size,
        layers=len(plan.get("layers") or []),
    )
    if upload_size > _MAX_SYNC_PACKAGE_BYTES:
        _dev_sync_diag("PACKAGE_TOO_LARGE", project_id=project.id, bytes=upload_size)
        return JsonResponse({"ok": False, "error": "package_too_large"}, status=413)

    payload = upload.read()
    try:
        _dev_sync_diag("DIFF_START", project_id=project.id, bytes=len(payload))
        result = sync_project_geopackage_v2(
            alias,
            project_id=str(project.id),
            plan=plan,
            package_bytes=payload,
        )
    except SyncConflict as exc:
        _dev_sync_diag(
            "CONFLICT",
            project_id=project.id,
            conflicts=len(exc.conflicts),
        )
        return JsonResponse(
            {
                "ok": False,
                "error": "sync_conflict",
                "message": "동일 UUID 충돌 또는 서버 삭제 상태 때문에 동기화를 중단했습니다.",
                "conflicts": exc.conflicts,
            },
            status=409,
            json_dumps_params={"ensure_ascii": False},
        )
    except SyncRejected as exc:
        _dev_sync_diag(
            "REJECTED",
            project_id=project.id,
            error_type=type(exc).__name__,
            details=len(exc.details),
        )
        return JsonResponse(
            {
                "ok": False,
                "error": "sync_rejected",
                "message": str(exc),
                "details": exc.details,
            },
            status=400,
            json_dumps_params={"ensure_ascii": False},
        )
    except (DatabaseError, sqlite3.Error) as exc:
        _dev_sync_diag(
            "PROCESSING_FAIL",
            project_id=project.id,
            error_type=type(exc).__name__,
        )
        if _dev_sync_diag_enabled():
            logger.exception(
                "DEV-QGIS-SYNC PROCESSING_FAIL project_id=%s error_type=%s",
                project.id,
                type(exc).__name__,
            )
        return JsonResponse(
            {
                "ok": False,
                "error": "sync_failed",
                "message": "GeoFlow sync processing failed.",
            },
            status=503,
        )
    except Exception as exc:
        _dev_sync_diag(
            "UNEXPECTED_FAIL",
            project_id=project.id,
            error_type=type(exc).__name__,
        )
        if _dev_sync_diag_enabled():
            logger.exception(
                "DEV-QGIS-SYNC UNEXPECTED_FAIL project_id=%s error_type=%s",
                project.id,
                type(exc).__name__,
            )
        raise

    _dev_sync_diag(
        "SUCCESS",
        project_id=project.id,
        created=int(result.get("created") or 0),
        updated=int(result.get("updated") or 0),
        deleted=int(result.get("deleted") or 0),
        total=int(result.get("total") or 0),
    )
    return JsonResponse({"ok": True, **result}, json_dumps_params={"ensure_ascii": False})
