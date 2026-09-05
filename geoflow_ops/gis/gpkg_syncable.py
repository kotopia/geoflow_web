from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from django.db import connections, transaction

from .gpkg import _layer_specs, build_project_geopackage
from .qgis_sync_hash import content_hash, extract_gpkg_wkb


IMMUTABLE_FIELDS = {
    "id",
    "project_id",
    "created_at",
    "updated_at",
    "created_by",
    "updated_by",
}


def _ensure_hash_column(conn: sqlite3.Connection) -> None:
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info('_geoflow_baseline')").fetchall()
    }
    if "content_hash" not in columns:
        conn.execute("ALTER TABLE _geoflow_baseline ADD COLUMN content_hash TEXT")


def _snapshot_revision(alias: str, project_id: str) -> int:
    with connections[alias].cursor() as cursor:
        cursor.execute("SELECT to_regclass('gis.project_sync_state')")
        if cursor.fetchone()[0] is None:
            return 0
        cursor.execute(
            "SELECT current_revision FROM gis.project_sync_state WHERE project_id=%s",
            [project_id],
        )
        row = cursor.fetchone()
    return int(row[0]) if row else 0


def build_syncable_project_geopackage(
    alias: str,
    *,
    project_id: str,
    plan: dict[str, Any],
) -> tuple[bytes, list[dict[str, Any]]]:
    # A Delta cursor is valid only when every layer in the package was read from
    # the same PostgreSQL snapshot. REPEATABLE READ keeps the server snapshot
    # coherent even if another QGIS/QField client commits while materialization
    # is in progress.
    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        snapshot_revision = _snapshot_revision(alias, project_id)
        payload, layer_meta = build_project_geopackage(
            alias,
            project_id=project_id,
            plan=plan,
        )

    temp = tempfile.NamedTemporaryFile(
        prefix="geoflow-syncable-",
        suffix=".gpkg",
        delete=False,
    )
    temp_path = Path(temp.name)
    try:
        temp.write(payload)
        temp.close()
        conn = sqlite3.connect(str(temp_path))
        try:
            _ensure_hash_column(conn)
            conn.execute(
                "UPDATE _geoflow_package SET value='0.5' WHERE key='package_version'"
            )
            conn.execute(
                "INSERT OR REPLACE INTO _geoflow_package(key,value) VALUES ('snapshot_revision',?)",
                (str(snapshot_revision),),
            )
            conn.execute(
                "INSERT OR REPLACE INTO _geoflow_package(key,value) VALUES ('last_applied_revision',?)",
                (str(snapshot_revision),),
            )

            for spec in _layer_specs(alias, plan):
                field_names = [field.name for field in spec.fields]
                editable_names = [
                    field.name
                    for field in spec.fields
                    if field.editable and field.name not in IMMUTABLE_FIELDS
                ]
                quoted_fields = ", ".join(f'"{name}"' for name in field_names)
                rows = conn.execute(
                    f'SELECT fid, {quoted_fields}, "geom" FROM "{spec.physical_name}"'
                ).fetchall()
                for row in rows:
                    fid = int(row[0])
                    attrs = dict(zip(field_names, row[1:-1]))
                    object_id = str(attrs["id"])
                    geometry_wkb = extract_gpkg_wkb(row[-1])
                    digest = content_hash(attrs, geometry_wkb, editable_names)
                    conn.execute(
                        """
                        UPDATE _geoflow_baseline
                           SET content_hash=?
                         WHERE layer_name=? AND object_id=? AND local_fid=?
                        """,
                        (digest, spec.physical_name, object_id, fid),
                    )
            conn.commit()
        finally:
            conn.close()
        return temp_path.read_bytes(), layer_meta
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
