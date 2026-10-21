"""Read-only QGIS 4 validation against installed GeoFlow cache layers."""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

from qgis.PyQt.QtCore import Qt
from qgis.core import QgsApplication, QgsLayerTreeModel, QgsProject, QgsVectorLayer


PLUGIN_DIR = Path(__file__).resolve().parents[1]
if str(PLUGIN_DIR.parent) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR.parent))

from geoflow_connector.layers.default_style import (  # noqa: E402
    DEFAULT_STYLE_MAP,
    apply_default_qgis_style,
)


def cached_layers() -> dict[str, Path]:
    root = (
        Path(os.environ["APPDATA"])
        / "QGIS"
        / "QGIS4"
        / "GeoFlowConnector"
        / "projects"
    )
    found = {}
    packages = sorted(root.rglob("geoflow-*.gpkg"), key=lambda p: p.stat().st_mtime, reverse=True)
    for package in packages:
        if "_recovery_quarantine_" in str(package):
            continue
        try:
            with sqlite3.connect(f"file:{package.as_posix()}?mode=ro", uri=True) as connection:
                names = {
                    str(row[0]).lower()
                    for row in connection.execute(
                        "SELECT table_name FROM gpkg_contents WHERE data_type='features'"
                    )
                }
        except (OSError, sqlite3.Error):
            continue
        for canonical in DEFAULT_STYLE_MAP:
            if canonical in names and canonical not in found:
                found[canonical] = package
        if len(found) == len(DEFAULT_STYLE_MAP):
            break
    return found


def form_fingerprint(layer) -> tuple:
    config = layer.editFormConfig()
    read_only = tuple(config.readOnly(i) for i in range(len(layer.fields())))
    return (
        config.layout(),
        config.uiForm(),
        config.initFunction(),
        config.initCode(),
        read_only,
    )


app = QgsApplication([], False)
app.initQgis()
failures = []
valve_legend_labels = []
try:
    sources = cached_layers()
    for canonical in DEFAULT_STYLE_MAP:
        package = sources.get(canonical)
        if package is None:
            failures.append(f"{canonical}: cached layer missing")
            print(f"FAIL {canonical}: cached layer missing")
            continue

        layer = QgsVectorLayer(
            f"{package}|layername={canonical}", canonical, "ogr"
        )
        properties = {
            "geoflow/managed": True,
            "geoflow/project_id": package.parent.name,
            "geoflow/standard_name": canonical.upper(),
            "geoflow/physical_name": canonical,
            "geoflow/definition_layer_id": f"runtime-{canonical}",
            "geoflow/package_path": str(package),
            "geoflow/local_editing": True,
            "geoflow/sync_supported": True,
            "geoflow/server_row_count": layer.featureCount(),
        }
        for key, value in properties.items():
            layer.setCustomProperty(key, value)
        form_before = form_fingerprint(layer)
        feature_count = layer.featureCount()

        applied = apply_default_qgis_style(layer, canonical)
        properties_after = {
            key: layer.customProperty(key) for key in properties
        }
        checks = {
            "provider": layer.isValid(),
            "load": applied,
            "renderer": layer.renderer() is not None,
            "labeling": layer.labeling() is not None,
            "form": form_fingerprint(layer) == form_before,
            "properties": properties_after == properties,
        }

        first = next(layer.getFeatures(), None)
        if first is not None:
            layer.selectByIds([first.id()])
            checks["selection"] = layer.selectedFeatureCount() == 1
            layer.removeSelection()
        else:
            checks["selection"] = True

        project = QgsProject.instance()
        project.addMapLayer(layer)
        layer_id = layer.id()
        checks["tree"] = project.mapLayer(layer_id) is layer
        if canonical == "wtl_valv_ps":
            tree_model = QgsLayerTreeModel(project.layerTreeRoot())
            tree_model.setFlags(
                QgsLayerTreeModel.Flag.ShowLegend
                | QgsLayerTreeModel.Flag.ShowLegendAsTree
            )
            node = project.layerTreeRoot().findLayer(layer_id)
            valve_legend_labels = [
                str(item.data(Qt.ItemDataRole.DisplayRole))
                for item in tree_model.layerLegendNodes(node)
            ]
            checks["native_legend"] = len(valve_legend_labels) > 1
            tree_model.deleteLater()
        project.removeMapLayer(layer_id)

        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            failures.append(f"{canonical}: {', '.join(failed)}")
            print(f"FAIL {canonical}: {', '.join(failed)}")
        else:
            print(
                f"PASS {canonical}: {package.name} "
                f"features={feature_count} provider/style/form/selection/tree/properties"
            )

    # Recreate layers after removal to exercise the project-switch/stale-layer path.
    for canonical, package in sources.items():
        reopened = QgsVectorLayer(
            f"{package}|layername={canonical}", f"reopen-{canonical}", "ogr"
        )
        if not reopened.isValid():
            failures.append(f"{canonical}: reopen invalid")
    if not failures:
        print("WTL_VALV_PS_NATIVE_LEGEND=" + repr(valve_legend_labels))
        print("PASS project transition/reopen: no stale layer errors")
    else:
        raise AssertionError("; ".join(failures))
finally:
    QgsProject.instance().removeAllMapLayers()
    app.exitQgis()
