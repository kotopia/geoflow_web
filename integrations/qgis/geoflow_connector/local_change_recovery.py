from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .changeset_queue import queue_change


_SYSTEM_FIELDS = {
    "id",
    "project_id",
    "created_at",
    "updated_at",
    "created_by",
    "updated_by",
}


def _quote_ident(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__bytes__": bytes(value).hex()}
    if isinstance(value, dict):
        return {
            str(key): _json_safe(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def _extract_gpkg_wkb(blob: bytes | memoryview | None) -> bytes | None:
    if blob is None:
        return None
    raw = bytes(blob)
    if len(raw) < 8 or raw[:2] != b"GP":
        raise RuntimeError("GeoFlow 로컬 geometry가 유효한 GeoPackage 형식이 아닙니다.")
    flags = raw[3]
    envelope_code = (flags >> 1) & 0x07
    envelope_sizes = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}
    if envelope_code not in envelope_sizes:
        raise RuntimeError("지원하지 않는 GeoPackage geometry envelope입니다.")
    offset = 8 + envelope_sizes[envelope_code]
    return raw[offset:] if len(raw) > offset else None


def _content_hash(attributes: dict, geometry_wkb: bytes | None, editable_names: list[str]) -> str:
    payload = {
        "attributes": {
            name: _json_safe(attributes.get(name))
            for name in sorted(set(editable_names))
        },
        "geometry_wkb": geometry_wkb.hex() if geometry_wkb is not None else None,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def recover_untracked_snapshot_changes(package_path: str, manifest: dict) -> dict[str, int]:
    """Queue edits saved while the server sync gate was disabled."""

    project = manifest.get("project") or {}
    project_id = str(uuid.UUID(str(project.get("id") or "")))
    operations: list[dict[str, Any]] = []

    uri = Path(package_path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    try:
        baseline_columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info('_geoflow_baseline')").fetchall()
        }
        if not {"layer_name", "object_id", "content_hash"}.issubset(baseline_columns):
            raise RuntimeError(
                "GeoFlow 로컬 기준선이 없어 미전송 변경을 안전하게 복구할 수 없습니다."
            )

        for layer_def in manifest.get("layers") or []:
            physical_name = str(layer_def.get("physical_name") or "")
            standard_name = str(layer_def.get("standard_name") or physical_name.upper())
            if not physical_name or not standard_name:
                continue

            field_names = [
                str(row.get("name"))
                for row in (layer_def.get("fields") or [])
                if row.get("name")
            ]
            if "id" not in field_names or "project_id" not in field_names:
                raise RuntimeError(f"{standard_name}: GeoFlow 식별 필드가 없습니다.")
            editable_names = [
                str(row.get("name"))
                for row in (layer_def.get("fields") or [])
                if row.get("name")
                and bool(row.get("editable", True))
                and str(row.get("name")) not in _SYSTEM_FIELDS
            ]

            columns = ", ".join(_quote_ident(name) for name in field_names)
            table = _quote_ident(physical_name)
            current_rows = conn.execute(
                f'SELECT {columns}, "geom" FROM {table}'
            ).fetchall()
            current: dict[str, tuple[dict[str, Any], bytes | None]] = {}
            for row in current_rows:
                attrs = dict(zip(field_names, row[:-1]))
                object_id = str(uuid.UUID(str(attrs.get("id") or "")))
                row_project_id = str(uuid.UUID(str(attrs.get("project_id") or "")))
                if row_project_id != project_id:
                    raise RuntimeError(
                        f"{standard_name}: 다른 프로젝트 객체가 로컬 Snapshot에 포함되어 있습니다."
                    )
                if object_id in current:
                    raise RuntimeError(f"{standard_name}: 중복 GeoFlow UUID가 있습니다.")
                current[object_id] = (attrs, _extract_gpkg_wkb(row[-1]))

            baseline = {
                str(uuid.UUID(str(object_id))): str(content_hash or "")
                for object_id, content_hash in conn.execute(
                    "SELECT object_id, content_hash FROM _geoflow_baseline WHERE layer_name=?",
                    (physical_name,),
                ).fetchall()
            }

            for object_id, (attrs, geometry_wkb) in current.items():
                safe_attrs = {
                    name: _json_safe(attrs.get(name))
                    for name in editable_names
                    if attrs.get(name) is not None
                }
                if object_id not in baseline:
                    if geometry_wkb is None:
                        raise RuntimeError(f"{standard_name}: 신규 객체 geometry가 없습니다.")
                    operations.append(
                        {
                            "layer": standard_name,
                            "object_id": object_id,
                            "action": "create",
                            "attributes": safe_attrs,
                            "geometry_wkb": geometry_wkb.hex(),
                        }
                    )
                    continue

                original_hash = baseline[object_id]
                if original_hash and original_hash != _content_hash(
                    attrs, geometry_wkb, editable_names
                ):
                    operations.append(
                        {
                            "layer": standard_name,
                            "object_id": object_id,
                            "action": "update",
                            "attributes": safe_attrs,
                            "geometry_wkb": geometry_wkb.hex() if geometry_wkb else None,
                        }
                    )

            for object_id in set(baseline) - set(current):
                operations.append(
                    {
                        "layer": standard_name,
                        "object_id": object_id,
                        "action": "delete",
                        "attributes": {},
                        "geometry_wkb": None,
                    }
                )
    finally:
        conn.close()

    counts = {"created": 0, "updated": 0, "deleted": 0, "total": 0}
    for operation in operations:
        queue_change(package_path, **operation)
        key = {"create": "created", "update": "updated", "delete": "deleted"}[
            operation["action"]
        ]
        counts[key] += 1
        counts["total"] += 1
    return counts
