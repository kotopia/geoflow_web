from __future__ import annotations

import datetime as dt
import json
import sqlite3
import uuid
from typing import Any


MAX_OUTBOX_ITEMS = 5000


def ensure_changeset_tables(package_path: str) -> None:
    conn = sqlite3.connect(package_path, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS _geoflow_pending_change (
                layer_name TEXT NOT NULL,
                object_id TEXT NOT NULL,
                action TEXT NOT NULL,
                attributes_json TEXT NOT NULL DEFAULT '{}',
                geometry_wkb TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(layer_name, object_id)
            );
            CREATE TABLE IF NOT EXISTS _geoflow_outbox (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                changeset_id TEXT NOT NULL UNIQUE,
                client_id TEXT NOT NULL,
                base_revision INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def _normalize_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    if isinstance(value, dict):
        return {str(key): _normalize_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_json_value(item) for item in value]
    return str(value)


def _read_pending(conn: sqlite3.Connection, layer: str, object_id: str):
    return conn.execute(
        """
        SELECT action, attributes_json, geometry_wkb
          FROM _geoflow_pending_change
         WHERE layer_name=? AND object_id=?
        """,
        (layer, object_id),
    ).fetchone()


def queue_change(
    package_path: str,
    *,
    layer: str,
    object_id: str,
    action: str,
    attributes: dict[str, Any] | None = None,
    geometry_wkb: str | None = None,
) -> None:
    action = str(action or "").lower()
    if action not in {"create", "update", "delete"}:
        raise ValueError(f"unsupported pending action: {action}")
    object_id = str(uuid.UUID(str(object_id)))
    attrs = {
        str(name): _normalize_json_value(value)
        for name, value in (attributes or {}).items()
    }
    now = dt.datetime.now(dt.timezone.utc).isoformat()

    conn = sqlite3.connect(package_path, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        existing = _read_pending(conn, layer, object_id)
        if existing is None:
            if action == "delete":
                attrs = {}
                geometry_wkb = None
            conn.execute(
                """
                INSERT INTO _geoflow_pending_change(
                    layer_name, object_id, action, attributes_json, geometry_wkb, updated_at
                ) VALUES (?,?,?,?,?,?)
                """,
                (
                    layer,
                    object_id,
                    action,
                    json.dumps(attrs, ensure_ascii=False, separators=(",", ":")),
                    geometry_wkb,
                    now,
                ),
            )
            conn.commit()
            return

        old_action, old_attrs_json, old_geometry = existing
        old_attrs = json.loads(old_attrs_json or "{}")

        if old_action == "create" and action == "delete":
            # A local object created and deleted before reaching GeoFlow has no
            # server-side effect and should disappear from the queue entirely.
            conn.execute(
                "DELETE FROM _geoflow_pending_change WHERE layer_name=? AND object_id=?",
                (layer, object_id),
            )
            conn.commit()
            return

        if action == "delete":
            merged_action = "delete"
            merged_attrs = {}
            merged_geometry = None
        elif old_action == "create":
            merged_action = "create"
            merged_attrs = {**old_attrs, **attrs}
            merged_geometry = geometry_wkb if geometry_wkb is not None else old_geometry
        elif old_action == "update" and action == "update":
            merged_action = "update"
            merged_attrs = {**old_attrs, **attrs}
            merged_geometry = geometry_wkb if geometry_wkb is not None else old_geometry
        elif old_action == "delete" and action == "create":
            # Reusing the same UUID after a queued delete is ambiguous. GeoFlow
            # UUID identity is immutable, so require a new UUID instead.
            raise ValueError("cannot recreate a pending-deleted GeoFlow UUID")
        else:
            merged_action = action
            merged_attrs = attrs
            merged_geometry = geometry_wkb

        conn.execute(
            """
            UPDATE _geoflow_pending_change
               SET action=?, attributes_json=?, geometry_wkb=?, updated_at=?
             WHERE layer_name=? AND object_id=?
            """,
            (
                merged_action,
                json.dumps(merged_attrs, ensure_ascii=False, separators=(",", ":")),
                merged_geometry,
                now,
                layer,
                object_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def pending_count(package_path: str) -> int:
    ensure_changeset_tables(package_path)
    conn = sqlite3.connect(package_path, timeout=30)
    try:
        return int(
            conn.execute("SELECT count(*) FROM _geoflow_pending_change").fetchone()[0]
        )
    finally:
        conn.close()


def read_last_applied_revision(package_path: str) -> int:
    conn = sqlite3.connect(package_path, timeout=30)
    try:
        row = conn.execute(
            "SELECT value FROM _geoflow_package WHERE key='last_applied_revision'"
        ).fetchone()
        return int(row[0]) if row and row[0] not in (None, "") else 0
    finally:
        conn.close()


def write_last_applied_revision(package_path: str, revision: int) -> None:
    conn = sqlite3.connect(package_path, timeout=30)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO _geoflow_package(key,value) VALUES ('last_applied_revision',?)",
            (str(int(revision)),),
        )
        conn.commit()
    finally:
        conn.close()


def _oldest_outbox(conn: sqlite3.Connection):
    return conn.execute(
        "SELECT seq, changeset_id, payload_json FROM _geoflow_outbox ORDER BY seq LIMIT 1"
    ).fetchone()


def prepare_outbox(package_path: str, *, client_id: str) -> tuple[str, dict[str, Any]] | None:
    ensure_changeset_tables(package_path)
    client_id = str(uuid.UUID(str(client_id)))
    conn = sqlite3.connect(package_path, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("BEGIN IMMEDIATE")
        existing = _oldest_outbox(conn)
        if existing is not None:
            payload = json.loads(existing[2])
            conn.commit()
            return str(existing[1]), payload

        rows = conn.execute(
            """
            SELECT layer_name, object_id, action, attributes_json, geometry_wkb
              FROM _geoflow_pending_change
             ORDER BY updated_at, layer_name, object_id
             LIMIT ?
            """,
            (MAX_OUTBOX_ITEMS,),
        ).fetchall()
        if not rows:
            conn.commit()
            return None

        revision_row = conn.execute(
            "SELECT value FROM _geoflow_package WHERE key='last_applied_revision'"
        ).fetchone()
        base_revision = int(revision_row[0]) if revision_row and revision_row[0] else 0
        changes = []
        keys = []
        for layer, object_id, action, attrs_json, geometry_wkb in rows:
            item = {
                "action": str(action),
                "layer": str(layer),
                "id": str(object_id),
            }
            attrs = json.loads(attrs_json or "{}")
            if attrs:
                item["attributes"] = attrs
            if geometry_wkb is not None:
                item["geometry_wkb"] = str(geometry_wkb)
            changes.append(item)
            keys.append((str(layer), str(object_id)))

        changeset_id = str(uuid.uuid4())
        payload = {
            "client_id": client_id,
            "changeset_id": changeset_id,
            "base_revision": base_revision,
            "changes": changes,
        }
        conn.execute(
            """
            INSERT INTO _geoflow_outbox(
                changeset_id, client_id, base_revision, payload_json, created_at
            ) VALUES (?,?,?,?,?)
            """,
            (
                changeset_id,
                client_id,
                base_revision,
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                dt.datetime.now(dt.timezone.utc).isoformat(),
            ),
        )
        conn.executemany(
            "DELETE FROM _geoflow_pending_change WHERE layer_name=? AND object_id=?",
            keys,
        )
        conn.commit()
        return changeset_id, payload
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def acknowledge_outbox(package_path: str, changeset_id: str) -> None:
    conn = sqlite3.connect(package_path, timeout=30)
    try:
        conn.execute(
            "DELETE FROM _geoflow_outbox WHERE changeset_id=?",
            (str(changeset_id),),
        )
        conn.commit()
    finally:
        conn.close()


def outbox_count(package_path: str) -> int:
    ensure_changeset_tables(package_path)
    conn = sqlite3.connect(package_path, timeout=30)
    try:
        return int(conn.execute("SELECT count(*) FROM _geoflow_outbox").fetchone()[0])
    finally:
        conn.close()
