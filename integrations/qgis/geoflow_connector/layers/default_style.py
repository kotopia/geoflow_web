"""Apply the bundled GeoFlow QML defaults without importing layer metadata."""
from __future__ import annotations

from pathlib import Path

from qgis.core import QgsMapLayer, QgsMapLayerStyle, QgsMessageLog, Qgis


DEFAULT_STYLE_MAP = {
    "wtl_etc_ps": "wtl_etc_ps.qml",
    "wtl_fire_ps": "wtl_fire_ps.qml",
    "wtl_flow_ps": "wtl_flow_ps.qml",
    "wtl_pipe_lm": "wtl_pipe_lm.qml",
    "wtl_pipe_ps": "wtl_pipe_ps.qml",
    "wtl_valv_ps": "wtl_valv_ps.qml",
    "survey": "survey.qml",
}

DEFAULT_STYLE_APPLIED_PROPERTY = "geoflow/default_style_applied"
STYLE_DIRECTORY = (
    Path(__file__).resolve().parent.parent / "resources" / "styles" / "qgis_style"
)


def _log(message: str, level) -> None:
    QgsMessageLog.logMessage(f"[STYLE] {message}", "GeoFlow", level)


def _geoflow_properties(layer) -> dict:
    """Snapshot every existing GeoFlow property, including future keys."""
    try:
        keys = layer.customPropertyKeys()
    except Exception:
        keys = ()
    return {
        str(key): layer.customProperty(key)
        for key in keys
        if str(key).startswith("geoflow/")
    }


def _restore_geoflow_properties(layer, before: dict) -> None:
    """Undo additions/removals/changes made by a style loader."""
    try:
        current_keys = tuple(layer.customPropertyKeys())
    except Exception:
        current_keys = ()
    for key in current_keys:
        key = str(key)
        if key.startswith("geoflow/") and key not in before:
            layer.removeCustomProperty(key)
    for key, value in before.items():
        if layer.customProperty(key) != value:
            layer.setCustomProperty(key, value)


def apply_default_qgis_style(layer, canonical_name: str) -> bool:
    """Apply a bundled visual default once to a newly materialized layer.

    Only QGIS visual style categories are loaded. Fields, forms, actions,
    relations, custom properties and other runtime metadata in a QML file are
    deliberately excluded. Failures are logged and never abort project load.
    """
    canonical = str(canonical_name or "").strip().lower()
    qml_name = DEFAULT_STYLE_MAP.get(canonical)
    if not qml_name:
        return False

    if bool(layer.customProperty(DEFAULT_STYLE_APPLIED_PROPERTY, False)):
        _log(f"skipped existing user style -> {canonical}", Qgis.MessageLevel.Info)
        return False

    qml_path = STYLE_DIRECTORY / qml_name
    if not qml_path.is_file():
        _log(f"qml missing -> {canonical} ({qml_path})", Qgis.MessageLevel.Warning)
        return False

    protected = _geoflow_properties(layer)
    previous_style = QgsMapLayerStyle()
    previous_style.readFromLayer(layer)
    try:
        categories = QgsMapLayer.StyleCategory.AllVisualStyleCategories
        # Use a keyword here: the positional overload also accepts a bool as
        # its second argument and would silently load every QML category.
        message, ok = layer.loadNamedStyle(str(qml_path), categories=categories)
        _restore_geoflow_properties(layer, protected)
        if _geoflow_properties(layer) != protected:
            raise RuntimeError("GeoFlow custom properties could not be restored")
        if not ok:
            raise RuntimeError(str(message or "QGIS rejected the QML style"))
        layer.setCustomProperty(DEFAULT_STYLE_APPLIED_PROPERTY, True)
        layer.triggerRepaint()
        _log(f"applied qgis_style/{qml_name} -> {canonical}", Qgis.MessageLevel.Info)
        return True
    except Exception as exc:
        try:
            previous_style.writeToLayer(layer)
        finally:
            _restore_geoflow_properties(layer, protected)
        _log(
            f"failed -> {canonical}: {type(exc).__name__}: {exc}",
            Qgis.MessageLevel.Warning,
        )
        return False
