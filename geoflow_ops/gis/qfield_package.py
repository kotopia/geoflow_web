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
    _copy_layer_rows,
    _create_feature_table,
    _init_gpkg,
    _layer_specs,
)


QFIELD_PACKAGE_VERSION = "1.0"
QFIELD_PLUGIN_RUNTIME_VERSION = "0.9.13"
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
        <srsid>3452</srsid><srid>4326</srid><authid>EPSG:4326</authid>
        <description>WGS 84</description><projectionacronym>longlat</projectionacronym>
        <ellipsoidacronym>EPSG:7030</ellipsoidacronym><geographicflag>true</geographicflag>
      </spatialrefsys>
    """.strip()


def _apply_qfield_qml_property_compat(text: str) -> str:
    replacements: tuple[tuple[str, str], ...] = (
        (
            '''            let fields = layer.fields()\n            for (let i = 0; i < fields.count(); i++) {\n                let name = String(fields.at(i).name())''',
            '''            let fields = layer.fields\n            let names = fields.names || []\n            for (let i = 0; i < names.length; i++) {\n                let name = String(names[i])''',
        ),
        (
            'try { return String(layer.fields().at(Number(index)).name()) } catch (err) {}',
            'try { let names = layer.fields.names || []; let idx = Number(index); return idx >= 0 && idx < names.length ? String(names[idx]) : "" } catch (err) {}',
        ),
        ('let fields = layer.fields()', 'let fields = layer.fields'),
        ('let fields = binding.layer.fields()', 'let fields = binding.layer.fields'),
        ('binding.layer.fields().indexOf(', 'binding.layer.fields.indexOf('),
        ('let geometry = feature.geometry()', 'let geometry = feature.geometry'),
        ('binding.fidMap[String(feature.id())]', 'binding.fidMap[String(feature.id)]'),
        ('binding.versionMap[String(feature.id())]', 'binding.versionMap[String(feature.id)]'),
        ('if (!geometry || geometry.isNull() || geometry.isEmpty()) return ""', 'if (!geometry || geometry.isNull) return ""'),
        ('if (geometry && !geometry.isNull() && !geometry.isEmpty()) wkt = String(geometry.asWkt(8))', 'if (geometry && !geometry.isNull) wkt = String(geometry.asWkt(8))'),
        ('if (!geometry || geometry.isNull() || geometry.isEmpty()) continue', 'if (!geometry || geometry.isNull) continue'),
        ('return [e.xMinimum(), e.yMinimum(), e.xMaximum(), e.yMaximum()].join(",")', 'return [e.xMinimum, e.yMinimum, e.xMaximum, e.yMaximum].join(",")'),
        ('try { return String(layer.name()) } catch (err2) {}', 'try { return String(layer.name || "") } catch (err2) {}'),
    )
    for old, new in replacements:
        if old not in text:
            raise RuntimeError(f"QField 4.2 property compatibility marker missing: {old[:80]!r}")
        text = text.replace(old, new)
    forbidden = (
        "layer.fields()", "binding.layer.fields()", "feature.geometry()", "feature.id()",
        "geometry.isNull()", "e.xMinimum()", "e.yMinimum()", "e.xMaximum()", "e.yMaximum()",
    )
    remaining = [marker for marker in forbidden if marker in text]
    if remaining:
        raise RuntimeError("QField 4.2 property compatibility rewrite incomplete: " + ", ".join(remaining))
    return text


def _render_qfield_plugin(template_path: Path) -> str:
    text = template_path.read_text(encoding="utf-8")
    required_markers = (
        "GeoFlow Field 0.9.4",
        "function pollForLocalChanges(force)",
        "function resetRoamingStateForFreshTicket()",
        "Never infer deletes from iterator absence",
        "function manualSync()",
    )
    missing = [marker for marker in required_markers if marker not in text]
    if missing:
        raise RuntimeError("GeoFlow QField plugin template is not the reviewed 0.9.4 baseline: " + ", ".join(missing))

    property_marker = "    property bool pollingBaselineReady: false\n"
    if property_marker not in text:
        raise RuntimeError("QField polling property marker disappeared")
    text = text.replace(property_marker, property_marker + '    property string lastEditedStandard: ""\n' + "    property int lastEditedFid: -1\n", 1)

    remember_edit = r'''
    function rememberEditedFeature(binding, fid) {
        if (!binding) return
        lastEditedStandard = String(binding.standard || "")
        lastEditedFid = Number(fid)
        log("edited feature observed " + lastEditedStandard + " fid=" + lastEditedFid)
    }

    function lastEditedBinding() {
        if (!lastEditedStandard || lastEditedFid < 0) return null
        for (let i = 0; i < layerBindings.length; i++) {
            let binding = layerBindings[i]
            if (String(binding.standard || "") === lastEditedStandard) return binding
        }
        return null
    }

'''
    unbind_marker = "    function unbindLayers() {"
    if unbind_marker not in text:
        raise RuntimeError("QField unbind marker disappeared")
    text = text.replace(unbind_marker, remember_edit + unbind_marker, 1)

    binding_replacements = (
        ('binding.added = function(fid) { geoflowField.captureCreate(binding, fid) }', 'binding.added = function(fid) { geoflowField.rememberEditedFeature(binding, fid); geoflowField.captureCreate(binding, fid) }'),
        ('binding.attribute = function(fid, index, value) { geoflowField.captureAttribute(binding, fid, index, value) }', 'binding.attribute = function(fid, index, value) { geoflowField.rememberEditedFeature(binding, fid); geoflowField.captureAttribute(binding, fid, index, value) }'),
        ('binding.geometry = function(fid, geometry) { geoflowField.captureGeometry(binding, fid, geometry) }', 'binding.geometry = function(fid, geometry) { geoflowField.rememberEditedFeature(binding, fid); geoflowField.captureGeometry(binding, fid, geometry) }'),
    )
    for old, new in binding_replacements:
        if old not in text:
            raise RuntimeError("QField edit listener marker disappeared")
        text = text.replace(old, new, 1)

    forced_capture = r'''
    function captureFocusedFeatureForManualSync() {
        let form = null
        try { form = iface.findItemByObjectName("featureForm") } catch (err) {}
        let layer = null
        let feature = null
        if (form && form.selection) {
            try { layer = form.selection.focusedLayer } catch (err2) {}
            try { feature = form.selection.focusedFeature } catch (err3) {}
        }
        if (!layer || !feature) {
            let binding = lastEditedBinding()
            if (binding) {
                layer = binding.layer
                feature = featureByFid(layer, lastEditedFid)
                if (feature) log("manual sync using last edited feature " + binding.standard + " fid=" + lastEditedFid)
            }
        }
        if (!layer || !feature) {
            log("manual focused capture unavailable: no focused or last edited feature")
            return false
        }
        let standard = standardNameForPhysical(layerName(layer))
        let objectId = canonicalUuid(feature.attribute("id"))
        if (!standard || !objectId) {
            log("manual focused capture skipped: GeoFlow identity missing")
            return false
        }
        let key = pendingKey(standard, objectId)
        let old = pollingBaseline[key]
        let geometryWkt = featureGeometryWkt(feature)
        let change = {action: "update", layer: standard, id: objectId, attributes: collectAttributes(layer, feature)}
        if (geometryWkt) change.geometry_wkt = geometryWkt
        if (old && old.base_updated_at) change.base_updated_at = old.base_updated_at
        queueChange(change)
        log("manual focused feature queued " + standard + " " + objectId)
        return true
    }

'''
    marker = "    function manualSync() {"
    if marker not in text:
        raise RuntimeError("QField manualSync marker disappeared")
    text = text.replace(marker, forced_capture + marker, 1)

    old_manual = '''    function manualSync() {
        authBlocked = false
        log("manual sync requested")
        pollForLocalChanges(true)
        syncNow(true, true)
        scheduleRoaming(true)
    }'''
    new_manual = '''    function manualSync() {
        authBlocked = false
        log("manual sync requested")
        let forced = captureFocusedFeatureForManualSync()
        pollForLocalChanges(true)
        if (!forced) log("manual sync continuing without focused feature fallback")
        syncNow(true, true)
        scheduleRoaming(true)
    }'''
    if old_manual not in text:
        raise RuntimeError("QField reviewed manualSync body disappeared")
    text = text.replace(old_manual, new_manual, 1)

    error_log_marker = '                log("HTTP " + xhr.status + " " + url + (serverMessage ? " " + serverMessage : ""))'
    retry_reset = '''                log("HTTP " + xhr.status + " " + url + (serverMessage ? " " + serverMessage : ""))
                if (xhr.status >= 500) {
                    lastViewport = ""
                    lastLon = NaN
                    lastLat = NaN
                    log("server read unavailable; roaming will retry on next timer")
                }'''
    if error_log_marker not in text:
        raise RuntimeError("QField authGet error marker disappeared")
    text = text.replace(error_log_marker, retry_reset, 1)

    text = _apply_qfield_qml_property_compat(text)
    text = text.replace("GeoFlow Field 0.9.4", f"GeoFlow Field {QFIELD_PLUGIN_RUNTIME_VERSION}")
    text = text.replace("plugin 0.9.4 component completed", f"plugin {QFIELD_PLUGIN_RUNTIME_VERSION} component completed")
    return text


def build_qfield_geopackage(alias: str, *, project_id: str, plan: dict[str, Any]) -> tuple[Path, list[dict[str, Any]]]:
    specs = _layer_specs(alias, plan)
    if not specs:
        raise ValueError("project Layer Plan is empty")
    temp = tempfile.NamedTemporaryFile(prefix="geoflow-qfield-seed-", suffix=".gpkg", delete=False)
    path = Path(temp.name)
    temp.close()
    layer_meta = []
    try:
        conn = sqlite3.connect(str(path))
        try:
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.execute("PRAGMA cache_size=-65536")
            _init_gpkg(conn)
            profile = plan.get("profile") or {}
            conn.executemany(
                "INSERT INTO _geoflow_package(key,value) VALUES (?,?)",
                [
                    ("package_version", "0.9"),
                    ("package_id", str(uuid.uuid4())),
                    ("project_id", str(uuid.UUID(str(project_id)))),
                    ("profile_id", str(profile.get("id") or "")),
                    ("profile_code", str(profile.get("code") or "")),
                    ("generated_at", dt.datetime.now(dt.timezone.utc).isoformat()),
                    ("qfield_package_version", QFIELD_PACKAGE_VERSION),
                    ("qfield_plugin_runtime_version", QFIELD_PLUGIN_RUNTIME_VERSION),
                    ("bootstrap_mode", "project_snapshot_then_delta"),
                    ("spatial_index", "gpkg_rtree_index"),
                ],
            )
            conn.executescript(
                """
                CREATE TABLE _geoflow_qfield_cell (cell_key TEXT PRIMARY KEY, priority TEXT NOT NULL DEFAULT 'prefetch', fetched_at TEXT NOT NULL, last_used_at TEXT NOT NULL, complete INTEGER NOT NULL DEFAULT 1, dirty INTEGER NOT NULL DEFAULT 0, pending INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE _geoflow_qfield_object_cell (layer_name TEXT NOT NULL, object_id TEXT NOT NULL, cell_key TEXT NOT NULL, PRIMARY KEY(layer_name, object_id, cell_key));
                CREATE TABLE _geoflow_pending_change (layer_name TEXT NOT NULL, object_id TEXT NOT NULL, action TEXT NOT NULL, attributes_json TEXT NOT NULL DEFAULT '{}', geometry_wkb TEXT, updated_at TEXT NOT NULL, PRIMARY KEY(layer_name, object_id));
                CREATE TABLE _geoflow_outbox (seq INTEGER PRIMARY KEY AUTOINCREMENT, changeset_id TEXT NOT NULL UNIQUE, client_id TEXT NOT NULL, base_revision INTEGER NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL);
                """
            )
            for spec in specs:
                _create_feature_table(conn, spec)
                count = _copy_layer_rows(alias, conn, spec, str(project_id))
                layer_meta.append({
                    "standard_name": spec.standard_name,
                    "physical_name": spec.physical_name,
                    "label": spec.label,
                    "domain": spec.domain,
                    "geometry_kind": spec.geometry_kind,
                    "row_count": count,
                    "spatial_index": "rtree",
                    "fields": [{"name": f.name, "data_type": f.data_type, "editable": f.editable, "visible": f.visible, "sort_order": f.sort_order} for f in spec.fields],
                })
            conn.commit()
        finally:
            conn.close()
        return path, layer_meta
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _qgs_xml(*, project: dict, layers: list[dict[str, Any]], server_url: str, token: str, roaming_plan_url: str, roaming_cell_url: str, project_center: list[float] | None) -> str:
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
        tree_rows.append(f'<layer-tree-layer providerKey="ogr" source="./geoflow-field.gpkg|layername={html.escape(physical)}" checked="Qt::Checked" expanded="1" name="{html.escape(label)}" id="{layer_id}"/>')
        layer_rows.append(f"""
    <maplayer type="vector" geometry="{_geometry_name(layer.get('geometry_kind'))}" simplifyDrawingHints="1" simplifyAlgorithm="0" simplifyLocal="1" readOnly="0">
      <extent><xmin>{minx}</xmin><ymin>{miny}</ymin><xmax>{maxx}</xmax><ymax>{maxy}</ymax></extent>
      <id>{layer_id}</id><datasource>./geoflow-field.gpkg|layername={html.escape(physical)}</datasource>
      <keywordList><value></value></keywordList><layername>{html.escape(physical)}</layername>
      <srs>{_project_crs_xml()}</srs><provider encoding="UTF-8">ogr</provider>
      <customproperties><Option type="Map"><Option name="geoflow/project_id" value="{html.escape(project_id)}" type="QString"/><Option name="geoflow/physical_name" value="{html.escape(physical)}" type="QString"/></Option></customproperties>
    </maplayer>""".strip())
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<qgis projectname="{html.escape(project_code)}" version="3.40.0">
  <homePath path="."/><title>{html.escape(project_name)}</title><autotransaction active="0"/><evaluateDefaultValues active="1"/>
  <projectCrs>{_project_crs_xml()}</projectCrs>
  <mapcanvas name="theMapCanvas"><units>degrees</units><extent><xmin>{minx}</xmin><ymin>{miny}</ymin><xmax>{maxx}</xmax><ymax>{maxy}</ymax></extent><rotation>0</rotation><destinationsrs>{_project_crs_xml()}</destinationsrs></mapcanvas>
  <layer-tree-group checked="Qt::Checked" expanded="1" name="">{' '.join(tree_rows)}</layer-tree-group>
  <projectlayers>{' '.join(layer_rows)}</projectlayers>
  <properties><GeoFlow>
      <managed type="QString">1</managed><project_id type="QString">{html.escape(project_id)}</project_id><project_code type="QString">{html.escape(project_code)}</project_code>
      <server_url type="QString">{html.escape(server_url)}</server_url><qfield_token type="QString">{html.escape(token)}</qfield_token>
      <roaming_plan_url type="QString">{html.escape(roaming_plan_url)}</roaming_plan_url><roaming_cell_url type="QString">{html.escape(roaming_cell_url)}</roaming_cell_url>
      <movement_threshold_m type="double">100</movement_threshold_m>
    </GeoFlow></properties>
</qgis>"""


def build_qfield_bootstrap_zip(alias: str, *, project: dict, plan: dict[str, Any], server_url: str, token: str, roaming_plan_url: str, roaming_cell_url: str, project_center: list[float] | None) -> tuple[Path, int]:
    gpkg_path, layers = build_qfield_geopackage(alias, project_id=str(project["id"]), plan=plan)
    template_path = Path(settings.BASE_DIR) / "integrations" / "qfield" / "geoflow-field.qml"
    if not template_path.is_file():
        gpkg_path.unlink(missing_ok=True)
        raise RuntimeError("GeoFlow QField project plugin template is missing")
    temp = tempfile.NamedTemporaryFile(prefix="geoflow-qfield-package-", suffix=".zip", delete=False)
    zip_path = Path(temp.name)
    temp.close()
    try:
        qgs = _qgs_xml(project=project, layers=layers, server_url=server_url, token=token, roaming_plan_url=roaming_plan_url, roaming_cell_url=roaming_cell_url, project_center=project_center)
        qml = _render_qfield_plugin(template_path)
        readme = (
            "GeoFlow QField package\n"
            "- geoflow-field.qgs: persistent QField project\n"
            "- geoflow-field.qml: GeoFlow sync plugin\n"
            "- geoflow-field.gpkg: initial full project snapshot\n"
            f"- package: {QFIELD_PACKAGE_VERSION}\n- plugin runtime: {QFIELD_PLUGIN_RUNTIME_VERSION}\n"
            "After first install, server-to-device synchronization uses revision Delta.\n"
        )
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(gpkg_path, arcname=f"{PROJECT_BASENAME}.gpkg")
            archive.writestr(f"{PROJECT_BASENAME}.qgs", qgs.encode("utf-8"))
            archive.writestr(f"{PROJECT_BASENAME}.qml", qml.encode("utf-8"))
            archive.writestr("README.txt", readme.encode("utf-8"))
        return zip_path, len(layers)
    except Exception:
        zip_path.unlink(missing_ok=True)
        raise
    finally:
        gpkg_path.unlink(missing_ok=True)
