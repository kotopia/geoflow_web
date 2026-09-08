from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .gpkg_syncable import build_syncable_project_geopackage_file


_CACHE_ENV = "GEOFLOW_QGIS_SNAPSHOT_CACHE_DIR"
_MAX_REVISIONS_PER_FINGERPRINT = 3
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


@dataclass(frozen=True)
class ServerSnapshotArtifact:
    path: Path
    layer_meta: list[dict[str, Any]]
    snapshot_revision: int
    cache_hit: bool
    fingerprint: str


def _cache_root() -> Path:
    configured = str(os.getenv(_CACHE_ENV, "") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(tempfile.gettempdir()) / "geoflow-qgis-snapshot-cache"


def snapshot_fingerprint(
    *,
    alias: str,
    project_id: str,
    plan: dict[str, Any],
    layer_manifest: list[dict[str, Any]],
) -> str:
    profile = plan.get("profile") or {}
    payload = {
        "alias_hash": hashlib.sha256(str(alias).encode("utf-8")).hexdigest()[:16],
        "project_id": str(project_id),
        "profile": {
            "id": str(profile.get("id") or ""),
            "code": str(profile.get("code") or ""),
        },
        "layers": layer_manifest,
        "package_version": "0.6",
        "spatial_index": "gpkg_rtree_index",
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _namespace_dir(
    *,
    alias: str,
    project_id: str,
    fingerprint: str,
    cache_root: Path | None = None,
) -> Path:
    root = cache_root or _cache_root()
    alias_hash = hashlib.sha256(str(alias).encode("utf-8")).hexdigest()[:16]
    project_hash = hashlib.sha256(str(project_id).encode("utf-8")).hexdigest()[:16]
    return root / alias_hash / project_hash / fingerprint[:24]


def _revision_paths(namespace: Path, revision: int) -> tuple[Path, Path]:
    stem = f"revision-{int(revision):020d}"
    return namespace / f"{stem}.gpkg", namespace / f"{stem}.json"


def _lock_for(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[key] = lock
        return lock


def _read_metadata(meta_path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _load_cached(
    *,
    gpkg_path: Path,
    meta_path: Path,
    expected_revision: int,
    fingerprint: str,
) -> ServerSnapshotArtifact | None:
    if not gpkg_path.is_file() or not meta_path.is_file():
        return None
    meta = _read_metadata(meta_path)
    if not meta:
        return None
    try:
        revision = int(meta.get("snapshot_revision"))
        size_bytes = int(meta.get("size_bytes"))
    except (TypeError, ValueError):
        return None
    if revision != int(expected_revision):
        return None
    if str(meta.get("fingerprint") or "") != fingerprint:
        return None
    try:
        if gpkg_path.stat().st_size != size_bytes or size_bytes <= 0:
            return None
        with gpkg_path.open("rb") as handle:
            if handle.read(16) != b"SQLite format 3\x00":
                return None
    except OSError:
        return None
    layer_meta = meta.get("layer_meta")
    if not isinstance(layer_meta, list):
        return None
    return ServerSnapshotArtifact(
        path=gpkg_path,
        layer_meta=layer_meta,
        snapshot_revision=revision,
        cache_hit=True,
        fingerprint=fingerprint,
    )


def _write_metadata(
    meta_path: Path,
    *,
    fingerprint: str,
    snapshot_revision: int,
    gpkg_path: Path,
    layer_meta: list[dict[str, Any]],
) -> None:
    payload = {
        "fingerprint": fingerprint,
        "snapshot_revision": int(snapshot_revision),
        "size_bytes": int(gpkg_path.stat().st_size),
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "layer_meta": layer_meta,
    }
    temp_meta = meta_path.with_suffix(meta_path.suffix + ".tmp")
    temp_meta.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(temp_meta, meta_path)


def _prune(namespace: Path, *, keep: int = _MAX_REVISIONS_PER_FINGERPRINT) -> None:
    if keep < 1:
        return
    packages = sorted(
        namespace.glob("revision-*.gpkg"),
        key=lambda path: path.name,
        reverse=True,
    )
    for gpkg_path in packages[keep:]:
        meta_path = gpkg_path.with_suffix(".json")
        try:
            gpkg_path.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            meta_path.unlink(missing_ok=True)
        except OSError:
            pass


def get_or_build_server_snapshot(
    *,
    alias: str,
    project_id: str,
    plan: dict[str, Any],
    layer_manifest: list[dict[str, Any]],
    requested_revision: int,
    cache_root: Path | None = None,
    builder: Callable[..., tuple[Path, list[dict[str, Any]], int]] = build_syncable_project_geopackage_file,
) -> ServerSnapshotArtifact:
    """Return one revision-scoped cached Snapshot or build it once.

    The cache is intentionally exact-revision keyed. A fresh QGIS device can
    therefore share a server Snapshot with other clients opening the same
    project revision, while subsequent revisions remain immutable artifacts.
    The returned file is safe to stream directly with Django FileResponse.

    Process-local locking is sufficient for the current strict-development
    single-process ASGI runtime. Production multi-worker rollout still requires
    a separately reviewed shared cache/object-store lock strategy.
    """

    fingerprint = snapshot_fingerprint(
        alias=alias,
        project_id=project_id,
        plan=plan,
        layer_manifest=layer_manifest,
    )
    namespace = _namespace_dir(
        alias=alias,
        project_id=project_id,
        fingerprint=fingerprint,
        cache_root=cache_root,
    )
    namespace.mkdir(parents=True, exist_ok=True)
    gpkg_path, meta_path = _revision_paths(namespace, int(requested_revision))

    cached = _load_cached(
        gpkg_path=gpkg_path,
        meta_path=meta_path,
        expected_revision=int(requested_revision),
        fingerprint=fingerprint,
    )
    if cached is not None:
        return cached

    lock_key = str(gpkg_path)
    with _lock_for(lock_key):
        cached = _load_cached(
            gpkg_path=gpkg_path,
            meta_path=meta_path,
            expected_revision=int(requested_revision),
            fingerprint=fingerprint,
        )
        if cached is not None:
            return cached

        built_path: Path | None = None
        try:
            built_path, layer_meta, snapshot_revision = builder(
                alias,
                project_id=str(project_id),
                plan=plan,
            )
            actual_gpkg, actual_meta = _revision_paths(
                namespace,
                int(snapshot_revision),
            )
            # A revision may advance between the caller's current-revision read
            # and the REPEATABLE READ snapshot transaction. Store the immutable
            # artifact under the revision it actually represents.
            existing = _load_cached(
                gpkg_path=actual_gpkg,
                meta_path=actual_meta,
                expected_revision=int(snapshot_revision),
                fingerprint=fingerprint,
            )
            if existing is not None:
                return existing

            os.replace(built_path, actual_gpkg)
            built_path = None
            _write_metadata(
                actual_meta,
                fingerprint=fingerprint,
                snapshot_revision=int(snapshot_revision),
                gpkg_path=actual_gpkg,
                layer_meta=layer_meta,
            )
            _prune(namespace)
            return ServerSnapshotArtifact(
                path=actual_gpkg,
                layer_meta=layer_meta,
                snapshot_revision=int(snapshot_revision),
                cache_hit=False,
                fingerprint=fingerprint,
            )
        finally:
            if built_path is not None:
                try:
                    built_path.unlink(missing_ok=True)
                except OSError:
                    pass
