from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
import struct
import tempfile
import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from django.db import connections


GPKG_APPLICATION_ID = 0x47504B47
SNAPSHOT_BATCH_ROWS = 5_000
_SAFE_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


@dataclass(frozen=True)
class PackageField:
    name: str
    data_type: str
    editable: bool
    visible: bool
    sort_order: int


@dataclass(frozen=True)
class PackageLayer:
    standard_name: str
    physical_name: str
    label: str
    domain: str
    geometry_kind: str
    fields: tuple[PackageField, ...]


def _quote_ident(value: str) -> str:
    if not _SAFE_IDENT.fullmatch(value):
        raise ValueError(f"unsafe GIS identifier: {value}")
    return '"' + value + '"'


def _sqlite_type(pg_type: str) -> str:
    value = (pg_type or "").lower()
    if any(token in value for token in ("smallint", "integer", "bigint")):
        return "INTEGER"
    if any(token in value for token in ("numeric", "decimal", "real", "double precision")):
        return "REAL"
    if value == "boolean":
        return "INTEGER"
    if value == "bytea":
        return "BLOB"
    return "TEXT"


def _normalize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, memoryview):
        return bytes(value)
    return value


def gpkg_geometry_blob(wkb: bytes | memoryview | None, *, srs_id: int = 4326) -> bytes | None:
    if wkb is None:
        return None
    raw = bytes(wkb)
    if not raw:
        return None
    return b"GP" + b"\x00" + b"\x01" + struct.pack("<i", int(srs_id)) + raw


def _geometry_type_name(kind: str) -> str:
    return {
        "POINT": "POINT",
        "LINE": "LINESTRING",
        "POLYGON": "POLYGON",
    }.get(str(kind or "").upper(), "GEOMETRY")


def _init_gpkg(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA application_id={GPKG_APPLICATION_ID}")
    conn.execute("PRAGMA user_version=10300")
    conn.executescript(
        """
        CREATE TABLE gpkg_spatial_ref_sys (
            srs_name TEXT NOT NULL,
            srs_id INTEGER NOT NULL PRIMARY KEY,
            organization TEXT NOT NULL,
            organization_coordsys_id INTEGER NOT NULL,
            definition TEXT NOT NULL,
            description TEXT
        );
        CREATE TABLE gpkg_contents (
            table_name TEXT NOT NULL PRIMARY KEY,
            data_type TEXT NOT NULL,
            identifier TEXT UNIQUE,
            description TEXT DEFAULT '',
            last_change DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            min_x DOUBLE,
            min_y DOUBLE,
            max_x DOUBLE,
            max_y DOUBLE,
            srs_id INTEGER,
            CONSTRAINT fk_gc_r_srs_id FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys(srs_id)
        );
        CREATE TABLE gpkg_geometry_columns (
            table_name TEXT NOT NULL,
            column_name TEXT NOT NULL,
            geometry_type_name TEXT NOT NULL,
            srs_id INTEGER NOT NULL,
            z TINYINT NOT NULL,
            m TINYINT NOT NULL,
            CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name),
            CONSTRAINT uk_gc_table_name UNIQUE (table_name),
            CONSTRAINT fk_gc_tn FOREIGN KEY (table_name) REFERENCES gpkg_contents(table_name),
            CONSTRAINT fk_gc_srs FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys(srs_id)
        );
        CREATE TABLE gpkg_extensions (
            table_name TEXT,
            column_name TEXT,
            extension_name TEXT NOT NULL,
            definition TEXT NOT NULL,
            scope TEXT NOT NULL,
            CONSTRAINT ge_tce UNIQUE (table_name, column_name, extension_name)
        );
        CREATE TABLE _geoflow_package (
            key TEXT NOT NULL PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE _geoflow_baseline (
            layer_name TEXT NOT NULL,
            object_id TEXT NOT NULL,
            local_fid INTEGER NOT NULL,
            source_updated_at TEXT,
            PRIMARY KEY(layer_name, object_id),
            UNIQUE(layer_name, local_fid)
        );
        """
    )
    conn.executemany(
        "INSERT INTO gpkg_spatial_ref_sys(srs_name,srs_id,organization,organization_coordsys_id,definition,description) VALUES (?,?,?,?,?,?)",
        [
            ("Undefined Cartesian SRS", -1, "NONE", -1, "undefined", "undefined cartesian coordinate reference system"),
            ("Undefined geographic SRS", 0, "NONE", 0, "undefined", "undefined geographic coordinate reference system"),
            (
                "WGS 84 geodetic",
                4326,
                "EPSG",
                4326,
                'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433],AXIS["Latitude",NORTH],AXIS["Longitude",EAST],AUTHORITY["EPSG","4326"]]',
                "longitude/latitude coordinates in decimal degrees on the WGS 84 spheroid",
            ),
        ],
    )


def _profile_layer_fields(alias: str, profile_id: str, physical_name: str) -> tuple[PackageField, ...]:
    with connections[alias].cursor() as cursor:
        cursor.execute(
            """
            SELECT fd.physical_name, fd.data_type, pf.editable, pf.visible, pf.sort_order
              FROM gis.profile_field pf
              JOIN gis.meta_field_def fd ON fd.id=pf.field_def_id
              JOIN gis.meta_feature_type ft ON ft.id=fd.feature_type_id
             WHERE pf.profile_id=%s::uuid
               AND pf.enabled
               AND ft.physical_name=%s
             ORDER BY pf.sort_order, fd.sort_order, fd.physical_name
            """,
            [profile_id, physical_name],
        )
        rows = cursor.fetchall()
    fields = []
    for name, data_type, editable, visible, sort_order in rows:
        if name == "geom":
            continue
        if not _SAFE_IDENT.fullmatch(name):
            continue
        fields.append(
            PackageField(
                name=name,
                data_type=data_type or "text",
                editable=bool(editable),
                visible=bool(visible),
                sort_order=int(sort_order or 0),
            )
        )
    by_name = {field.name: field for field in fields}
    for required_name in ("id", "project_id"):
        if required_name not in by_name:
            fields.insert(0, PackageField(required_name, "uuid", False, True, -100))
    return tuple(fields)


def _layer_specs(alias: str, plan: dict[str, Any]) -> tuple[PackageLayer, ...]:
    profile = plan.get("profile") or {}
    profile_id = str(profile.get("id") or "")
    if not profile_id:
        raise ValueError("active GIS profile is required for GeoPackage materialization")
    specs = []
    for row in plan.get("layers") or []:
        physical_name = str(row.get("physical_name") or "")
        if not _SAFE_IDENT.fullmatch(physical_name):
            raise ValueError(f"unsafe GIS layer name: {physical_name}")
        specs.append(
            PackageLayer(
                standard_name=str(row.get("standard_name") or physical_name.upper()),
                physical_name=physical_name,
                label=str(row.get("label") or row.get("standard_name") or physical_name),
                domain=str(row.get("domain") or ""),
                geometry_kind=str(row.get("geometry_kind") or ""),
                fields=_profile_layer_fields(alias, profile_id, physical_name),
            )
        )
    return tuple(specs)


def project_geopackage_layer_manifest(alias: str, plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "standard_name": layer.standard_name,
            "physical_name": layer.physical_name,
            "label": layer.label,
            "domain": layer.domain,
            "geometry_kind": layer.geometry_kind,
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
        for layer in _layer_specs(alias, plan)
    ]


def _rtree_name(layer: PackageLayer) -> str:
    return f"rtree_{layer.physical_name}_geom"


def _create_feature_table(sqlite_conn: sqlite3.Connection, layer: PackageLayer) -> None:
    columns = ["fid INTEGER PRIMARY KEY AUTOINCREMENT"]
    seen = set()
    for field in layer.fields:
        if field.name in seen:
            continue
        seen.add(field.name)
        columns.append(f'{_quote_ident(field.name)} {_sqlite_type(field.data_type)}')
    columns.append('"geom" BLOB')
    table = _quote_ident(layer.physical_name)
    sqlite_conn.execute(f"CREATE TABLE {table} ({', '.join(columns)})")
    sqlite_conn.execute(
        "INSERT INTO gpkg_contents(table_name,data_type,identifier,description,srs_id) VALUES (?,?,?,?,4326)",
        (layer.physical_name, "features", layer.label, layer.standard_name),
    )
    sqlite_conn.execute(
        "INSERT INTO gpkg_geometry_columns(table_name,column_name,geometry_type_name,srs_id,z,m) VALUES (?,?,?,?,0,0)",
        (layer.physical_name, "geom", _geometry_type_name(layer.geometry_kind), 4326),
    )
    sqlite_conn.execute(f"CREATE UNIQUE INDEX {_quote_ident(layer.physical_name + '_id_uq')} ON {table}(\"id\")")
    sqlite_conn.execute(f"CREATE INDEX {_quote_ident(layer.physical_name + '_project_idx')} ON {table}(\"project_id\")")

    rtree = _quote_ident(_rtree_name(layer))
    sqlite_conn.execute(f"CREATE VIRTUAL TABLE {rtree} USING rtree(id, minx, maxx, miny, maxy)")
    sqlite_conn.execute(
        "INSERT INTO gpkg_extensions(table_name,column_name,extension_name,definition,scope) VALUES (?,?,?,?,?)",
        (
            layer.physical_name,
            "geom",
            "gpkg_rtree_index",
            "http://www.geopackage.org/spec/#extension_rtree",
            "write-only",
        ),
    )


def _install_rtree_triggers(sqlite_conn: sqlite3.Connection, layer: PackageLayer) -> None:
    table = _quote_ident(layer.physical_name)
    rtree = _quote_ident(_rtree_name(layer))
    prefix = _rtree_name(layer)
    sqlite_conn.executescript(
        f"""
        CREATE TRIGGER {_quote_ident(prefix + '_insert')}
        AFTER INSERT ON {table}
        WHEN NEW.geom IS NOT NULL AND NOT ST_IsEmpty(NEW.geom)
        BEGIN
            INSERT OR REPLACE INTO {rtree} VALUES (
                NEW.fid, ST_MinX(NEW.geom), ST_MaxX(NEW.geom), ST_MinY(NEW.geom), ST_MaxY(NEW.geom)
            );
        END;

        CREATE TRIGGER {_quote_ident(prefix + '_update')}
        AFTER UPDATE OF geom ON {table}
        BEGIN
            DELETE FROM {rtree} WHERE id = OLD.fid;
            INSERT OR REPLACE INTO {rtree}
            SELECT NEW.fid, ST_MinX(NEW.geom), ST_MaxX(NEW.geom), ST_MinY(NEW.geom), ST_MaxY(NEW.geom)
             WHERE NEW.geom IS NOT NULL AND NOT ST_IsEmpty(NEW.geom);
        END;

        CREATE TRIGGER {_quote_ident(prefix + '_delete')}
        AFTER DELETE ON {table}
        BEGIN
            DELETE FROM {rtree} WHERE id = OLD.fid;
        END;
        """
    )


def _update_contents_extent(
    sqlite_conn: sqlite3.Connection,
    layer: PackageLayer,
    extent: tuple[float, float, float, float] | None,
) -> None:
    if extent is None:
        return
    minx, miny, maxx, maxy = extent
    sqlite_conn.execute(
        "UPDATE gpkg_contents SET min_x=?, min_y=?, max_x=?, max_y=? WHERE table_name=?",
        (minx, miny, maxx, maxy, layer.physical_name),
    )


def _copy_layer_rows(alias: str, sqlite_conn: sqlite3.Connection, layer: PackageLayer, project_id: str) -> int:
    table = _quote_ident(layer.physical_name)
    field_names = [field.name for field in layer.fields]
    select_fields = ", ".join(_quote_ident(name) for name in field_names)
    source_table = f'"gis".{table}'
    id_index = field_names.index("id")
    insert_columns = field_names + ["geom"]
    quoted_columns = ", ".join(_quote_ident(name) for name in insert_columns)
    placeholders = ", ".join("?" for _ in insert_columns)
    insert_sql = f"INSERT INTO {table} ({quoted_columns}) VALUES ({placeholders})"
    rtree = _quote_ident(_rtree_name(layer))

    row_count = 0
    last_source_id = None
    last_local_fid = 0
    extent = None

    while True:
        where = "project_id=%s"
        params: list[Any] = [project_id]
        if last_source_id is not None:
            where += " AND id>%s::uuid"
            params.append(last_source_id)
        params.append(SNAPSHOT_BATCH_ROWS)

        with connections[alias].cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {select_fields},
                       ST_AsBinary(geom),
                       updated_at,
                       ST_XMin(ST_Box3D(geom)),
                       ST_YMin(ST_Box3D(geom)),
                       ST_XMax(ST_Box3D(geom)),
                       ST_YMax(ST_Box3D(geom))
                  FROM {source_table}
                 WHERE {where}
                 ORDER BY id
                 LIMIT %s
                """,
                params,
            )
            rows = cursor.fetchall()

        if not rows:
            break

        payload = []
        source_updated_by_id: dict[str, Any] = {}
        bbox_by_id: dict[str, tuple[float, float, float, float] | None] = {}
        for row in rows:
            object_id = str(uuid.UUID(str(row[id_index])))
            attrs = [_normalize_value(value) for value in row[: len(field_names)]]
            attrs.append(gpkg_geometry_blob(row[len(field_names)], srs_id=4326))
            payload.append(tuple(attrs))
            source_updated_by_id[object_id] = _normalize_value(row[len(field_names) + 1])
            bbox_values = row[len(field_names) + 2 : len(field_names) + 6]
            if all(value is not None for value in bbox_values):
                minx, miny, maxx, maxy = (float(value) for value in bbox_values)
                bbox_by_id[object_id] = (minx, miny, maxx, maxy)
                if extent is None:
                    extent = (minx, miny, maxx, maxy)
                else:
                    extent = (
                        min(extent[0], minx),
                        min(extent[1], miny),
                        max(extent[2], maxx),
                        max(extent[3], maxy),
                    )
            else:
                bbox_by_id[object_id] = None

        sqlite_conn.executemany(insert_sql, payload)
        local_rows = sqlite_conn.execute(
            f"SELECT id, fid FROM {table} WHERE fid>? ORDER BY fid",
            (last_local_fid,),
        ).fetchall()
        baseline = []
        rtree_rows = []
        for object_id, fid in local_rows:
            canonical_id = str(uuid.UUID(str(object_id)))
            local_fid = int(fid)
            baseline.append(
                (
                    layer.physical_name,
                    canonical_id,
                    local_fid,
                    source_updated_by_id[canonical_id],
                )
            )
            bbox = bbox_by_id.get(canonical_id)
            if bbox is not None:
                rtree_rows.append((local_fid, bbox[0], bbox[2], bbox[1], bbox[3]))
            last_local_fid = max(last_local_fid, local_fid)

        if baseline:
            sqlite_conn.executemany(
                "INSERT INTO _geoflow_baseline(layer_name,object_id,local_fid,source_updated_at) VALUES (?,?,?,?)",
                baseline,
            )
        if rtree_rows:
            sqlite_conn.executemany(
                f"INSERT INTO {rtree}(id,minx,maxx,miny,maxy) VALUES (?,?,?,?,?)",
                rtree_rows,
            )

        row_count += len(rows)
        last_source_id = str(uuid.UUID(str(rows[-1][id_index])))

    _update_contents_extent(sqlite_conn, layer, extent)
    _install_rtree_triggers(sqlite_conn, layer)
    return row_count


def build_project_geopackage(alias: str, *, project_id: str, plan: dict[str, Any]) -> tuple[bytes, list[dict[str, Any]]]:
    specs = _layer_specs(alias, plan)
    if not specs:
        raise ValueError("project Layer Plan is empty")

    temp = tempfile.NamedTemporaryFile(prefix="geoflow-project-", suffix=".gpkg", delete=False)
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
                count = _copy_layer_rows(alias, sqlite_conn, layer, str(project_id))
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
        return temp_path.read_bytes(), layer_meta
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
