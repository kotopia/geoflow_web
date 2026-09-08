from __future__ import annotations

import sqlite3
import tempfile
import uuid
from pathlib import Path
from typing import Any

from django.db import transaction

from .gpkg import _layer_specs
from .layer_plan import allowed_standard_names
from .qgis_sync import (
    SyncConflict,
    SyncOperation,
    SyncRejected,
    _apply_operation,
    _coerce_for_pg,
    _current_package_rows,
    _geometry_valid,
    _read_package_project_id,
    _source_row,
    _uuid_exists,
    sync_runtime_enabled,
)
from .qgis_sync_hash import content_hash


_AUDIT_FIELDS = {"created_at", "updated_at", "created_by", "updated_by"}
_IMMUTABLE_FIELDS = {"id", "project_id", *_AUDIT_FIELDS}


def _baseline_for_layer_v2(
    package: sqlite3.Connection,
    physical_name: str,
) -> dict[str, dict[str, Any]]:
    try:
        rows = package.execute(
            """
            SELECT object_id, local_fid, source_updated_at, content_hash
              FROM _geoflow_baseline
             WHERE layer_name=?
            """,
            (physical_name,),
        ).fetchall()
    except sqlite3.Error as exc:
        raise SyncRejected(
            "GeoFlow package baseline is missing or too old; reopen the project"
        ) from exc

    result: dict[str, dict[str, Any]] = {}
    for object_id, local_fid, updated_at, baseline_hash in rows:
        try:
            normalized_id = str(uuid.UUID(str(object_id)))
        except (ValueError, TypeError, AttributeError) as exc:
            raise SyncRejected(f"invalid baseline UUID in {physical_name}") from exc
        if not baseline_hash:
            raise SyncRejected(
                "GeoFlow package does not contain content hashes; reopen the project"
            )
        result[normalized_id] = {
            "local_fid": int(local_fid),
            "updated_at": str(updated_at) if updated_at else None,
            "content_hash": str(baseline_hash),
        }
    return result


def _collect_operations_last_write_wins(
    alias: str,
    *,
    package: sqlite3.Connection,
    project_id: str,
    plan: dict[str, Any],
) -> tuple[list[SyncOperation], list[dict[str, Any]]]:
    specs = _layer_specs(alias, plan)
    allowed = allowed_standard_names(plan)
    operations: list[SyncOperation] = []
    conflicts: list[dict[str, Any]] = []

    for spec in specs:
        if spec.standard_name.upper() not in allowed:
            raise SyncRejected(f"layer outside Layer Plan: {spec.standard_name}")

        baseline = _baseline_for_layer_v2(package, spec.physical_name)
        current = _current_package_rows(package, spec.physical_name, spec.fields)
        current_by_fid = {int(row["fid"]): object_id for object_id, row in current.items()}
        field_by_name = {field.name: field for field in spec.fields}
        editable_names = {
            field.name
            for field in spec.fields
            if field.editable and field.name not in _IMMUTABLE_FIELDS
        }

        # Existing GeoFlow UUID identity is immutable even if a user bypasses
        # the QGIS form widget and edits the raw GeoPackage table directly.
        for baseline_id, meta in baseline.items():
            current_id = current_by_fid.get(int(meta["local_fid"]))
            if current_id is not None and current_id != baseline_id:
                raise SyncRejected(
                    f"{spec.standard_name}: existing object UUID was changed locally ({baseline_id})"
                )

        for object_id in sorted(set(baseline) | set(current)):
            package_row = current.get(object_id)
            baseline_meta = baseline.get(object_id)

            if baseline_meta is not None:
                # Missing from the local package means the user deleted it.
                if package_row is None:
                    source = _source_row(
                        alias,
                        physical_name=spec.physical_name,
                        fields=spec.fields,
                        project_id=project_id,
                        object_id=object_id,
                        lock=True,
                    )
                    if source is not None:
                        operations.append(
                            SyncOperation(
                                "delete",
                                spec.physical_name,
                                spec.standard_name,
                                object_id,
                                {},
                                None,
                            )
                        )
                    continue

                attrs = package_row["attrs"]
                if attrs.get("project_id") != project_id:
                    raise SyncRejected(
                        f"{spec.standard_name} {object_id}: project_id mismatch"
                    )

                package_hash = content_hash(
                    attrs,
                    package_row["geom"],
                    editable_names,
                )
                if package_hash == baseline_meta["content_hash"]:
                    # No local edit: never overwrite a newer server value merely
                    # because somebody else changed the object after download.
                    continue

                package_geom = package_row["geom"]
                if package_geom is None or not _geometry_valid(
                    alias, package_geom, spec.geometry_kind
                ):
                    raise SyncRejected(
                        f"{spec.standard_name} {object_id}: valid geometry is required"
                    )

                source = _source_row(
                    alias,
                    physical_name=spec.physical_name,
                    fields=spec.fields,
                    project_id=project_id,
                    object_id=object_id,
                    lock=True,
                )
                if source is None:
                    conflicts.append(
                        {
                            "layer": spec.standard_name,
                            "id": object_id,
                            "reason": "server_object_missing",
                        }
                    )
                    continue

                # Whole-object last successful server write wins. Only fields
                # declared editable by the active profile are written back.
                update_attrs = {
                    name: _coerce_for_pg(attrs.get(name), field_by_name[name])
                    for name in editable_names
                    if name in attrs
                }
                operations.append(
                    SyncOperation(
                        "update",
                        spec.physical_name,
                        spec.standard_name,
                        object_id,
                        update_attrs,
                        package_geom,
                    )
                )
                continue

            # No baseline row means a new local object.
            assert package_row is not None
            attrs = package_row["attrs"]
            if attrs.get("project_id") != project_id:
                raise SyncRejected(
                    f"{spec.standard_name} {object_id}: project_id mismatch"
                )
            if _uuid_exists(alias, spec.physical_name, object_id, lock=True):
                conflicts.append(
                    {
                        "layer": spec.standard_name,
                        "id": object_id,
                        "reason": "uuid_already_exists",
                    }
                )
                continue
            package_geom = package_row["geom"]
            if package_geom is None or not _geometry_valid(
                alias, package_geom, spec.geometry_kind
            ):
                raise SyncRejected(
                    f"{spec.standard_name} {object_id}: valid geometry is required"
                )
            create_attrs = {
                name: _coerce_for_pg(attrs.get(name), field_by_name[name])
                for name in editable_names
                if name in attrs
            }
            operations.append(
                SyncOperation(
                    "create",
                    spec.physical_name,
                    spec.standard_name,
                    object_id,
                    create_attrs,
                    package_geom,
                )
            )

    return operations, conflicts


def sync_project_geopackage_v2(
    alias: str,
    *,
    project_id: str,
    plan: dict[str, Any],
    package_bytes: bytes,
) -> dict[str, Any]:
    if not sync_runtime_enabled(alias):
        raise SyncRejected(
            "QGIS sync is enabled only in the strict development runtime"
        )
    if not package_bytes.startswith(b"SQLite format 3\x00"):
        raise SyncRejected("uploaded file is not a SQLite/GeoPackage file")

    temp = tempfile.NamedTemporaryFile(
        prefix="geoflow-sync-v2-",
        suffix=".gpkg",
        delete=False,
    )
    path = Path(temp.name)
    operations: list[SyncOperation] = []
    try:
        temp.write(package_bytes)
        temp.close()
        package = sqlite3.connect(str(path))
        try:
            package_project_id = _read_package_project_id(package)
            if package_project_id != project_id:
                raise SyncRejected(
                    "GeoPackage project does not match the requested project"
                )

            with transaction.atomic(using=alias):
                operations, conflicts = _collect_operations_last_write_wins(
                    alias,
                    package=package,
                    project_id=project_id,
                    plan=plan,
                )
                if conflicts:
                    raise SyncConflict(conflicts)
                for operation in operations:
                    _apply_operation(alias, project_id, operation)
        finally:
            package.close()
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    counts = {"create": 0, "update": 0, "delete": 0}
    for operation in operations:
        counts[operation.action] += 1
    return {
        "created": counts["create"],
        "updated": counts["update"],
        "deleted": counts["delete"],
        "total": len(operations),
        "strategy": "last_successful_server_write_wins",
    }
