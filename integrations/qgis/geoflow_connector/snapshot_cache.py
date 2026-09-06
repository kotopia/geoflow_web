from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path


MIN_REUSABLE_PACKAGE_VERSION = (0, 6)


@dataclass(frozen=True)
class SnapshotCacheCandidate:
    path: str
    size_bytes: int
    last_applied_revision: int
    pending_count: int
    outbox_count: int
    mtime: float

    @property
    def dirty(self) -> bool:
        return bool(self.pending_count or self.outbox_count)


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = []
    for token in str(value or "").split("."):
        try:
            parts.append(int(token))
        except (TypeError, ValueError):
            break
    return tuple(parts)


def manifest_cache_fingerprint(manifest: dict) -> str:
    project = manifest.get("project") or {}
    profile = manifest.get("profile") or {}
    layers = []
    for layer in manifest.get("layers") or []:
        fields = []
        for field in layer.get("fields") or []:
            fields.append(
                {
                    "name": str(field.get("name") or ""),
                    "data_type": str(field.get("data_type") or ""),
                    "editable": bool(field.get("editable", True)),
                    "visible": bool(field.get("visible", True)),
                    "sort_order": int(field.get("sort_order") or 0),
                }
            )
        layers.append(
            {
                "standard_name": str(layer.get("standard_name") or ""),
                "physical_name": str(layer.get("physical_name") or ""),
                "domain": str(layer.get("domain") or ""),
                "geometry_kind": str(layer.get("geometry_kind") or ""),
                "fields": fields,
            }
        )
    payload = {
        "manifest_version": str(manifest.get("manifest_version") or ""),
        "project_id": str(project.get("id") or ""),
        "profile_id": str(profile.get("id") or ""),
        "profile_code": str(profile.get("code") or ""),
        "layers": layers,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _metadata(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute("SELECT key, value FROM _geoflow_package").fetchall()
    return {str(key): str(value or "") for key, value in rows}


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?",
            (str(name),),
        ).fetchone()
    )


def _row_count_if_table(conn: sqlite3.Connection, table: str) -> int:
    if not _table_exists(conn, table):
        return 0
    return int(conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0])


def _expected_layer_columns(layer: dict) -> set[str]:
    names = {
        str(field.get("name") or "")
        for field in (layer.get("fields") or [])
        if field.get("name")
    }
    return {"fid", "geom", *names}


def inspect_snapshot(path: str, manifest: dict) -> SnapshotCacheCandidate | None:
    snapshot = Path(path)
    if not snapshot.is_file() or snapshot.suffix.lower() != ".gpkg":
        return None

    project = manifest.get("project") or {}
    profile = manifest.get("profile") or {}
    expected_project = str(project.get("id") or "")
    if not expected_project:
        return None
    try:
        expected_project = str(uuid.UUID(expected_project))
    except (TypeError, ValueError, AttributeError):
        return None

    conn = None
    try:
        conn = sqlite3.connect(f"file:{snapshot.as_posix()}?mode=rw", uri=True, timeout=5)
        conn.execute("PRAGMA busy_timeout=5000")
        if not _table_exists(conn, "_geoflow_package"):
            return None
        meta = _metadata(conn)
        try:
            package_project = str(uuid.UUID(str(meta.get("project_id") or "")))
        except (TypeError, ValueError, AttributeError):
            return None
        if package_project != expected_project:
            return None
        if _version_tuple(meta.get("package_version", "")) < MIN_REUSABLE_PACKAGE_VERSION:
            return None

        expected_profile_id = str(profile.get("id") or "")
        expected_profile_code = str(profile.get("code") or "")
        if expected_profile_id and str(meta.get("profile_id") or "") != expected_profile_id:
            return None
        if expected_profile_code and str(meta.get("profile_code") or "") != expected_profile_code:
            return None

        expected_layers = {
            str(layer.get("physical_name") or ""): layer
            for layer in (manifest.get("layers") or [])
            if layer.get("physical_name")
        }
        actual_layers = {
            str(row[0])
            for row in conn.execute(
                "SELECT table_name FROM gpkg_contents WHERE data_type='features'"
            ).fetchall()
        }
        if actual_layers != set(expected_layers):
            return None

        for physical_name, layer in expected_layers.items():
            columns = {
                str(row[1])
                for row in conn.execute(
                    f'PRAGMA table_info("{physical_name}")'
                ).fetchall()
            }
            if columns != _expected_layer_columns(layer):
                return None
            if not _table_exists(conn, f"rtree_{physical_name}_geom"):
                return None

        fingerprint = manifest_cache_fingerprint(manifest)
        saved_fingerprint = str(meta.get("cache_manifest_fingerprint") or "")
        if saved_fingerprint and saved_fingerprint != fingerprint:
            return None

        try:
            last_revision = int(meta.get("last_applied_revision") or 0)
        except (TypeError, ValueError):
            return None
        if last_revision < 0:
            return None

        pending = _row_count_if_table(conn, "_geoflow_pending_change")
        outbox = _row_count_if_table(conn, "_geoflow_outbox")
        return SnapshotCacheCandidate(
            path=str(snapshot),
            size_bytes=int(snapshot.stat().st_size),
            last_applied_revision=last_revision,
            pending_count=pending,
            outbox_count=outbox,
            mtime=float(snapshot.stat().st_mtime),
        )
    except (OSError, sqlite3.Error):
        return None
    finally:
        if conn is not None:
            conn.close()


def stamp_snapshot(path: str, manifest: dict) -> None:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    conn = sqlite3.connect(path, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        conn.executemany(
            "INSERT OR REPLACE INTO _geoflow_package(key,value) VALUES (?,?)",
            [
                ("cache_manifest_fingerprint", manifest_cache_fingerprint(manifest)),
                ("cache_last_opened_at", now),
            ],
        )
        conn.commit()
    finally:
        conn.close()
    try:
        os.utime(path, None)
    except OSError:
        pass


def select_reusable_snapshot(project_dir: str, manifest: dict) -> SnapshotCacheCandidate | None:
    root = Path(project_dir)
    if not root.is_dir():
        return None

    candidates = []
    for path in root.glob("*.gpkg"):
        candidate = inspect_snapshot(str(path), manifest)
        if candidate is not None:
            candidates.append(candidate)
    if not candidates:
        return None

    dirty = [candidate for candidate in candidates if candidate.dirty]
    if len(dirty) > 1:
        raise RuntimeError(
            "동일 GeoFlow 프로젝트에 미전송 변경이 남은 로컬 Snapshot이 둘 이상 있습니다. "
            "자동 선택으로 변경을 잃을 수 있어 프로젝트 열기를 중단했습니다."
        )
    selected = dirty[0] if dirty else max(candidates, key=lambda row: row.mtime)
    stamp_snapshot(selected.path, manifest)
    return SnapshotCacheCandidate(
        path=selected.path,
        size_bytes=selected.size_bytes,
        last_applied_revision=selected.last_applied_revision,
        pending_count=selected.pending_count,
        outbox_count=selected.outbox_count,
        mtime=float(Path(selected.path).stat().st_mtime),
    )
