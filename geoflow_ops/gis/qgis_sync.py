from __future__ import annotations

import datetime as dt
import json
import os
import re
import sqlite3
import tempfile
import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import connections, transaction
from psycopg2.extras import Json

from .gpkg import PackageField, _layer_specs
from .layer_plan import allowed_standard_names


_SAFE_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")
_AUDIT_FIELDS = {"created_at", "updated_at", "created_by", "updated_by"}
_IMMUTABLE_FIELDS = {"id", "project_id", *_AUDIT_FIELDS}


class SyncRejected(RuntimeError):
    def __init__(self, message: str, *, details: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.details = details or []


class SyncConflict(RuntimeError):
    def __init__(self, conflicts: list[dict[str, Any]]):
        super().__init__("GeoFlow sync conflict")
        self.conflicts = conflicts


@dataclass(frozen=True)
class SyncOperation:
    action: str
    table: str
    standard_name: str
    object_id: str
    attributes: dict[str, Any]
    geometry_wkb: bytes | None


def sync_runtime_enabled(alias: str) -> bool:
    if not settings.DEBUG or os.getenv("GEOFLOW_DEV_RUNTIME_STRICT") != "1":
        return False
    try:
        db_name = str(connections[alias].settings_dict.get("NAME") or "")
    except Exception:
        return False
    lowered = db_name.lower()
    return "dev" in lowered or "test" in lowered


def _quote_ident(value: str) -> str:
    if not _SAFE_IDENT.fullmatch(value):
        raise SyncRejected(f"unsafe GIS identifier: {value}")
    return '"' + value + '"'


def _normalize(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, memoryview):
        return bytes(value)
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value


def _coerce_for_pg(value: Any, field: PackageField) -> Any:
    kind = str(field.data_type or "").lower()
    if value is None:
        # GeoFlow GIS feature tables define ext_data as
        # JSONB NOT NULL DEFAULT '{}'. QGIS/OGR represents an untouched JSON
        # field on a newly created feature as NULL, so an explicit NULL insert
        # would bypass the database default and violate the table contract.
        # Keep the normalization narrowly scoped to ext_data; other nullable
        # JSON fields must retain their own NULL semantics.
        if field.name == "ext_data" and kind in {"json", "jsonb"}:
            return Json({})
        return None
    if kind == "boolean":
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "t", "yes", "y"}
        return bool(value)
    if kind in {"json", "jsonb"}:
        if isinstance(value, str):
            try:
                return Json(json.loads(value))
            except json.JSONDecodeError as exc:
                raise SyncRejected(f"{field.name}: invalid JSON") from exc
        return Json(value)
    return value


def extract_gpkg_wkb(blob: bytes | memoryview | None) -> bytes | None:
    if blob is None:
        return None
    raw = bytes(blob)
    if len(raw) < 8 or raw[:2] != b"GP":
        raise SyncRejected("invalid GeoPackage geometry blob")
    flags = raw[3]
    envelope_code = (flags >> 1) & 0x07
    envelope_sizes = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}
    if envelope_code not in envelope_sizes:
        raise SyncRejected("unsupported GeoPackage geometry envelope")
    offset = 8 + envelope_sizes[envelope_code]
    if len(raw) <= offset:
        return None
    return raw[offset:]


def _read_package_project_id(conn: sqlite3.Connection) -> str:
    try:
        row = conn.execute(
            "SELECT value FROM _geoflow_package WHERE key='project_id'"
        ).fetchone()
    except sqlite3.Error as exc:
        raise SyncRejected("GeoFlow package metadata is missing") from exc
    if not row or not row[0]:
        raise SyncRejected("GeoFlow package project_id is missing")
    try:
        return str(uuid.UUID(str(row[0])))
    except (ValueError, TypeError, AttributeError) as exc:
        raise SyncRejected("GeoFlow package project_id is invalid") from exc


def _baseline_for_layer(conn: sqlite3.Connection, physical_name: str) -> dict[str, dict[str, Any]]:
    try:
        rows = conn.execute(
            "SELECT object_id, local_fid, source_updated_at FROM _geoflow_baseline WHERE layer_name=?",
            (physical_name,),
        ).fetchall()
    except sqlite3.Error as exc:
        raise SyncRejected("GeoFlow package baseline is missing or too old; reopen the project") from exc
    result: dict[str, dict[str, Any]] = {}
    for object_id, local_fid, updated_at in rows:
        try:
            normalized_id = str(uuid.UUID(str(object_id)))
        except (ValueError, TypeError, AttributeError) as exc:
            raise SyncRejected(f"invalid baseline UUID in {physical_name}") from exc
        result[normalized_id] = {
            "local_fid": int(local_fid),
            "updated_at": str(updated_at) if updated_at else None,
        }
    return result


def _current_package_rows(
    conn: sqlite3.Connection,
    physical_name: str,
    fields: tuple[PackageField, ...],
) -> dict[str, dict[str, Any]]:
    table = _quote_ident(physical_name)
    names = [field.name for field in fields]
    select_list = ", ".join(_quote_ident(name) for name in names)
    try:
        cursor = conn.execute(f"SELECT fid, {select_list}, \"geom\" FROM {table}")
        rows = cursor.fetchall()
    except sqlite3.Error as exc:
        raise SyncRejected(f"GeoPackage layer is unreadable: {physical_name}") from exc

    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        local_fid = int(row[0])
        attrs = dict(zip(names, row[1:-1]))
        raw_id = attrs.get("id")
        raw_project_id = attrs.get("project_id")
        if not raw_id:
            raise SyncRejected(f"{physical_name}: object without GeoFlow UUID")
        try:
            object_id = str(uuid.UUID(str(raw_id)))
        except (ValueError, TypeError, AttributeError) as exc:
            raise SyncRejected(f"{physical_name}: invalid GeoFlow UUID {raw_id}") from exc
        if raw_project_id:
            try:
                attrs["project_id"] = str(uuid.UUID(str(raw_project_id)))
            except (ValueError, TypeError, AttributeError) as exc:
                raise SyncRejected(f"{physical_name}: invalid project_id") from exc
        attrs["id"] = object_id
        if object_id in result:
            raise SyncRejected(f"{physical_name}: duplicate GeoFlow UUID {object_id}")
        result[object_id] = {
            "fid": local_fid,
            "attrs": attrs,
            "geom": extract_gpkg_wkb(row[-1]),
        }
    return result


def _source_row(
    alias: str,
    *,
    physical_name: str,
    fields: tuple[PackageField, ...],
    project_id: str,
    object_id: str,
    lock: bool,
) -> dict[str, Any] | None:
    table = _quote_ident(physical_name)
    field_names = [field.name for field in fields]
    select_list = ", ".join(_quote_ident(name) for name in field_names)
    suffix = " FOR UPDATE" if lock else ""
    with connections[alias].cursor() as cursor:
        cursor.execute(
            f"SELECT {select_list}, ST_AsBinary(geom), updated_at "
            f"FROM \"gis\".{table} WHERE project_id=%s AND id=%s{suffix}",
            [project_id, object_id],
        )
        row = cursor.fetchone()
    if not row:
        return None
    attrs = dict(zip(field_names, row[: len(field_names)]))
    return {
        "attrs": {key: _normalize(value) for key, value in attrs.items()},
        "geom": bytes(row[len(field_names)]) if row[len(field_names)] is not None else None,
        "updated_at": _normalize(row[len(field_names) + 1]),
    }


def _uuid_exists(alias: str, physical_name: str, object_id: str, *, lock: bool) -> bool:
    table = _quote_ident(physical_name)
    suffix = " FOR UPDATE" if lock else ""
    with connections[alias].cursor() as cursor:
        cursor.execute(
            f"SELECT 1 FROM \"gis\".{table} WHERE id=%s{suffix}",
            [object_id],
        )
        return cursor.fetchone() is not None


def _geometry_valid(alias: str, wkb: bytes, expected_kind: str) -> bool:
    expected = {
        "POINT": "ST_Point",
        "LINE": "ST_LineString",
        "POLYGON": "ST_Polygon",
    }.get(str(expected_kind or "").upper())
    with connections[alias].cursor() as cursor:
        cursor.execute(
            "SELECT ST_IsValid(g), ST_GeometryType(g) FROM (SELECT ST_GeomFromWKB(%s,4326) g) s",
            [wkb],
        )
        valid, geometry_type = cursor.fetchone()
    return bool(valid) and (expected is None or geometry_type == expected)


def _table_has_column(alias: str, physical_name: str, column_name: str) -> bool:
    with connections[alias].cursor() as cursor:
        cursor.execute(
            """
            SELECT EXISTS(
                SELECT 1 FROM information_schema.columns
                 WHERE table_schema='gis' AND table_name=%s AND column_name=%s
            )
            """,
            [physical_name, column_name],
        )
        return bool(cursor.fetchone()[0])


def _collect_operations(
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
        baseline = _baseline_for_layer(package, spec.physical_name)
        current = _current_package_rows(package, spec.physical_name, spec.fields)
        current_by_fid = {int(row["fid"]): object_id for object_id, row in current.items()}
        field_by_name = {field.name: field for field in spec.fields}
        editable_names = {
            field.name
            for field in spec.fields
            if field.editable and field.name not in _IMMUTABLE_FIELDS
        }

        for baseline_id, meta in baseline.items():
            current_id = current_by_fid.get(int(meta["local_fid"]))
            if current_id is not None and current_id != baseline_id:
                raise SyncRejected(
                    f"{spec.standard_name}: existing object UUID was changed locally ({baseline_id})"
                )

        for object_id in sorted(set(baseline) | set(current)):
            in_baseline = object_id in baseline
            package_row = current.get(object_id)

            if in_baseline:
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
                        {"layer": spec.standard_name, "id": object_id, "reason": "server_object_missing"}
                    )
                    continue
                if str(source.get("updated_at") or "") != str(baseline[object_id].get("updated_at") or ""):
                    conflicts.append(
                        {"layer": spec.standard_name, "id": object_id, "reason": "server_object_changed"}
                    )
                    continue

                if package_row is None:
                    operations.append(
                        SyncOperation("delete", spec.physical_name, spec.standard_name, object_id, {}, None)
                    )
                    continue

                package_attrs = package_row["attrs"]
                if package_attrs.get("project_id") != project_id:
                    raise SyncRejected(f"{spec.standard_name} {object_id}: project_id mismatch")

                changed_attrs: dict[str, Any] = {}
                for name, package_value in package_attrs.items():
                    if name not in field_by_name or name in _AUDIT_FIELDS:
                        continue
                    package_norm = _normalize(package_value)
                    source_norm = source["attrs"].get(name)
                    if package_norm == source_norm:
                        continue
                    if name in {"id", "project_id"} or name not in editable_names:
                        raise SyncRejected(
                            f"{spec.standard_name} {object_id}: protected field changed: {name}"
                        )
                    changed_attrs[name] = _coerce_for_pg(package_value, field_by_name[name])

                package_geom = package_row["geom"]
                geometry_changed = package_geom != source["geom"]
                if geometry_changed:
                    if package_geom is None:
                        raise SyncRejected(f"{spec.standard_name} {object_id}: geometry cannot be NULL")
                    if not _geometry_valid(alias, package_geom, spec.geometry_kind):
                        raise SyncRejected(f"{spec.standard_name} {object_id}: invalid geometry")

                if changed_attrs or geometry_changed:
                    operations.append(
                        SyncOperation(
                            "update",
                            spec.physical_name,
                            spec.standard_name,
                            object_id,
                            changed_attrs,
                            package_geom if geometry_changed else None,
                        )
                    )
                continue

            assert package_row is not None
            package_attrs = package_row["attrs"]
            if package_attrs.get("project_id") != project_id:
                raise SyncRejected(f"{spec.standard_name} {object_id}: project_id mismatch")
            if _uuid_exists(alias, spec.physical_name, object_id, lock=True):
                conflicts.append(
                    {"layer": spec.standard_name, "id": object_id, "reason": "uuid_already_exists"}
                )
                continue
            package_geom = package_row["geom"]
            if package_geom is None or not _geometry_valid(alias, package_geom, spec.geometry_kind):
                raise SyncRejected(f"{spec.standard_name} {object_id}: valid geometry is required")

            attrs: dict[str, Any] = {}
            for name in editable_names:
                if name in package_attrs:
                    attrs[name] = _coerce_for_pg(package_attrs[name], field_by_name[name])
            operations.append(
                SyncOperation("create", spec.physical_name, spec.standard_name, object_id, attrs, package_geom)
            )

    return operations, conflicts


def _apply_operation(alias: str, project_id: str, op: SyncOperation) -> None:
    table = _quote_ident(op.table)
    has_updated_at = _table_has_column(alias, op.table, "updated_at")

    if op.action == "delete":
        with connections[alias].cursor() as cursor:
            cursor.execute(
                f"DELETE FROM \"gis\".{table} WHERE project_id=%s AND id=%s",
                [project_id, op.object_id],
            )
            if cursor.rowcount != 1:
                raise SyncConflict(
                    [{"layer": op.standard_name, "id": op.object_id, "reason": "delete_target_changed"}]
                )
        return

    if op.action == "create":
        columns = ["id", "project_id", *op.attributes.keys(), "geom"]
        values_sql = ["%s::uuid", "%s::uuid"]
        params: list[Any] = [op.object_id, project_id]
        for value in op.attributes.values():
            values_sql.append("%s")
            params.append(value)
        values_sql.append("ST_GeomFromWKB(%s,4326)")
        params.append(op.geometry_wkb)
        quoted_columns = ", ".join(_quote_ident(name) for name in columns)
        with connections[alias].cursor() as cursor:
            cursor.execute(
                f"INSERT INTO \"gis\".{table} ({quoted_columns}) VALUES ({', '.join(values_sql)})",
                params,
            )
        return

    if op.action == "update":
        assignments: list[str] = []
        params = []
        for name, value in op.attributes.items():
            assignments.append(f"{_quote_ident(name)}=%s")
            params.append(value)
        if op.geometry_wkb is not None:
            assignments.append('"geom"=ST_GeomFromWKB(%s,4326)')
            params.append(op.geometry_wkb)
        if has_updated_at:
            assignments.append('"updated_at"=now()')
        if not assignments:
            return
        params.extend([project_id, op.object_id])
        with connections[alias].cursor() as cursor:
            cursor.execute(
                f"UPDATE \"gis\".{table} SET {', '.join(assignments)} WHERE project_id=%s AND id=%s",
                params,
            )
            if cursor.rowcount != 1:
                raise SyncConflict(
                    [{"layer": op.standard_name, "id": op.object_id, "reason": "update_target_changed"}]
                )
        return

    raise SyncRejected(f"unsupported sync action: {op.action}")


def sync_project_geopackage(
    alias: str,
    *,
    project_id: str,
    plan: dict[str, Any],
    package_bytes: bytes,
) -> dict[str, Any]:
    if not sync_runtime_enabled(alias):
        raise SyncRejected("QGIS sync is enabled only in the strict development runtime")
    if not package_bytes.startswith(b"SQLite format 3\x00"):
        raise SyncRejected("uploaded file is not a SQLite/GeoPackage file")

    temp = tempfile.NamedTemporaryFile(prefix="geoflow-sync-", suffix=".gpkg", delete=False)
    path = Path(temp.name)
    operations: list[SyncOperation] = []
    try:
        temp.write(package_bytes)
        temp.close()
        package = sqlite3.connect(str(path))
        try:
            package_project_id = _read_package_project_id(package)
            if package_project_id != project_id:
                raise SyncRejected("GeoPackage project does not match the requested project")

            with transaction.atomic(using=alias):
                operations, conflicts = _collect_operations(
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
        "ok": True,
        "project_id": project_id,
        "created": counts["create"],
        "updated": counts["update"],
        "deleted": counts["delete"],
        "total_changes": len(operations),
    }
