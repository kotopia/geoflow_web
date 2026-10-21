"""QGIS 4.2.2 runtime proof for the native GeoFlow layer tree."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from qgis.PyQt.QtCore import QObject, Qt, pyqtSignal
from qgis.PyQt.QtWidgets import QStyleOptionViewItem
from qgis.core import (
    QgsApplication,
    QgsCategorizedSymbolRenderer,
    QgsFeature,
    QgsLayerTreeGroup,
    QgsLayerTreeLayer,
    QgsLayerTreeModel,
    QgsMarkerSymbol,
    QgsProject,
    Qgis,
    QgsRendererCategory,
    QgsVectorLayer,
)
from qgis.gui import QgsLayerTreeView

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from geoflow_connector.ui.native_layer_tree import GeoFlowNativeLayerTree
from geoflow_connector.ui.layer_workspace import GeoFlowLayerWorkspace


APP = QgsApplication.instance() or QgsApplication([], False)
if isinstance(APP, QgsApplication):
    APP.initQgis()


class State(QObject):
    rowsChanged = pyqtSignal()
    selectionChanged = pyqtSignal(str)
    revealRequested = pyqtSignal(str)
    visibilityChanged = pyqtSignal()
    symbologyChanged = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.selected = []
        self.rows = []
        self._layers = {}

    def select_layer(self, layer_id, **_kwargs):
        self.selected.append(layer_id)
        return True

    def refresh(self):
        self.rowsChanged.emit()

    def layers(self):
        return dict(self._layers)


class Canvas:
    def refresh(self):
        pass


project = QgsProject.instance()
project.clear()
state = State()
plugin = SimpleNamespace(
    _workspace_model=state,
    active_context={"project_id": "native-tree-project"},
    iface=SimpleNamespace(mapCanvas=lambda: Canvas()),
)

outer = project.layerTreeRoot().addGroup("GeoFlow · TEST")
outer.setCustomProperty("geoflow/context_owner", "native-tree-project")
water = outer.addGroup("상수")


def layer(name, standard, managed=True, count=0):
    result = QgsVectorLayer("Point?field=FTR_CDE:string", name, "memory")
    result.setCustomProperty("geoflow/managed", managed)
    result.setCustomProperty("geoflow/project_id", "native-tree-project")
    result.setCustomProperty("geoflow/standard_name", standard)
    result.setCustomProperty("geoflow/physical_name", standard.lower())
    features = []
    for index in range(count):
        feature = QgsFeature(result.fields())
        feature["FTR_CDE"] = "SA100" if index % 2 == 0 else "SA200"
        features.append(feature)
    result.dataProvider().addFeatures(features)
    project.addMapLayer(result, False)
    water.addLayer(result)
    return result


valve = layer("변류시설", "WTL_VALV_PS", count=3)
pipe = layer("상수관로", "WTL_PIPE_LM", count=2)
foreign = layer("임시 레이어", "TEMP", managed=False, count=1)
state._layers = {item.id(): item for item in (valve, pipe)}
state.rows = [
    {"layer_id": valve.id(), "row_count": 3},
    {"layer_id": pipe.id(), "row_count": 2},
]

categories = [
    QgsRendererCategory("SA100", QgsMarkerSymbol.createSimple({"color": "255,0,0"}), "제수변"),
    QgsRendererCategory("SA200", QgsMarkerSymbol.createSimple({"color": "0,0,255"}), "공기변"),
]
valve.setRenderer(QgsCategorizedSymbolRenderer("FTR_CDE", categories))

tree = GeoFlowNativeLayerTree(plugin)
tree.resize(420, 600)
tree.install_project_model()
tree.set_counts([
    {"layer_id": valve.id(), "row_count": 3},
    {"layer_id": pipe.id(), "row_count": 2},
])
tree.show()
APP.processEvents()
tree.refresh_presentation()
APP.processEvents()

assert isinstance(tree, QgsLayerTreeView)
assert isinstance(tree.native_model, QgsLayerTreeModel)
assert tree.native_model.rootGroup() is project.layerTreeRoot()
assert tree.native_model.testFlag(QgsLayerTreeModel.Flag.ShowLegend)
assert tree.node_for_index(tree.rootIndex()) is outer

valve_node = outer.findLayer(valve.id())
valve_source = tree.native_model.node2index(valve_node)
valve_view = tree.layerTreeModelIndexToViewIndex(valve_source)
outer_view = tree.layerTreeModelIndexToViewIndex(tree.native_model.node2index(outer))
water_view = tree.layerTreeModelIndexToViewIndex(tree.native_model.node2index(water))
assert tree.isExpanded(water_view)
assert not tree.isExpanded(valve_view)
assert not bool(tree.model().flags(valve_view) & Qt.ItemFlag.ItemIsUserCheckable)
assert tree.model().data(valve_view, Qt.ItemDataRole.CheckStateRole) is None
delegate = tree.itemDelegate()
layer_option = delegate._typed_option(QStyleOptionViewItem(), valve_view, valve_node)
legend_view = tree.model().index(0, 0, valve_view)
legend_option = delegate._typed_option(QStyleOptionViewItem(), legend_view, None)
assert layer_option.font.bold()
assert not legend_option.font.bold()
assert legend_option.font.pointSizeF() < layer_option.font.pointSizeF()
legend = tree.native_model.layerLegendNodes(valve_node)
labels = [str(item.data(Qt.ItemDataRole.DisplayRole)) for item in legend]
assert labels[:2] == ["제수변", "공기변"], labels

foreign_source = tree.native_model.node2index(outer.findLayer(foreign.id()))
foreign_view = tree.layerTreeModelIndexToViewIndex(foreign_source)
assert tree.isRowHidden(foreign_view.row(), foreign_view.parent())

tree.setCurrentLayer(valve)
APP.processEvents()
assert state.selected[-1] == valve.id()
assert valve.selectedFeatureCount() == 0

valve_node.setItemVisibilityChecked(False)
state.visibilityChanged.emit()
APP.processEvents()
assert not valve_node.isVisible()
valve_node.setItemVisibilityChecked(True)
state.visibilityChanged.emit()
APP.processEvents()
assert valve_node.isVisible()

assert tree.feature_count(valve.id()) == 3
tree.set_counts([
    {"layer_id": valve.id(), "row_count": 1},
    {"layer_id": pipe.id(), "row_count": 2},
])
assert tree.feature_count(valve.id()) == 1
tree.setExpanded(valve_view, True)
tree.set_counts(state.rows)
assert tree.isExpanded(valve_view)
assert tree._expansion_by_project["native-tree-project"][tree._node_key(valve_node)]

# QGIS featureCount reflects pending native deletes, which is the explicit
# count policy used by LayerWorkspaceState during editing.
pipe.startEditing()
pipe.deleteFeature(next(pipe.getFeatures()).id())
pending_delete_count = pipe.featureCount()
assert pending_delete_count == 1
pipe.rollBack()

valve.setRenderer(QgsCategorizedSymbolRenderer("FTR_CDE", [
    QgsRendererCategory("SA100", QgsMarkerSymbol.createSimple({"color": "0,255,0"}), "제수변 변경"),
]))
tree.refresh_symbology(valve.id())
APP.processEvents()
valve_view = tree.layerTreeModelIndexToViewIndex(
    tree.native_model.node2index(valve_node)
)
assert tree.isExpanded(valve_view)
assert tree._expansion_by_project["native-tree-project"][tree._node_key(valve_node)]
changed_labels = [
    str(item.data(Qt.ItemDataRole.DisplayRole))
    for item in tree.native_model.layerLegendNodes(valve_node)
]
assert changed_labels == ["제수변 변경"], changed_labels

workspace = GeoFlowLayerWorkspace(plugin)
workspace.set_project({})
APP.processEvents()
assert isinstance(workspace.tree, QgsLayerTreeView)
assert isinstance(workspace.tree.native_model, QgsLayerTreeModel)
assert valve_node.customProperty("showFeatureCount", True) is False
assert workspace.count_toggle_button.isChecked()
workspace.count_toggle_button.click()
assert not workspace.tree.count_visible
workspace.count_toggle_button.click()
assert workspace.tree.count_visible
workspace.collapse_all_button.click()
assert not any(
    workspace.tree.isExpanded(index)
    for index in workspace.tree._walk_indexes()
)
workspace.expand_groups_button.click()
for index in workspace.tree._walk_indexes():
    node = workspace.tree.node_for_index(index)
    if isinstance(node, QgsLayerTreeGroup):
        assert workspace.tree.isExpanded(index)
    elif isinstance(node, QgsLayerTreeLayer):
        assert not workspace.tree.isExpanded(index)

# A -> B -> A filtering uses the same project tree model and leaves no stale
# QgsLayerTreeNode/QgsVectorLayer references in the presentation.
other_group = project.layerTreeRoot().addGroup("GeoFlow · OTHER")
other_group.setCustomProperty("geoflow/context_owner", "other-project")
other_layer = QgsVectorLayer("Point", "다른 프로젝트", "memory")
other_layer.setCustomProperty("geoflow/managed", True)
other_layer.setCustomProperty("geoflow/project_id", "other-project")
other_layer.setCustomProperty("geoflow/standard_name", "OTHER_PS")
project.addMapLayer(other_layer, False)
other_group.addLayer(other_layer)
APP.processEvents()
plugin.active_context = {"project_id": "other-project"}
tree.refresh_presentation()
APP.processEvents()
other_view = tree.layerTreeModelIndexToViewIndex(
    tree.native_model.node2index(other_group.findLayer(other_layer.id()))
)
assert tree.node_for_index(tree.rootIndex()) is other_group
assert not tree.isRowHidden(other_view.row(), other_view.parent())
plugin.active_context = {"project_id": "native-tree-project"}
tree.refresh_presentation()
APP.processEvents()
valve_view = tree.layerTreeModelIndexToViewIndex(
    tree.native_model.node2index(outer.findLayer(valve.id()))
)
assert not tree.isRowHidden(valve_view.row(), valve_view.parent())
assert tree.node_for_index(tree.rootIndex()) is outer
assert tree.isExpanded(valve_view)

result = {
    "qgis_version": Qgis.QGIS_VERSION,
    "view": type(tree).__mro__[1].__name__,
    "model": type(tree.native_model).__name__,
    "root_is_project_tree": tree.native_model.rootGroup() is project.layerTreeRoot(),
    "managed_only": tree.isRowHidden(foreign_view.row(), foreign_view.parent()),
    "legend_labels": labels,
    "changed_legend_labels": changed_labels,
    "count": tree.feature_count(valve.id()),
    "pending_delete_count": pending_delete_count,
    "visibility": valve_node.isVisible(),
    "layer_selection_preserved_feature_selection": valve.selectedFeatureCount() == 0,
    "workspace_uses_native_view": isinstance(workspace.tree, QgsLayerTreeView),
    "native_count_disabled": True,
    "tree_toolbar": True,
    "count_toggle_session_state": True,
    "project_switch_a_b_a": True,
    "project_root_hidden": True,
    "layer_checkbox_hidden": True,
    "layer_bold_legend_smaller": True,
    "initial_legend_collapsed": True,
    "expansion_preserved": tree.isExpanded(valve_view),
}
print("qgis native layer tree runtime: " + json.dumps(result, ensure_ascii=False))

workspace.shutdown()
workspace.close()
tree.shutdown()
tree.close()
project.clear()
