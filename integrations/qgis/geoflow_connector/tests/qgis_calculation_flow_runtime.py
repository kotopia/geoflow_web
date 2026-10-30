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
layer = QgsVectorLayer("Point?crs=EPSG:4326&field=id:string&field=pip_dep:double&field=ang_dir:double&field=note:string", "runtime", "memory")
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


from qgis.core import QgsGeometry,QgsPointXY,QgsRectangle
from qgis.PyQt.QtCore import Qt,QPoint,QEvent
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QWidget,QVBoxLayout
from qgis.gui import QgsMapMouseEvent
from geoflow_connector.forms.dynamic.form import DynamicForm
from geoflow_connector.forms.dynamic.binding import DynamicFormBinding
from geoflow_connector.ui.form_actions import FormActionToolbar
from geoflow_connector.layers.identify import IdentifyGeometry
from geoflow_connector.ui.direction import RotationDialog
from uuid import uuid4

def add(target,ident,x,depth=None,code=None,z=None):
    f=QgsFeature(target.fields());f['id']=ident
    if 'pip_dep' in target.fields().names():f['pip_dep']=depth;f['ang_dir']=0
    if code is not None:f['code']=code;f['raw_z']=z
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x,36.36)))
    assert target.dataProvider().addFeature(f)
    target.updateExtents();return f
features=[add(layer,'null',127.40),add(layer,'same',127.400001,1.2),add(layer,'old',127.400002,3),add(layer,'missing',127.42)]
survey=QgsVectorLayer('Point?crs=EPSG:4326&field=id:string&field=code:string&field=raw_z:double','Survey','memory')
for key,val in [('managed',True),('project_id','project-1'),('package_path','runtime.gpkg'),('standard_name','SURVEY')]:survey.setCustomProperty('geoflow/'+key,val)
add(survey,'source',127.40,code='100',z=38.5);add(survey,'height',127.40001,code='H',z=39.7)
QgsProject.instance().addMapLayer(survey);plugin.active_context['layer_ids'].append(survey.id())
canvas.setDestinationCrs(layer.crs());canvas.setLayers([layer,survey]);canvas.setExtent(QgsRectangle(127.3999,36.3599,127.4201,36.3601))
controller=plugin.edit_tools
iface._layer=layer
layer.selectByIds([f.id() for f in features]);controller.refresh();APP.processEvents()
assert not layer.isEditable()
assert controller.depth_batch_button.isEnabled()
assert controller.depth_batch_button.parentWidget() is plugin.presentation.rail
assert not controller.palette.isVisible()
controller._overwrite_choice=lambda:False
controller.depth_batch_button.click();APP.processEvents()
dialog=controller._depth_results
assert dialog.isVisible() and dialog.table.rowCount()==4
assert {r['identity']:r['status'] for r in dialog.rows}=={'null':'changed','same':'skipped','old':'skipped','missing':'failed'},dialog.rows
assert layer.selectedFeatureCount()==4
assert len(dialog.highlight.bands)==2,(len(dialog.highlight.bands),dialog.rows)
saved_selection=layer.selectedFeatureIds();dialog.locate(0);dialog.show_changed();assert layer.selectedFeatureIds()==saved_selection
dialog.close();assert not dialog.highlight.bands
controller._overwrite_choice=lambda:True
controller.depth_batch_button.click();APP.processEvents()
dialog=controller._depth_results
assert {r['identity']:r['status'] for r in dialog.rows}=={'null':'unchanged','same':'unchanged','old':'changed','missing':'failed'},dialog.rows
assert '계산 성공 3' in dialog.summary.text() and '실제 변경 1' in dialog.summary.text()
dialog.close();layer.rollBack()
# Missing Survey is a visible execution failure, not a silent disabled action.
plugin.active_context['layer_ids'].remove(survey.id());controller.refresh()
assert controller.depth_batch_button.isEnabled()
controller.depth_batch_button.click();APP.processEvents()
assert all(r['status']=='failed' for r in controller._depth_results.rows)
controller._depth_results.close();assert not layer.isEditable()
plugin.active_context['layer_ids'].append(survey.id())
# Capability survives incomplete configuration and generic field-action preferences.
layer_id=str(uuid4());field_id=str(uuid4());layer.setCustomProperty('geoflow/definition_layer_id',layer_id)
field=dict(id=field_id,layer_id=layer_id,layer_standard_name='WTL_PIPE_PS',label='Angle',
    widget_type='decimal',semantic_data_type='decimal',visible=True,required=False,readonly=False,
    display_order=1,layout={},reference_codes=[],storage={'kind':'column','key':'ang_dir'},
    capabilities=['direction'],direction=None)
service=plugin._definition_service;service.definition={'fields':[field],'rules':[]};service.state='ready'
page=QWidget();page.standard='WTL_PIPE_PS';page.layer_id=layer.id();page.project_id='project-1';page.feature_id=features[0].id();page.note=QLabel();page.dirty=False
page.form=DynamicForm(service.definition,[field],page);QVBoxLayout(page).addWidget(page.form)
page.form_actions=FormActionToolbar(page.form);page.update_dirty=lambda:None
page.binding=DynamicFormBinding(page,layer,page.form,True);page.binding.load(layer.getFeature(page.feature_id),force=True)
layer.selectByIds([page.feature_id]);controller.register_form_page(page,layer);page.show();APP.processEvents()
assert len(page._direction_actions[field_id])==2
assert all(not b.isHidden() and not b.isEnabled() and b.toolTip() for b in page._direction_actions[field_id])
# Updating definitions attaches/enables existing page actions without duplicate buttons.
field['direction']=dict(zero_axis='north',positive_direction='clockwise',symbol_offset=90,allow_reverse=True)
controller._refresh_direction_page(page,layer)
assert not page._direction_actions[field_id][0].isEnabled()
assert page._direction_actions[field_id][1].isEnabled()
controller._refresh_direction_page(page,layer);assert len(page._direction_actions[field_id])==2
assert controller.direction.targets(layer)
rotation=RotationDialog(controller,layer,page);rotation.show();rotation.spin.setValue(73);APP.processEvents()
assert rotation.dial.value()==7300 and not layer.isEditable()
rotation.reject();assert not layer.isModified()
rotation=RotationDialog(controller,layer,page);rotation.show();rotation.set_value(73);rotation.apply()
assert layer.getFeature(page.feature_id)['ang_dir']==73
layer.undoStack().undo();assert layer.getFeature(page.feature_id)['ang_dir']==0
# Permission rechecked when applying, including attempts through service APIs.
plugin.active_context['manifest']['transport']['write_authorized']=False
controller.refresh();assert not controller.depth_batch_button.isEnabled()
result=controller.direction.manual_result(layer,layer.getFeature(page.feature_id))
try:controller.direction.apply(layer,[dict(result,angle=10)],track=False);raise AssertionError('permission bypass')
except ValueError:pass
summary=controller.depth.apply_to_features(layer,features,overwrite=True)
assert summary['changed']==0 and summary['failed']==4
page.binding.dispose();page.close();plugin.unload();window.close()
print('USER_FLOW: selection-independent depth buttons, real spatial calculation, per-row results, highlights, manual rules, refreshed actions, undo, permissions OK')
