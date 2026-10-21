"""Online-only changeset helpers and one-way legacy queue migration."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path


LEGACY_QUEUE_TABLES = (
    "_geoflow_pending_change",
    "_geoflow_outbox",
    "_geoflow_conflict",
    "_geoflow_pending_photo",
)


def change_signature(changes: list[dict]) -> str:
    """Stable in-memory retry identity; no payload is written to disk."""
    raw = json.dumps(
        changes, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def legacy_queue_status(package_path: str) -> dict[str, int]:
    """Inspect stale queue rows without creating or modifying a database."""
    result = {table: 0 for table in LEGACY_QUEUE_TABLES}
    if not package_path or not os.path.isfile(package_path):
        return result
    connection = sqlite3.connect(Path(package_path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        for table in LEGACY_QUEUE_TABLES:
            if table in tables:
                result[table] = int(
                    connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
                )
        return result
    finally:
        connection.close()


def legacy_queue_packages(project_dir: str) -> list[tuple[str, dict[str, int]]]:
    """Find inert legacy rows in all project packages, including quarantine."""
    root = Path(project_dir)
    if not root.is_dir():
        return []
    found = []
    for path in root.rglob("*.gpkg"):
        status = legacy_queue_status(str(path))
        if sum(status.values()):
            found.append((str(path), status))
    return found


def clear_legacy_queue(package_path: str) -> int:
    """Delete stale rows only after explicit user confirmation."""
    status = legacy_queue_status(package_path)
    total = sum(status.values())
    if not total:
        return 0
    connection = sqlite3.connect(package_path, timeout=30)
    try:
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("BEGIN IMMEDIATE")
        for table, count in status.items():
            if count:
                connection.execute(f'DELETE FROM "{table}"')
        connection.commit()
        return total
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def read_last_applied_revision(package_path: str) -> int:
    connection = sqlite3.connect(package_path, timeout=30)
    try:
        row = connection.execute(
            "SELECT value FROM _geoflow_package WHERE key='last_applied_revision'"
        ).fetchone()
        return int(row[0]) if row and row[0] not in (None, "") else 0
    finally:
        connection.close()


def write_last_applied_revision(package_path: str, revision: int) -> None:
    connection = sqlite3.connect(package_path, timeout=30)
    try:
        connection.execute(
            "INSERT OR REPLACE INTO _geoflow_package(key,value) VALUES ('last_applied_revision',?)",
            (str(int(revision)),),
        )
        connection.commit()
    finally:
        connection.close()
