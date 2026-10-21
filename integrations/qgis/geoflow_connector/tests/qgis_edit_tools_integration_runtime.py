"""Exercise edit tools through the real plugin classFactory and main dock."""
import json
import sys
from pathlib import Path
from unittest.mock import Mock

from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.PyQt.QtGui import QAction
from qgis.PyQt.QtWidgets import (
    QApplication, QLabel, QMainWindow, QToolBar, QToolButton,
)
from qgis.core import QgsApplication, QgsFeature, QgsProject, QgsVectorLayer
from qgis.gui import QgsMapCanvas

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from geoflow_connector import classFactory
from geoflow_connector.app.state import State
from geoflow_connector.ui.presentation import PanelMode


APP = QApplication.instance() or QgsApplication([], False)
if isinstance(APP, QgsApplication):
    APP.initQgis()


class Iface(QObject):
    currentLayerChanged = pyqtSignal(object)

    def __init__(self, window, canvas, layer):
        super().__init__()
        self._window, self._canvas, self._layer = window, canvas, layer
        self._message_bar = Mock()
        self.native_save_calls = 0
        self.save_toolbar = QToolBar("save", window)
        window.addToolBar(self.save_toolbar)
        self.save_action = QAction("Save Layer Edits", window)
        self.save_action.setEnabled(True)
        self.save_action.triggered.connect(self._native_save_triggered)
        self.save_toolbar.addAction(self.save_action)

    def _native_save_triggered(self): self.native_save_calls += 1

    def mainWindow(self): return self._window
    def mapCanvas(self): return self._canvas
    def activeLayer(self): return self._layer
    def messageBar(self): return self._message_bar
    def actionSaveActiveLayerEdits(self): return self.save_action
    def addPluginToMenu(self, *_args): pass
    def removePluginMenu(self, *_args): pass
    def addToolBarIcon(self, *_args): pass
    def removeToolBarIcon(self, *_args): pass
    def addDockWidget(self, area, dock): self._window.addDockWidget(area, dock)
    def removeDockWidget(self, dock): self._window.removeDockWidget(dock)


window = QMainWindow()
window.resize(1100, 900)
canvas = QgsMapCanvas(window)
window.setCentralWidget(canvas)
layer = QgsVectorLayer("Point?crs=EPSG:5186&field=id:string", "runtime", "memory")
layer.setCustomProperty("geoflow/managed", True)
layer.setCustomProperty("geoflow/project_id", "project-1")
layer.setCustomProperty("geoflow/package_path", "runtime.gpkg")
layer.setCustomProperty("geoflow/standard_name", "WTL_PIPE_PS")
line_layer = QgsVectorLayer("LineString?crs=EPSG:5186&field=id:string", "runtime-line", "memory")
polygon_layer = QgsVectorLayer("Polygon?crs=EPSG:5186&field=id:string", "runtime-polygon", "memory")
for candidate, standard in (
    (line_layer, "WTL_PIPE_LS"), (polygon_layer, "WTL_BLOCK_PS")
):
    candidate.setCustomProperty("geoflow/managed", True)
    candidate.setCustomProperty("geoflow/project_id", "project-1")
    candidate.setCustomProperty("geoflow/package_path", "runtime.gpkg")
    candidate.setCustomProperty("geoflow/standard_name", standard)
QgsProject.instance().addMapLayers([layer, line_layer, polygon_layer])
iface = Iface(window, canvas, layer)

plugin = classFactory(iface)
plugin.initGui()
plugin._ensure_ui()
assert plugin.editModeButton.objectName() == "editModeButton"
assert plugin.editModeButton.parentWidget() is plugin.presentation.root.rail
assert plugin.edit_tools.palette.parent() is window
assert plugin.edit_tools.panel.parentWidget() is plugin.edit_tools.palette
assert plugin.edit_tools._save_proxy in iface.save_toolbar.actions()
assert iface.save_action not in iface.save_toolbar.actions()

plugin.dialog.client = plugin.active_client = Mock()
plugin.dialog.project_opened = True
plugin.active_context = {
    "project_id": "project-1",
    "package_path": "runtime.gpkg",
    "layer_ids": [layer.id(), line_layer.id(), polygon_layer.id()],
    "sync_supported": True,
    "manifest": {"transport": {
        "write_authorized": True,
        "local_editing_supported": True,
    }},
}
plugin.state_manager.set(State.PROJECT_READY)
plugin.dock.show()
window.show()
APP.processEvents()
assert plugin.presentation.rail.width() == 46
assert plugin.GeoFlowRail_info.parentWidget() is plugin.presentation.root.rail
assert (
    plugin.presentation.root.rail_layout.indexOf(plugin.GeoFlowRail_info) + 1
    == plugin.presentation.root.rail_layout.indexOf(
        plugin.presentation.root.GeoFlowRail_projects
    )
)
assert plugin.stack.currentWidget() is plugin.work
assert not plugin.work.save_button.isVisible()

# The edit entry remains reachable even when the main content is collapsed.
plugin.presentation.set_mode(PanelMode.ICONS)
APP.processEvents()
assert not plugin.presentation.content.isVisible()
assert plugin.editModeButton.isVisible()
assert plugin.editModeButton.isVisibleTo(plugin.dock)
assert plugin.editModeButton.width() > 0 and plugin.editModeButton.height() > 0
assert plugin.editModeButton.text() == ""
assert plugin.editModeButton.toolTip() == "편집 도구"
assert not plugin.editModeButton.icon().isNull()
main_width_before = plugin.dock.width()
main_geometry_before = plugin.dock.geometry()

plugin.editModeButton.click()
APP.processEvents()
assert plugin.editModeButton.isChecked()
assert layer.isEditable()
assert plugin.editModeButton.text() == ""
assert plugin.presentation.mode == PanelMode.ICONS
assert plugin.edit_tools.palette.isVisible()
assert plugin.edit_tools.panel.isVisible()
assert plugin.edit_tools.palette.width() > 0 and plugin.edit_tools.palette.height() > 0
assert plugin.edit_tools.panel.width() > 0 and plugin.edit_tools.panel.height() > 0
assert plugin.dock.width() == main_width_before
assert plugin.dock.geometry() == main_geometry_before
assert plugin.edit_tools.palette.geometry().right() < plugin.dock.geometry().left()
save_feature = QgsFeature(layer.fields())
save_feature["id"] = "90000000-0000-4000-8000-000000000001"
assert layer.addFeature(save_feature)
plugin.work.save_current = Mock(return_value=True)
plugin.edit_tools.refresh()
assert plugin.edit_tools._save_proxy.isEnabled()
plugin.edit_tools._save_proxy.trigger()
assert plugin.work.save_current.call_count == 1
assert iface.native_save_calls == 0
assert plugin._online_save_trigger == "geoflow_save"
assert layer.rollBack()
assert layer.startEditing()

# The separate palette follows the main dock without changing edit mode.
plugin.dock.hide()
APP.processEvents()
assert plugin.editModeButton.isChecked()
assert not plugin.edit_tools.palette.isVisible()
plugin.dock.show()
APP.processEvents()
assert plugin.editModeButton.isChecked()
assert plugin.edit_tools.palette.isVisible()
assert plugin.dock.width() == main_width_before
assert plugin.dock.geometry() == main_geometry_before
button_names = {
    "addFeatureButton", "moveButton", "vertexButton", "splitButton",
    "deleteButton", "snappingButton", "undoButton", "redoButton",
}
panel_buttons = {
    button.objectName(): button
    for button in plugin.edit_tools.panel.findChildren(QToolButton)
}
assert button_names <= set(panel_buttons)
for name in button_names:
    button = panel_buttons[name]
    assert button.isVisibleTo(plugin.edit_tools.palette), name
    assert (button.width(), button.height()) == (32, 32), name
    assert (button.iconSize().width(), button.iconSize().height()) == (22, 22), name
assert plugin.edit_tools.panel.findChildren(QLabel) == []
tool_positions = [panel_buttons[name].y() for name in button_names]
assert len(set(tool_positions)) == len(button_names)
geometry_icons = {}
for geometry_name, candidate in (
    ("point", layer), ("line", line_layer), ("polygon", polygon_layer)
):
    iface._layer = candidate
    canvas.setCurrentLayer(candidate)
    iface.currentLayerChanged.emit(candidate)
    APP.processEvents()
    icon = panel_buttons["addFeatureButton"].icon()
    assert not icon.isNull(), geometry_name
    geometry_icons[geometry_name] = int(icon.cacheKey())
assert len(set(geometry_icons.values())) == 3, geometry_icons
iface._layer = layer
canvas.setCurrentLayer(layer)
iface.currentLayerChanged.emit(layer)
APP.processEvents()
runtime_shape = {
    "navigation_width": plugin.presentation.rail.width(),
    "button": [plugin.editModeButton.x(), plugin.editModeButton.y(),
               plugin.editModeButton.width(), plugin.editModeButton.height()],
    "palette": [plugin.edit_tools.palette.x(), plugin.edit_tools.palette.y(),
                plugin.edit_tools.palette.width(), plugin.edit_tools.palette.height()],
    "panel": [plugin.edit_tools.panel.x(), plugin.edit_tools.panel.y(),
              plugin.edit_tools.panel.width(), plugin.edit_tools.panel.height()],
    "button_visible_to_dock": plugin.editModeButton.isVisibleTo(plugin.dock),
    "button_parent": plugin.editModeButton.parentWidget().objectName(),
    "button_size_hint": [plugin.editModeButton.sizeHint().width(),
                         plugin.editModeButton.sizeHint().height()],
    "button_text_width": plugin.editModeButton.fontMetrics().horizontalAdvance(
        plugin.editModeButton.text()
    ),
    "tool_button_size": [32, 32],
    "tool_icon_size": [22, 22],
    "geometry_icon_keys": geometry_icons,
}

plugin.editModeButton.click()
APP.processEvents()
assert plugin.editModeButton.text() == ""
assert not plugin.edit_tools.palette.isVisible()
assert not plugin.edit_tools.panel.isVisible()
plugin.unload()
assert iface.save_action in iface.save_toolbar.actions()
QgsProject.instance().removeMapLayers([
    layer.id(), line_layer.id(), polygon_layer.id()
])
window.close()
print("EDIT_TOOLS_RUNTIME=" + json.dumps(runtime_shape, sort_keys=True))
print("qgis edit tools classFactory integration: OK")
