"""QGIS 4 runtime coverage for bundled GeoFlow default styles."""
from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from qgis.core import (
    QgsApplication,
    QgsFillSymbol,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsProject,
    QgsSingleSymbolRenderer,
    QgsVectorLayer,
)


PLUGIN_DIR = Path(__file__).resolve().parents[1]
PACKAGE_PARENT = PLUGIN_DIR.parent
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

from geoflow_connector.layers.default_style import (  # noqa: E402
    DEFAULT_STYLE_APPLIED_PROPERTY,
    DEFAULT_STYLE_MAP,
    STYLE_DIRECTORY,
    apply_default_qgis_style,
)


app = QgsApplication([], False)
app.initQgis()

GEOMETRIES = {
    "wtl_pipe_lm": "LineString",
}
PROPERTIES = {
    "geoflow/managed": True,
    "geoflow/project_id": "runtime-project",
    "geoflow/standard_name": "",
    "geoflow/physical_name": "",
    "geoflow/definition_layer_id": "runtime-definition",
    "geoflow/package_path": "runtime.gpkg",
    "geoflow/local_editing": True,
    "geoflow/sync_supported": True,
    "geoflow/server_row_count": 0,
}

failures = []
try:
    for canonical, qml_name in DEFAULT_STYLE_MAP.items():
        geometry = GEOMETRIES.get(canonical, "Point")
        layer = QgsVectorLayer(f"{geometry}?crs=EPSG:5186", canonical, "memory")
        expected = dict(PROPERTIES)
        expected["geoflow/standard_name"] = canonical.upper()
        expected["geoflow/physical_name"] = canonical
        for key, value in expected.items():
            layer.setCustomProperty(key, value)

        applied = apply_default_qgis_style(layer, canonical.upper())
        actual = {key: layer.customProperty(key) for key in expected}
        checks = {
            "qml": (STYLE_DIRECTORY / qml_name).is_file(),
            "load": applied,
            "renderer": layer.renderer() is not None,
            "labeling": layer.labeling() is not None,
            "properties": actual == expected,
            "marker": bool(layer.customProperty(DEFAULT_STYLE_APPLIED_PROPERTY, False)),
        }
        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            failures.append(f"{canonical}: {', '.join(failed)}")
            print(f"FAIL {canonical}: {', '.join(failed)}")
        else:
            print(f"PASS {canonical}: qml/load/renderer/labeling/properties")

        # A second call represents refresh/reuse. It must preserve a user's
        # explicit renderer instead of restoring the bundled default.
        if geometry == "LineString":
            symbol = QgsLineSymbol.createSimple({"color": "1,2,3"})
        elif geometry == "Polygon":
            symbol = QgsFillSymbol.createSimple({"color": "1,2,3"})
        else:
            symbol = QgsMarkerSymbol.createSimple({"color": "1,2,3"})
        user_renderer = QgsSingleSymbolRenderer(symbol)
        layer.setRenderer(user_renderer)
        reapplied = apply_default_qgis_style(layer, canonical)
        if reapplied or layer.renderer() is not user_renderer:
            failures.append(f"{canonical}: user style overwritten")
            print(f"FAIL {canonical}: user style overwritten")

    other = QgsVectorLayer("Point", "other", "memory")
    if apply_default_qgis_style(other, "road_test_ps"):
        failures.append("unmapped layer styled")

    # A project-saved user renderer and the applied marker must survive reopen.
    project = QgsProject.instance()
    persisted = QgsVectorLayer("Point?crs=EPSG:5186", "persisted", "memory")
    persisted.setCustomProperty("geoflow/standard_name", "WTL_PIPE_PS")
    if not apply_default_qgis_style(persisted, "WTL_PIPE_PS"):
        failures.append("project persistence: initial default failed")
    persisted.setRenderer(
        QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple({"color": "9,8,7"}))
    )
    project.addMapLayer(persisted)
    with TemporaryDirectory() as temporary:
        project_path = str(Path(temporary) / "style-preservation.qgz")
        if not project.write(project_path):
            failures.append("project persistence: write failed")
        project.clear()
        if not project.read(project_path):
            failures.append("project persistence: read failed")
        else:
            restored = next(iter(project.mapLayers().values()), None)
            color_before = restored.renderer().symbol().color().name() if restored else ""
            reapplied = apply_default_qgis_style(restored, "WTL_PIPE_PS") if restored else True
            color_after = restored.renderer().symbol().color().name() if restored else ""
            if reapplied or color_before != color_after:
                failures.append("project persistence: user style overwritten")
    project.clear()

    if failures:
        raise AssertionError("; ".join(failures))
    print("PASS user-style preservation, project reopen, and unmapped-layer skip")
finally:
    app.exitQgis()
