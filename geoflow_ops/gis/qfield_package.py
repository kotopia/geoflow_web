from __future__ import annotations

import datetime as dt
import html
import os
import sqlite3
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any

from django.conf import settings

from .gpkg_snapshot_v2 import (
    _create_feature_table,
    _init_gpkg,
    _install_rtree_triggers,
    _layer_specs,
)


QFIELD_PACKAGE_VERSION = "0.3"
PROJECT_BASENAME = "geoflow-field"


def _geometry_name(kind: str) -> str:
    return {
        "POINT": "Point",
        "LINE": "Line",
        "POLYGON": "Polygon",
    }.get(str(kind or "").upper(), "Unknown")


def _project_crs_xml() -> str:
    return """
      <spatialrefsys>
        <wkt>GEOGCRS[&quot;WGS 84&quot;,ENSEMBLE[&quot;World Geodetic System 1984 ensemble&quot;,MEMBER[&quot;World Geodetic System 1984 (Transit)&quot;],MEMBER[&quot;World Geodetic System 1984 (G730)&quot;],MEMBER[&quot;World Geodetic System 1984 (G873)&quot;],MEMBER[&quot;World Geodetic System 1984 (G1150)&quot;],MEMBER[&quot;World Geodetic System 1984 (G1674)&quot;],MEMBER[&quot;World Geodetic System 1984 (G1762)&quot;],MEMBER[&quot;World Geodetic System 1984 (G2139)&quot;],ELLIPSOID[&quot;WGS 84&quot;,6378137,298.257223563,LENGTHUNIT[&quot;metre&quot;,1]],ENSEMBLEACCURACY[2.0]],PRIMEM[&quot;Greenwich&quot;,0,ANGLEUNIT[&quot;degree&quot;,0.0174532925199433]],CS[ellipsoidal,2],AXIS[&quot;geodetic latitude (Lat)&quot;,north,ORDER[1],ANGLEUNIT[&quot;degree&quot;,0.0174532925199433]],AXIS[&quot;geodetic longitude (Lon)&quot;,east,ORDER[2],ANGLEUNIT[&quot;degree&quot;,0.0174532925199433]],USAGE[SCOPE[&quot;Horizontal component of 3D system.&quot;],AREA[&quot;World.&quot;],BBOX[-90,-180,90,180]],ID[&quot;EPSG&quot;,4326]]</wkt>
        <proj4>+proj=longlat +datum=WGS84 +no_defs</proj4>
        <srsid>3452</srsid>
        <srid>4326</srid>
        <authid>EPSG:4326</authid>
        <description>WGS 84</description>
        <projectionacronym>longlat</projectionacronym>
        <ellipsoidacronym>EPSG:7030</ellipsoidacronym>
        <geographicflag>true</geographicflag>
      </spatialrefsys>
    """.strip()


def build_empty_qfield_geopackage(
    alias: str,
    *,
    project_id: str,
    plan: dict[str, Any],
) -> tuple[Path, list[dict[str, Any]]]:
    specs = _layer_specs(alias, plan)
    if not specs:
        raise ValueError("project Layer Plan is empty")

    temp = tempfile.NamedTemporaryFile(
        prefix="geoflow-qfield-empty-",
        suffix=".gpkg",
        delete=False,
    )
    path = Path(temp.name)
    temp.close()
    layer_meta = []
    try:
        conn = sqlite3.connect(str(path))
        try:
            _init_gpkg(conn)
            profile = plan.get("profile") or {}
            conn.executemany(
                "INSERT INTO _geoflow_package(key,value) VALUES (?,?)",
                [
                    ("package_version", "0.7"),
                    ("package_id", str(uuid.uuid4())),
                    ("project_id", str(uuid.UUID(str(project_id)))),
                    ("profile_id", str(profile.get("id") or "")),
                    ("profile_code", str(profile.get("code") or "")),
                    ("generated_at", dt.datetime.now(dt.timezone.utc).isoformat()),
                    ("qfield_package_version", QFIELD_PACKAGE_VERSION),
                    ("spatial_index", "gpkg_rtree_index"),
                ],
            )
            conn.executescript(
                """
                CREATE TABLE _geoflow_qfield_cell (
                    cell_key TEXT PRIMARY KEY,
                    priority TEXT NOT NULL DEFAULT 'prefetch',
                    fetched_at TEXT NOT NULL,
                    last_used_at TEXT NOT NULL,
                    complete INTEGER NOT NULL DEFAULT 1,
                    dirty INTEGER NOT NULL DEFAULT 0,
                    pending INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE _geoflow_qfield_object_cell (
                    layer_name TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    cell_key TEXT NOT NULL,
                    PRIMARY KEY(layer_name, object_id, cell_key)
                );
                CREATE TABLE _geoflow_pending_change (
                    layer_name TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    attributes_json TEXT NOT NULL DEFAULT '{}',
                    geometry_wkb TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(layer_name, object_id)
                );
                CREATE TABLE _geoflow_outbox (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    changeset_id TEXT NOT NULL UNIQUE,
                    client_id TEXT NOT NULL,
                    base_revision INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            for spec in specs:
                _create_feature_table(conn, spec)
                _install_rtree_triggers(conn, spec)
                layer_meta.append(
                    {
                        "standard_name": spec.standard_name,
                        "physical_name": spec.physical_name,
                        "label": spec.label,
                        "domain": spec.domain,
                        "geometry_kind": spec.geometry_kind,
                        "fields": [
                            {
                                "name": field.name,
                                "data_type": field.data_type,
                                "editable": field.editable,
                                "visible": field.visible,
                                "sort_order": field.sort_order,
                            }
                            for field in spec.fields
                        ],
                    }
                )
            conn.commit()
        finally:
            conn.close()
        return path, layer_meta
    except Exception:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _qgs_xml(
    *,
    project: dict,
    layers: list[dict[str, Any]],
    server_url: str,
    token: str,
    roaming_plan_url: str,
    roaming_cell_url: str,
    project_center: list[float] | None,
) -> str:
    project_id = str(project["id"])
    project_code = str(project.get("code") or project_id[:8])
    project_name = str(project.get("name") or project_code)
    center = project_center or [127.5, 36.5]
    span = 0.01
    minx, miny, maxx, maxy = center[0] - span, center[1] - span, center[0] + span, center[1] + span

    tree_rows = []
    layer_rows = []
    for layer in layers:
        physical = str(layer["physical_name"])
        label = str(layer.get("label") or layer.get("standard_name") or physical)
        layer_id = f"{physical}_{uuid.uuid4().hex[:12]}"
        tree_rows.append(
            f'<layer-tree-layer providerKey="ogr" source="./geoflow-field.gpkg|layername={html.escape(physical)}" '
            f'checked="Qt::Checked" expanded="1" name="{html.escape(label)}" id="{layer_id}"/>'
        )
        layer_rows.append(
            f"""
    <maplayer type="vector" geometry="{_geometry_name(layer.get('geometry_kind'))}" simplifyDrawingHints="1" simplifyAlgorithm="0" simplifyLocal="1" readOnly="0">
      <extent><xmin>{minx}</xmin><ymin>{miny}</ymin><xmax>{maxx}</xmax><ymax>{maxy}</ymax></extent>
      <id>{layer_id}</id>
      <datasource>./geoflow-field.gpkg|layername={html.escape(physical)}</datasource>
      <keywordList><value></value></keywordList>
      <layername>{html.escape(physical)}</layername>
      <srs>{_project_crs_xml()}</srs>
      <provider encoding="UTF-8">ogr</provider>
      <customproperties>
        <Option type="Map">
          <Option name="geoflow/project_id" value="{html.escape(project_id)}" type="QString"/>
          <Option name="geoflow/physical_name" value="{html.escape(physical)}" type="QString"/>
        </Option>
      </customproperties>
    </maplayer>
            """.strip()
        )

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<qgis projectname="{html.escape(project_code)}" version="3.40.0">
  <homePath path="."/>
  <title>{html.escape(project_name)}</title>
  <autotransaction active="0"/>
  <evaluateDefaultValues active="1"/>
  <projectCrs>{_project_crs_xml()}</projectCrs>
  <mapcanvas name="theMapCanvas">
    <units>degrees</units>
    <extent><xmin>{minx}</xmin><ymin>{miny}</ymin><xmax>{maxx}</xmax><ymax>{maxy}</ymax></extent>
    <rotation>0</rotation>
    <destinationsrs>{_project_crs_xml()}</destinationsrs>
  </mapcanvas>
  <layer-tree-group checked="Qt::Checked" expanded="1" name="">
    {' '.join(tree_rows)}
  </layer-tree-group>
  <projectlayers>
    {' '.join(layer_rows)}
  </projectlayers>
  <properties>
    <GeoFlow>
      <managed type="QString">1</managed>
      <project_id type="QString">{html.escape(project_id)}</project_id>
      <project_code type="QString">{html.escape(project_code)}</project_code>
      <server_url type="QString">{html.escape(server_url)}</server_url>
      <qfield_token type="QString">{html.escape(token)}</qfield_token>
      <roaming_plan_url type="QString">{html.escape(roaming_plan_url)}</roaming_plan_url>
      <roaming_cell_url type="QString">{html.escape(roaming_cell_url)}</roaming_cell_url>
      <movement_threshold_m type="double">100</movement_threshold_m>
    </GeoFlow>
  </properties>
</qgis>
"""


def build_qfield_bootstrap_zip(
    alias: str,
    *,
    project: dict,
    plan: dict[str, Any],
    server_url: str,
    token: str,
    roaming_plan_url: str,
    roaming_cell_url: str,
    project_center: list[float] | None,
) -> tuple[Path, int]:
    gpkg_path, layers = build_empty_qfield_geopackage(
        alias,
        project_id=str(project["id"]),
        plan=plan,
    )
    template_path = Path(settings.BASE_DIR) / "integrations" / "qfield" / "geoflow-field.qml"
    if not template_path.is_file():
        gpkg_path.unlink(missing_ok=True)
        raise RuntimeError("GeoFlow QField project plugin template is missing")

    temp = tempfile.NamedTemporaryFile(
        prefix="geoflow-qfield-package-",
        suffix=".zip",
        delete=False,
    )
    zip_path = Path(temp.name)
    temp.close()
    try:
        qgs = _qgs_xml(
            project=project,
            layers=layers,
            server_url=server_url,
            token=token,
            roaming_plan_url=roaming_plan_url,
            roaming_cell_url=roaming_cell_url,
            project_center=project_center,
        )
        readme = (
            "GeoFlow QField PoC package\n"
            "- geoflow-field.qgs: QField project\n"
            "- geoflow-field.qml: project plugin\n"
            "- geoflow-field.gpkg: local roaming cache\n"
            "The embedded project ticket is short-lived and development-only.\n"
        )
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(gpkg_path, arcname=f"{PROJECT_BASENAME}.gpkg")
            archive.writestr(f"{PROJECT_BASENAME}.qgs", qgs.encode("utf-8"))
            archive.write(template_path, arcname=f"{PROJECT_BASENAME}.qml")
            archive.writestr("README.txt", readme.encode("utf-8"))
        return zip_path, len(layers)
    except Exception:
        try:
            zip_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    finally:
        try:
            gpkg_path.unlink(missing_ok=True)
        except OSError:
            pass
