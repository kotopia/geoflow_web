"""QGIS 4 runtime checks for edit tools, previous values and nearby search."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from qgis.PyQt.QtCore import QObject, Qt, pyqtSignal
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QApplication, QDockWidget, QLabel, QMainWindow, QMenu, QPushButton,
    QToolButton, QVBoxLayout, QWidget,
)
from qgis.core import (
    QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsFeature, QgsGeometry, QgsPointXY, QgsProject, QgsRasterLayer,
    QgsVectorLayer,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from geoflow_connector.services.depth import DepthFromNearbySurveyH, DepthService
from geoflow_connector.services.nearby import NearbyService
from geoflow_connector.services.previous_values import PreviousValueService, copy_candidate
from geoflow_connector.forms.dynamic.binding import DynamicFormBinding
from geoflow_connector.forms.dynamic.form import DynamicForm
from geoflow_connector.ui.form_actions import FormActionToolbar
from geoflow_connector.ui.edit_tools import EditToolsController
from geoflow_connector.ui.survey_panel import SurveyPanel


APP = QApplication.instance() or QgsApplication([], False)
if isinstance(APP, QgsApplication):
    APP.initQgis()


class Settings:
    def __init__(self): self.values = {}
    def setValue(self, key, value): self.values[key] = value
    def value(self, key, default=None): return self.values.get(key, default)
    def sync(self): pass


def field(name, *, visible=True, readonly=False, widget="text"):
    return {
        "id": name, "field_name": name, "visible": visible,
        "readonly": readonly, "widget_type": widget,
        "storage": {"kind": "column", "key": name},
    }


# Previous values are explicitly scoped and exclude identity/lifecycle fields.
plugin_scope = SimpleNamespace(
    active_context={"project_id": "project-1"},
    current_user_context=lambda: {"user_id": "user-1"},
)
service = PreviousValueService(plugin_scope, Settings())
fields = [field("diameter"), field("description"), field("id", visible=False),
          field("worker_id"), field("status"), field("survey_date")]
source_form = SimpleNamespace(
    fields=fields,
    save_values=lambda: {
        "diameter": 300, "description": "현장값", "id": "uuid-a",
        "worker_id": "worker-a", "status": "완료", "survey_date": "2026-10-07",
    },
)
source_page = SimpleNamespace(standard="WTL_PIPE_LM", form=source_form)
assert service.capture(source_page) == 2
assert copy_candidate(field("diameter"))
assert not copy_candidate(field("status"))

handles = {name: SimpleNamespace(set_value=Mock()) for name in (row["id"] for row in fields)}
target_form = SimpleNamespace(
    fields=fields, handles=handles,
    values=Mock(return_value={"diameter": None, "description": None, "status": None}),
    load_values=Mock(),
)
target_binding = SimpleNamespace(has_actual_changes=Mock(return_value=True))
target_page = SimpleNamespace(
    standard="WTL_PIPE_LM", form=target_form, binding=target_binding,
)
assert service.apply(target_page) == ["diameter", "description"]
target_form.load_values.assert_called_once_with({
    "diameter": 300, "description": "현장값", "status": None,
})
target_binding.has_actual_changes.assert_called_once()


# Nearby distances remain metres even when source and target layers use
# different projected/display coordinate systems.
project = QgsProject.instance()
origin_wgs = QgsPointXY(127.405081, 36.270687)
source_crs = QgsCoordinateReferenceSystem("EPSG:5186")
origin_5186 = QgsCoordinateTransform(
    QgsCoordinateReferenceSystem("EPSG:4326"), source_crs,
    project.transformContext(),
).transform(origin_wgs)
source_geometry = QgsGeometry.fromPointXY(origin_5186)
survey = QgsVectorLayer("Point?crs=EPSG:4326&field=code:string&field=z:double", "survey", "memory")
for lon, code, z in ((127.405091, "H", 40.0), (127.40520, "H1", 41.0), (127.40515, "H", 42.0)):
    feature = QgsFeature(survey.fields())
    feature["code"], feature["z"] = code, z
    feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, origin_wgs.y())))
    assert survey.dataProvider().addFeature(feature)
nearby = NearbyService(project).find_nearby(
    source_geometry, source_crs, survey, 20,
    predicate=lambda candidate: DepthFromNearbySurveyH.is_h(candidate["code"]),
    limit=2,
)
assert len(nearby) == 2
assert nearby[0]["feature"]["code"] == "H"
assert 0 < nearby[0]["distance"] < nearby[1]["distance"] < 20
source_crs_5187 = QgsCoordinateReferenceSystem("EPSG:5187")
source_5187 = QgsGeometry.fromPointXY(QgsCoordinateTransform(
    QgsCoordinateReferenceSystem("EPSG:4326"), source_crs_5187,
    project.transformContext(),
).transform(origin_wgs))
nearby_5187 = NearbyService(project).find_nearby(
    source_5187, source_crs_5187, survey, 20,
    predicate=lambda candidate: DepthFromNearbySurveyH.is_h(candidate["code"]),
    limit=2,
)
assert len(nearby_5187) == 2
assert abs(nearby_5187[0]["distance"] - nearby[0]["distance"]) < 0.05
assert not DepthFromNearbySurveyH.is_h("H1")
try:
    DepthFromNearbySurveyH(depth_field="", subtract="reference-source")
    raise AssertionError("ambiguous depth contract must fail closed")
except ValueError:
    pass
depth = DepthFromNearbySurveyH(depth_field="pip_dep", subtract="reference-source")
assert depth.calculate(None, 10) == (None, "source_z_missing")
assert depth.calculate(8, None) == (None, "h_z_missing")
assert depth.calculate(8, 10) == (2.0, None)


# Linked-source lineage is explicit, the closest valid H wins, and partial
# failures leave status and other feature values untouched.
survey_depth = QgsVectorLayer(
    "Point?crs=EPSG:4326&field=id:string&field=code:string&field=raw_z:double",
    "survey-depth", "memory",
)
survey_depth.setCustomProperty("geoflow/standard_name", "SURVEY")
survey_rows = (
    ("source-1", "100", 38.5, 127.405081),
    ("source-no-z", "300", None, 127.405081),
    ("h-no-z", "H", None, 127.405082),
    ("h-valid", "H", 39.7, 127.405091),
    ("h1-invalid-code", "H1", 50.0, 127.405083),
)
for object_id, code, z_value, lon in survey_rows:
    row = QgsFeature(survey_depth.fields())
    row["id"], row["code"], row["raw_z"] = object_id, code, z_value
    row.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, origin_wgs.y())))
    assert survey_depth.dataProvider().addFeature(row)
targets = QgsVectorLayer(
    "Point?crs=EPSG:4326&field=id:string&field=ftr_cde:string&field=pip_dep:double&field=status:string",
    "depth-targets", "memory",
)
targets.setCustomProperty("geoflow/standard_name", "WTL_PIPE_PS")
for target_id in ("target-ok", "target-no-z", "target-no-link"):
    row = QgsFeature(targets.fields())
    row["id"], row["status"] = target_id, None
    row.setGeometry(QgsGeometry.fromPointXY(origin_wgs))
    assert targets.dataProvider().addFeature(row)
depth_plugin = SimpleNamespace(
    integration_state=lambda: {"ready":True,"can_write":True},
    _managed_layers=lambda: [survey_depth, targets],
    active_context={"project_id": "depth-project"},
    active_client=SimpleNamespace(base_url="https://example.test"),
    iface=SimpleNamespace(messageBar=lambda: None),
)
depth_service = DepthService(depth_plugin, settings=Settings())
by_id = {row["id"]: row for row in targets.getFeatures()}
calculated = depth_service.calculate_feature(by_id["target-ok"])
assert calculated["ok"] and calculated["depth"] == 1.2
assert calculated["reference_survey_id"] == "h-valid"
assert 0 < calculated["distance_m"] < 2
generated = depth_service.calculate_survey_point({
    "id": "source-1", "raw_code": "100", "raw_z": 38.5,
    "longitude": origin_wgs.x(), "latitude": origin_wgs.y(),
})
assert generated["ok"] and generated["depth"] == 1.2
batch_generated = DepthService(depth_plugin, settings=Settings()).prepare_batch().calculate_survey_point({
    "id": "source-1", "code": "100", "raw_code": "100", "raw_z": 38.5,
    "longitude": origin_wgs.x(), "latitude": origin_wgs.y(),
})
assert batch_generated["ok"]
assert batch_generated["depth"] == generated["depth"]
assert batch_generated["reference_survey_id"] == generated["reference_survey_id"]
assert abs(batch_generated["distance_m"] - generated["distance_m"]) < 0.001
generated_feature, generated_id = SurveyPanel._new_target_feature(
    SimpleNamespace(
        plugin=depth_plugin,
        _source_id_for_point=lambda _point: "runtime-source",
    ), targets, {
        "id": "source-1", "raw_code": "100", "raw_z": 38.5,
        "longitude": origin_wgs.x(), "latitude": origin_wgs.y(),
    }, "SA900", null_status=True,
)
assert generated_feature["pip_dep"] is None
assert generated_feature["status"] is None
assert targets.dataProvider().addFeature(generated_feature)
batch = depth_service.apply_to_features(
    targets, [row for row in targets.getFeatures()
              if str(row["id"]).startswith("target-")], overwrite=False,
)
assert (batch["success"], batch["failed"], batch["skipped"]) == (3, 0, 0)
assert {row["status"] for row in targets.getFeatures()} == {None}
assert next(row for row in targets.getFeatures()
            if row["id"] == "target-ok")["pip_dep"] == 1.2
targets.rollBack()


class Iface(QObject):
    currentLayerChanged = pyqtSignal(object)
    def __init__(self, layer):
        super().__init__(); self.layer = layer
        self.window = QMainWindow()
        self.actions = {name: Mock() for name in (
            "add", "move", "vertex", "split", "delete", "pan",
        )}
        for action in self.actions.values():
            action.icon.return_value = QIcon(":/geoflow/tabler/edit.svg")
            action.isEnabled.return_value = True
    def mainWindow(self): return self.window
    def addDockWidget(self, area, dock): self.window.addDockWidget(area, dock)
    def removeDockWidget(self, dock): self.window.removeDockWidget(dock)
    def activeLayer(self): return self.layer
    def set_layer(self, layer):
        self.layer = layer
        self.currentLayerChanged.emit(layer)
    def actionAddFeature(self): return self.actions["add"]
    def actionMoveFeature(self): return self.actions["move"]
    def actionVertexToolActiveLayer(self): return self.actions["vertex"]
    def actionSplitFeatures(self): return self.actions["split"]
    def actionDeleteSelected(self): return self.actions["delete"]
    def actionPan(self): return self.actions["pan"]


# Edit mode exposes only geometry-compatible native launchers and restores pan
# without rolling back the layer edit buffer.
edit_layer = QgsVectorLayer("Point?field=id:string", "point-edit", "memory")
edit_layer.setCustomProperty("geoflow/standard_name", "WTL_MANH_PS")
edit_layer.setCustomProperty("geoflow/managed", True)
existing = QgsFeature(edit_layer.fields())
existing.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(0, 0)))
assert edit_layer.dataProvider().addFeature(existing)
iface = Iface(edit_layer)
edit_logs = []
plugin = SimpleNamespace(
    iface=iface, work=None,
    integration_state=lambda: {
        "ready": True, "can_write": True, "layers": (iface.layer,)
        if isinstance(iface.layer, QgsVectorLayer) else (),
    },
    log=edit_logs.append,
)
plugin.dock = QDockWidget("main", iface.window)
iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, plugin.dock)
more_button = QToolButton()
more_button.setMenu(QMenu(more_button))
plugin.presentation = SimpleNamespace(
    root=SimpleNamespace(moreActionsButton=more_button)
)
toggle = QPushButton(); toggle.setCheckable(True)
controller = EditToolsController(plugin, toggle)
iface.window.show(); APP.processEvents()
toggle.click()
APP.processEvents()
assert controller.palette.isVisible()
assert controller.panel.addFeatureButton.isEnabled()
assert not controller.panel.addFeatureButton.icon().isNull()
assert controller.panel.addFeatureButton.toolTip() == "점 생성"
iface.actions["add"].isEnabled.return_value = False
controller.refresh()
assert not controller.panel.addFeatureButton.isEnabled()
iface.actions["add"].isEnabled.return_value = True
line_edit_layer = QgsVectorLayer("LineString?field=id:string", "line-edit", "memory")
line_edit_layer.setCustomProperty("geoflow/standard_name", "WTL_PIPE_LM")
line_edit_layer.setCustomProperty("geoflow/managed", True)
iface.set_layer(line_edit_layer)
assert controller.panel.addFeatureButton.toolTip() == "선 생성"
iface.set_layer(edit_layer)
existing_id = next(edit_layer.getFeatures()).id()
edit_layer.selectByIds([existing_id])
assert controller.panel.moveButton.isEnabled()
assert controller.panel.deleteButton.isEnabled()
controller.panel.deleteButton.click()
iface.actions["delete"].trigger.assert_called_once()
edit_layer.selectByIds([])
assert not controller.panel.moveButton.isEnabled()
raster = QgsRasterLayer("", "raster", "gdal")
iface.set_layer(raster)
assert not controller.panel.addFeatureButton.isEnabled()
assert not controller.panel.moveButton.isEnabled()
iface.set_layer(edit_layer)
edit_layer.selectByIds([existing_id])
assert controller.panel.moveButton.isEnabled()

# A selected feature which is also open in Dynamic Form is updated through the
# form/binding lifecycle, not through a stale parallel edit-buffer value.
form_target = QgsVectorLayer(
    "Point?crs=EPSG:4326&field=id:string&field=pip_dep:double",
    "form-depth-target", "memory",
)
form_target.setCustomProperty("geoflow/standard_name", "WTL_PIPE_PS")
form_row = QgsFeature(form_target.fields())
form_row["id"] = "target-form"
form_row.setGeometry(QgsGeometry.fromPointXY(origin_wgs))
assert form_target.dataProvider().addFeature(form_row)
other_form_row = QgsFeature(form_target.fields())
other_form_row["id"] = "target-other"
other_form_row.setGeometry(QgsGeometry.fromPointXY(origin_wgs))
assert form_target.dataProvider().addFeature(other_form_row)
form_rows = {row["id"]: row.id() for row in form_target.getFeatures()}
form_fid = form_rows["target-form"]
other_form_fid = form_rows["target-other"]
depth_field = field("pip_dep", widget="decimal")
depth_field.update({
    "label": "심도", "required": False, "display_order": 1,
    "layout": {}, "reference_codes": [], "semantic_data_type": "decimal",
})
depth_form = DynamicForm({"fields": [depth_field], "rules": []}, [depth_field])
depth_page = SimpleNamespace(
    note=QLabel(), dirty=False, feature_id=form_fid,
    form=depth_form, standard="WTL_PIPE_PS", layer_id=form_target.id(),
    form_actions=FormActionToolbar(depth_form.tabs),
)
depth_form.set_header_widget(depth_page.form_actions)
depth_page.update_dirty = lambda: setattr(
    depth_page, "dirty", bool(depth_page.binding.dirty)
)
depth_page.binding = DynamicFormBinding(
    depth_page, form_target, depth_form, True
)
depth_page.binding.load(form_target.getFeature(form_fid), force=True)
plugin.work = SimpleNamespace(
    pages={form_target.id(): depth_page}, previous_values=SimpleNamespace(
        available=lambda _page: False
    ),
)
plugin._managed_layers = lambda: [survey_depth, form_target]
iface.set_layer(form_target)
form_target.selectByIds([form_fid, other_form_fid])
controller._overwrite_choice = Mock(
    side_effect=AssertionError("단일 심도 계산은 옵션 UI를 열면 안 됨")
)
controller.register_form_page(depth_page, form_target)
inline_depth_button = controller._depth_field_actions[form_target.id()][0]
assert not depth_page.form_actions.saveButton.icon().isNull()
assert not depth_page.form_actions.previousButton.icon().isNull()
assert not depth_page.form_actions.nearbyButton.icon().isNull()
assert not depth_page.form_actions.layoutButton.icon().isNull()
assert not depth_page.form_actions.referenceRefreshButton.icon().isNull()
assert not depth_page.form_actions.photoButton.icon().isNull()
for action_button in (
    depth_page.form_actions.saveButton,
    depth_page.form_actions.previousButton,
    depth_page.form_actions.nearbyButton,
    depth_page.form_actions.layoutButton,
    depth_page.form_actions.referenceRefreshButton,
    depth_page.form_actions.photoButton,
):
    assert action_button.property("fieldAction") == "true"
    assert action_button.minimumWidth() == inline_depth_button.minimumWidth()
    assert action_button.maximumWidth() == inline_depth_button.maximumWidth()
assert inline_depth_button in depth_form._field_actions["pip_dep"]
assert not inline_depth_button.icon().isNull()
assert inline_depth_button.property("fieldAction") == "true"
assert not inline_depth_button.autoRaise()
assert inline_depth_button.iconSize().width() == 16
assert inline_depth_button.iconSize().height() == 16
assert inline_depth_button.minimumWidth() == inline_depth_button.maximumWidth()
assert inline_depth_button.minimumHeight() == inline_depth_button.maximumHeight()
depth_editor_row = depth_form.handles["pip_dep"].field_block.layout().itemAt(1).layout()
assert depth_editor_row.indexOf(depth_form.handles["pip_dep"].widget) == 0
assert depth_editor_row.indexOf(inline_depth_button) == 1
inline_depth_button.click()
controller._overwrite_choice.assert_not_called()
assert depth_form.values()["pip_dep"] == 1.2
assert depth_page.binding.has_actual_changes()
assert depth_page.dirty
assert not form_target.isModified()
assert set(form_target.selectedFeatureIds()) == {form_fid, other_form_fid}
assert any(
    '"target": "dynamic_form"' in row and '"widget_updated": true' in row
    for row in edit_logs if row.startswith("depth_apply_result ")
)
saved_from_toolbar = []
depth_page.form_actions.saveButton.clicked.connect(
    lambda: saved_from_toolbar.append(depth_page.binding.save())
)
depth_page.form_actions.saveButton.click()
assert saved_from_toolbar == [True]
assert not depth_page.binding.dirty and not depth_page.dirty
saved_form_row = form_target.getFeature(depth_page.binding.feature_id)
assert saved_form_row["pip_dep"] == 1.2
depth_page.binding.load(saved_form_row, force=True)
assert depth_form.values()["pip_dep"] == 1.2

# A failed calculation preserves the currently displayed value.
calculate_feature = controller.depth.calculate_feature
controller.depth.calculate_feature = lambda _feature: {
    "ok": False, "reason": "no_nearby_survey"
}
inline_depth_button.click()
assert depth_form.values()["pip_dep"] == 1.2
controller.depth.calculate_feature = calculate_feature
depth_page.binding.dispose()
reopened_form = DynamicForm(
    {"fields": [depth_field], "rules": []}, [depth_field]
)
reopened_page = SimpleNamespace(
    note=QLabel(), dirty=False, feature_id=saved_form_row.id()
)
reopened_page.update_dirty = lambda: None
reopened_binding = DynamicFormBinding(
    reopened_page, form_target, reopened_form, True
)
reopened_binding.load(saved_form_row, force=True)
assert reopened_form.values()["pip_dep"] == 1.2
assert not reopened_binding.has_actual_changes()
reopened_binding.dispose()

non_depth_form = DynamicForm(
    {"fields": [field("name")], "rules": []}, [
        {**field("name"), "label": "이름", "required": False,
         "display_order": 1, "layout": {}, "reference_codes": [],
         "semantic_data_type": "text"}
    ],
)
non_depth_page = SimpleNamespace(form=non_depth_form)
non_depth_layer = QgsVectorLayer("Point?field=name:string", "manhole", "memory")
non_depth_layer.setCustomProperty("geoflow/standard_name", "WTL_MANH_PS")
assert controller.field_action_registry.attach(
    non_depth_page, non_depth_layer, controller
) == []

plugin._managed_layers = lambda: [survey_depth, targets]
plugin.work = None
iface.set_layer(targets)
targets.selectAll()
assert not any(
    action.text() == "선택 객체 심도 일괄계산"
    for action in plugin.presentation.root.moreActionsButton.menu().actions()
)
toggle.click()
APP.processEvents()
assert toggle.isChecked() and targets.isEditable()
controller.panel.addFeatureButton.click()
iface.actions["add"].trigger.assert_called_once()
assert targets.isEditable()
draft = QgsFeature(targets.fields()); assert targets.addFeature(draft)
targets.rollBack()
APP.processEvents()
iface.actions["pan"].trigger.assert_called()
assert not toggle.isChecked()
assert not targets.isEditable()
assert not targets.isModified()
controller.close(); toggle.deleteLater(); iface.window.close()

print("qgis field tools runtime: OK")
