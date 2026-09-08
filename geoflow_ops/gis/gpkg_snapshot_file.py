from __future__ import annotations

import datetime as dt
import sqlite3
import tempfile
import uuid
from pathlib import Path
from typing import Any

from .gpkg_snapshot_v2 import (
    SNAPSHOT_BATCH_ROWS,
    _copy_layer_rows,
    _create_feature_table,
    _init_gpkg,
    _layer_specs,
)


def build_project_geopackage_file(
    alias: str,
    *,
    project_id: str,
    plan: dict[str, Any],
) -> tuple[Path, list[dict[str, Any]]]:
    """Materialize a project GeoPackage directly on disk.

    The older bytes-returning helper is retained for compatibility, but large
    QGIS snapshots should use this path so the server never has to hold the
    entire GeoPackage payload in Python memory merely to hand it to the HTTP
    response layer.

    The caller owns the returned temporary file and must remove or move it.
    """

    specs = _layer_specs(alias, plan)
    if not specs:
        raise ValueError("project Layer Plan is empty")

    temp = tempfile.NamedTemporaryFile(
        prefix="geoflow-project-file-",
        suffix=".gpkg",
        delete=False,
    )
    temp_path = Path(temp.name)
    temp.close()
    layer_meta: list[dict[str, Any]] = []

    try:
        sqlite_conn = sqlite3.connect(str(temp_path))
        try:
            sqlite_conn.execute("PRAGMA temp_store=MEMORY")
            sqlite_conn.execute("PRAGMA cache_size=-65536")
            _init_gpkg(sqlite_conn)
            profile = plan.get("profile") or {}
            sqlite_conn.executemany(
                "INSERT INTO _geoflow_package(key,value) VALUES (?,?)",
                [
                    ("package_version", "0.6"),
                    ("package_id", str(uuid.uuid4())),
                    ("project_id", str(uuid.UUID(str(project_id)))),
                    ("profile_id", str(profile.get("id") or "")),
                    ("profile_code", str(profile.get("code") or "")),
                    ("generated_at", dt.datetime.now(dt.timezone.utc).isoformat()),
                    ("snapshot_batch_rows", str(SNAPSHOT_BATCH_ROWS)),
                    ("spatial_index", "gpkg_rtree_index"),
                ],
            )
            for layer in specs:
                _create_feature_table(sqlite_conn, layer)
                count = _copy_layer_rows(
                    alias,
                    sqlite_conn,
                    layer,
                    str(project_id),
                )
                layer_meta.append(
                    {
                        "standard_name": layer.standard_name,
                        "physical_name": layer.physical_name,
                        "label": layer.label,
                        "domain": layer.domain,
                        "geometry_kind": layer.geometry_kind,
                        "row_count": count,
                        "spatial_index": "rtree",
                        "fields": [
                            {
                                "name": field.name,
                                "data_type": field.data_type,
                                "editable": field.editable,
                                "visible": field.visible,
                                "sort_order": field.sort_order,
                            }
                            for field in layer.fields
                        ],
                    }
                )
            sqlite_conn.commit()
        finally:
            sqlite_conn.close()
        return temp_path, layer_meta
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
