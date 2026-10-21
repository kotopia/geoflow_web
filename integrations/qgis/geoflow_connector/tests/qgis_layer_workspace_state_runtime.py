"""End-to-end native layer-tree signals with the real workspace state."""
import json
import sys
from pathlib import Path

from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.core import (
    QgsApplication,
    QgsCategorizedSymbolRenderer,
    QgsFeature,
    QgsMarkerSymbol,
    QgsProject,
    QgsRendererCategory,
    QgsVectorLayer,
    Qgis,
)
from qgis.gui import QgsLayerTreeView

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from geoflow_connector.layers.selection import LayerWorkspaceState
from geoflow_connector.ui.layer_workspace import GeoFlowLayerWorkspace


APP = QgsApplication.instance() or QgsApplication([], False)
if isinstance(APP, QgsApplication):
    APP.initQgis()


class Events(QObject):
    changed = pyqtSignal()


class Iface(QObject):
    currentLayerChanged = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self._active = None

    def mainWindow(self):
        return self

    def activeLayer(self):
        return self._active

    def setActiveLayer(self, layer):
        self._active = layer
        self.currentLayerChanged.emit(layer)

    def mapCanvas(self):
        return self

    def refresh(self):
        pass


class Plugin:
    def __init__(self, layers):
        self.iface = Iface()
        self.integration_events = Events()
        self.active_context = {
            "project_id": "state-project",
            "manifest": {"layers": [
                {"standard_name": "WTL_VALV_PS", "label": "변류시설", "domain": "WTL"},
            ]},
        }
        self._layers = layers
        self._workspace_model = LayerWorkspaceState(self)

    def integration_state(self):
        return {
            "epoch": 1,
            "project_id": "state-project",
            "ready": True,
            "layers": tuple(self._layers),
        }


project = QgsProject.instance()
project.clear()
group = project.layerTreeRoot().addGroup("GeoFlow · STATE")
group.setCustomProperty("geoflow/context_owner", "state-project")
domain = group.addGroup("상수")
layer = QgsVectorLayer("Point?field=FTR_CDE:string", "변류시설", "memory")
for key, value in {
    "geoflow/managed": True,
    "geoflow/project_id": "state-project",
    "geoflow/standard_name": "WTL_VALV_PS",
    "geoflow/physical_name": "wtl_valv_ps",
}.items():
    layer.setCustomProperty(key, value)
features = []
for code in ("SA100", "SA200", "SA300"):
    feature = QgsFeature(layer.fields())
    feature["FTR_CDE"] = code
    features.append(feature)
layer.dataProvider().addFeatures(features)
layer.setRenderer(QgsCategorizedSymbolRenderer("FTR_CDE", [
    QgsRendererCategory("SA100", QgsMarkerSymbol.createSimple({"color": "255,0,0"}), "제수변"),
    QgsRendererCategory("SA200", QgsMarkerSymbol.createSimple({"color": "0,0,255"}), "공기변"),
]))
project.addMapLayer(layer, False)
domain.addLayer(layer)

plugin = Plugin([layer])
workspace = GeoFlowLayerWorkspace(plugin)
workspace.set_project(plugin.active_context["manifest"])
workspace.show()
APP.processEvents()

assert isinstance(workspace.tree, QgsLayerTreeView)
assert workspace.tree.feature_count(layer.id()) == 3

# A layer row click changes the active layer but never the feature selection.
workspace.tree.setCurrentLayer(layer)
APP.processEvents()
assert plugin.iface.activeLayer() is layer
assert layer.selectedFeatureCount() == 0

# QGIS-native pending delete immediately changes featureCount and the cached
# presentation count; rollback restores it.
layer.startEditing()
layer.deleteFeature(next(layer.getFeatures()).id())
APP.processEvents()
assert layer.featureCount() == 2
assert workspace.tree.feature_count(layer.id()) == 2
layer.rollBack()
APP.processEvents()
assert workspace.tree.feature_count(layer.id()) == 3
rollback_count = workspace.tree.feature_count(layer.id())

layer.startEditing()
for feature_id in list(layer.allFeatureIds()):
    layer.deleteFeature(feature_id)
APP.processEvents()
assert workspace.tree.feature_count(layer.id()) == 0
assert layer.commitChanges(False)
APP.processEvents()
assert workspace.tree.feature_count(layer.id()) == 0

# Renderer signals flow through LayerWorkspaceState and rebuild native legend.
layer.setRenderer(QgsCategorizedSymbolRenderer("FTR_CDE", [
    QgsRendererCategory("SA100", QgsMarkerSymbol.createSimple({"color": "0,255,0"}), "제수변 실시간"),
]))
APP.processEvents()
node = project.layerTreeRoot().findLayer(layer.id())
labels = [str(item.data(0)) for item in workspace.tree.native_model.layerLegendNodes(node)]
assert labels == ["제수변 실시간"], labels

# A visibility change made outside GeoFlow is read from the same QGIS node.
node.setItemVisibilityChecked(False)
APP.processEvents()
assert not node.isVisible()
node.setItemVisibilityChecked(True)
APP.processEvents()
assert node.isVisible()

print("qgis layer workspace state runtime: " + json.dumps({
    "qgis_version": Qgis.QGIS_VERSION,
    "count_initial": 3,
    "count_pending_delete": 2,
    "count_rollback": rollback_count,
    "count_multi_delete_commit": 0,
    "legend": labels,
    "visibility_bidirectional": node.isVisible(),
    "feature_selection_unchanged": layer.selectedFeatureCount() == 0,
}, ensure_ascii=False))

workspace.shutdown()
workspace.close()
plugin._workspace_model.close()
project.clear()
