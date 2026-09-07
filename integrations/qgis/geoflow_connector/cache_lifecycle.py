from __future__ import annotations

import datetime as dt
import os
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


COMPLETED_STATUSES = {"complete", "completed"}


@dataclass(frozen=True)
class CacheInventoryItem:
    path: str
    project_id: str
    project_status: str
    size_bytes: int
    last_opened_at: dt.datetime
    pending_count: int
    outbox_count: int

    @property
    def dirty(self) -> bool:
        return bool(self.pending_count or self.outbox_count)

    @property
    def completed(self) -> bool:
        return self.project_status.strip().lower() in COMPLETED_STATUSES


@dataclass(frozen=True)
class CacheCleanupDecision:
    path: str
    project_id: str
    size_bytes: int
    reason: str


@dataclass(frozen=True)
class CacheCleanupResult:
    deleted_files: int
    deleted_bytes: int
    failed_files: int
    decisions: tuple[CacheCleanupDecision, ...]


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (str(name),),
        ).fetchone()
    )


def _row_count_if_table(conn: sqlite3.Connection, table: str) -> int:
    if not _table_exists(conn, table):
        return 0
    return int(conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0])


def _parse_datetime(value: str, fallback_timestamp: float) -> dt.datetime:
    raw = str(value or "").strip()
    if raw:
        try:
            parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.timezone.utc)
            return parsed.astimezone(dt.timezone.utc)
        except (TypeError, ValueError):
            pass
    return dt.datetime.fromtimestamp(float(fallback_timestamp), tz=dt.timezone.utc)


def inspect_cache_file(path: str) -> CacheInventoryItem | None:
    snapshot = Path(path)
    if not snapshot.is_file() or snapshot.suffix.lower() != ".gpkg":
        return None

    conn = None
    try:
        uri = snapshot.resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5)
        conn.execute("PRAGMA busy_timeout=5000")
        if not _table_exists(conn, "_geoflow_package"):
            return None
        metadata = {
            str(key): str(value or "")
            for key, value in conn.execute(
                "SELECT key, value FROM _geoflow_package"
            ).fetchall()
        }
        try:
            project_id = str(uuid.UUID(str(metadata.get("project_id") or "")))
        except (TypeError, ValueError, AttributeError):
            return None

        stat = snapshot.stat()
        return CacheInventoryItem(
            path=str(snapshot),
            project_id=project_id,
            project_status=str(metadata.get("cache_project_status") or ""),
            size_bytes=int(stat.st_size),
            last_opened_at=_parse_datetime(
                metadata.get("cache_last_opened_at", ""),
                stat.st_mtime,
            ),
            pending_count=_row_count_if_table(conn, "_geoflow_pending_change"),
            outbox_count=_row_count_if_table(conn, "_geoflow_outbox"),
        )
    except (OSError, sqlite3.Error):
        return None
    finally:
        if conn is not None:
            conn.close()


def inventory_cache(root_dir: str) -> tuple[CacheInventoryItem, ...]:
    root = Path(root_dir)
    if not root.is_dir():
        return ()
    rows = []
    for path in root.glob("*/*.gpkg"):
        item = inspect_cache_file(str(path))
        if item is not None:
            rows.append(item)
    return tuple(rows)


def _normalize_paths(paths: Iterable[str]) -> set[str]:
    result = set()
    for path in paths:
        try:
            result.add(str(Path(path).resolve()))
        except OSError:
            result.add(os.path.abspath(str(path)))
    return result


def plan_cache_cleanup(
    items: Iterable[CacheInventoryItem],
    *,
    now: dt.datetime | None = None,
    active_unused_days: int = 90,
    completed_grace_days: int = 30,
    quota_bytes: int = 0,
    pinned_project_ids: Iterable[str] = (),
    protected_paths: Iterable[str] = (),
) -> tuple[CacheCleanupDecision, ...]:
    current_time = now or dt.datetime.now(dt.timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=dt.timezone.utc)
    current_time = current_time.astimezone(dt.timezone.utc)

    active_unused_days = max(1, int(active_unused_days))
    completed_grace_days = max(1, int(completed_grace_days))
    quota_bytes = max(0, int(quota_bytes))
    pinned = {str(value) for value in pinned_project_ids if str(value)}
    protected = _normalize_paths(protected_paths)
    rows = list(items)

    eligible = []
    protected_items = []
    for item in rows:
        try:
            resolved = str(Path(item.path).resolve())
        except OSError:
            resolved = os.path.abspath(item.path)
        if item.dirty or item.project_id in pinned or resolved in protected:
            protected_items.append(item)
            continue
        eligible.append(item)

    decisions: list[CacheCleanupDecision] = []
    selected_paths: set[str] = set()
    for item in eligible:
        age_days = max(
            0.0,
            (current_time - item.last_opened_at).total_seconds() / 86400.0,
        )
        threshold = completed_grace_days if item.completed else active_unused_days
        if age_days < threshold:
            continue
        reason = "completed_grace_expired" if item.completed else "inactive_expired"
        decisions.append(
            CacheCleanupDecision(
                path=item.path,
                project_id=item.project_id,
                size_bytes=item.size_bytes,
                reason=reason,
            )
        )
        selected_paths.add(item.path)

    if quota_bytes > 0:
        total_bytes = sum(item.size_bytes for item in rows)
        planned_bytes = sum(decision.size_bytes for decision in decisions)
        remaining_bytes = max(0, total_bytes - planned_bytes)
        if remaining_bytes > quota_bytes:
            quota_candidates = [
                item for item in eligible if item.path not in selected_paths
            ]
            # Completed caches are the first eviction class. Within each class
            # use LRU so the oldest local project cache is removed first.
            quota_candidates.sort(
                key=lambda item: (
                    0 if item.completed else 1,
                    item.last_opened_at,
                    item.path,
                )
            )
            for item in quota_candidates:
                if remaining_bytes <= quota_bytes:
                    break
                decisions.append(
                    CacheCleanupDecision(
                        path=item.path,
                        project_id=item.project_id,
                        size_bytes=item.size_bytes,
                        reason="quota_lru",
                    )
                )
                selected_paths.add(item.path)
                remaining_bytes = max(0, remaining_bytes - item.size_bytes)

    return tuple(decisions)


def execute_cache_cleanup(
    root_dir: str,
    decisions: Iterable[CacheCleanupDecision],
) -> CacheCleanupResult:
    root = Path(root_dir)
    try:
        root_resolved = root.resolve()
    except OSError:
        root_resolved = Path(os.path.abspath(str(root)))

    deleted_files = 0
    deleted_bytes = 0
    failed_files = 0
    applied: list[CacheCleanupDecision] = []
    for decision in decisions:
        path = Path(decision.path)
        try:
            resolved = path.resolve()
            if root_resolved not in resolved.parents:
                failed_files += 1
                continue
            if not path.is_file() or path.suffix.lower() != ".gpkg":
                continue
            size = int(path.stat().st_size)
            path.unlink()
            deleted_files += 1
            deleted_bytes += size
            applied.append(decision)
            try:
                parent = path.parent
                if parent != root_resolved and not any(parent.iterdir()):
                    parent.rmdir()
            except OSError:
                pass
        except OSError:
            # A file open in another QGIS process is intentionally left alone.
            failed_files += 1

    return CacheCleanupResult(
        deleted_files=deleted_files,
        deleted_bytes=deleted_bytes,
        failed_files=failed_files,
        decisions=tuple(applied),
    )
