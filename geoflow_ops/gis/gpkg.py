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


MAX_ROWS_PER_LAYER = 100_000
GPKG_APPLICATION_ID = 0x47504B47
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


def _copy_layer_rows(alias: str, sqlite_conn: sqlite3.Connection, layer: PackageLayer, project_id: str) -> int:
    table = _quote_ident(layer.physical_name)
    field_names = [field.name for field in layer.fields]
    select_fields = ", ".join(_quote_ident(name) for name in field_names)
    source_table = f'"gis".{table}'

    with connections[alias].cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM {source_table} WHERE project_id=%s", [project_id])
        row_count = int(cursor.fetchone()[0])
        if row_count > MAX_ROWS_PER_LAYER:
            raise ValueError(
                f"{layer.standard_name} has {row_count} rows; GeoPackage MVP limit is {MAX_ROWS_PER_LAYER}"
            )
        cursor.execute(
            f"SELECT {select_fields}, ST_AsBinary(geom) FROM {source_table} WHERE project_id=%s ORDER BY id",
            [project_id],
        )
        rows = cursor.fetchall()

    insert_columns = field_names + ["geom"]
    quoted_columns = ", ".join(_quote_ident(name) for name in insert_columns)
    placeholders = ", ".join("?" for _ in insert_columns)
    insert_sql = f"INSERT INTO {table} ({quoted_columns}) VALUES ({placeholders})"
    payload = []
    for row in rows:
        attrs = [_normalize_value(value) for value in row[:-1]]
        attrs.append(gpkg_geometry_blob(row[-1], srs_id=4326))
        payload.append(tuple(attrs))
    if payload:
        sqlite_conn.executemany(insert_sql, payload)
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
            _init_gpkg(sqlite_conn)
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
