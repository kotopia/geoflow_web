"""Run with QGIS Python: offscreen integration smoke test, no project or DB writes."""
from types import SimpleNamespace

from qgis.PyQt.QtCore import QDate, Qt
from qgis.PyQt.QtWidgets import QApplication, QCheckBox, QLabel
from qgis.core import QgsApplication, QgsFeature, QgsGeometry, QgsPointXY, QgsVectorLayer

from geoflow_connector.forms.dynamic.binding import DynamicFormBinding, _clean
from geoflow_connector.forms.common.lifecycle import sole_new_feature
from geoflow_connector.forms.dynamic.form import DynamicForm
from geoflow_connector.ui.behaviors.shape_switch import (
    SHAPE_SWITCH_CONFIGS,
    ShapeSwitchController,
    create_shape_switches,
)
from geoflow_connector.ui.form_host import Main as DynamicFormHost
from geoflow_connector.ui.form_actions import FormActionToolbar


app = QApplication.instance() or QgsApplication([], False)
if isinstance(app, QgsApplication):
    app.initQgis()


def field(name, standard="WTL_MANH_PS"):
    return {
        "id": name,
        "layer_standard_name": standard,
        "semantic_data_type": "decimal",
        "widget_type": "decimal",
        "label": name,
        "visible": True,
        "required": False,
        "readonly": False,
        "display_order": 1,
        "layout": {},
        "reference_codes": [],
        "storage": {"kind": "column", "key": name},
    }


fields = [field(name) for name in ("sbc_size", "sbc_size_h", "sbc_size_v")]
definition = {"fields": fields, "rules": []}
manifest_layers = [
    {"standard_name": standard, "label": label}
    for standard, label in (
        ("WTL_VALV_PS", "변류시설"), ("WTL_PIPE_LM", "상수관로"),
        ("WTL_PIPE_PS", "상수심도"), ("WTL_FIRE_PS", "소화전"),
        ("WTL_FLOW_PS", "유량계"), ("WTL_ETC_PS", "기타시설"),
        ("SURVEY", "Survey"),
    )
]
for manifest_row in manifest_layers:
    assert DynamicFormHost._layer_display_name(
        manifest_layers, manifest_row["standard_name"]
    ) == manifest_row["label"]
assert DynamicFormHost._layer_display_name(manifest_layers, "UNKNOWN") == "UNKNOWN"
layer = QgsVectorLayer(
    "Point?crs=EPSG:4326&field=sbc_size:double&field=sbc_size_h:double&field=sbc_size_v:double",
    "shape-smoke",
    "memory",
)
layer.setCustomProperty("geoflow/standard_name", "WTL_MANH_PS")
layer.setCustomProperty("geoflow/definition_layer_id", "runtime-layer-id")
feature = QgsFeature(layer.fields())
feature.setAttributes([None, 800.0, 600.0])
assert layer.dataProvider().addFeature(feature)
feature_id = next(layer.getFeatures()).id()

form = DynamicForm(definition, fields, layer="WTL_MANH_PS")
chrome_page = SimpleNamespace(
    tabs=form.tabs, display_name="상수맨홀",
    form=form, form_actions=FormActionToolbar(form),
)
form.set_header_widget(chrome_page.form_actions)
DynamicFormHost._apply_page_chrome(chrome_page)
form.layoutChanged.connect(
    lambda: DynamicFormHost._apply_page_chrome(chrome_page)
)
assert form.tabs.tabText(0) == "기본 정보"
assert chrome_page.form_actions.layerTitleLabel.text() == "상수맨홀"
assert form.tabs.cornerWidget(Qt.Corner.TopRightCorner) is None
controller = ShapeSwitchController(layer, form, SHAPE_SWITCH_CONFIGS[0], form)
page = SimpleNamespace(note=QLabel(), dirty=False, feature_id=feature_id)
page.update_dirty = lambda: None
binding = DynamicFormBinding(page, layer, form, True)
binding.load(layer.getFeature(feature_id))

assert controller.enabled
assert controller.shape == "rect"
assert controller.host.parentWidget() is form.handles["sbc_size_v"].field_block
rect_row = form.handles["sbc_size_v"].field_block.layout().itemAt(1).layout()
assert rect_row.indexOf(controller.host) == 1
assert controller.host.shapeToggleButton.text() == ""
assert not controller.host.shapeToggleButton.icon().isNull()
assert controller.host.shapeToggleButton.property("fieldAction") == "true"
assert not controller.host.shapeToggleButton.autoRaise()
assert (controller.host.shapeToggleButton.minimumWidth()
        == controller.host.shapeToggleButton.maximumWidth())
assert (controller.host.shapeToggleButton.minimumHeight()
        == controller.host.shapeToggleButton.maximumHeight())
assert controller.host.shapeToggleButton.iconSize().width() == 16
assert controller.host.shapeToggleButton.iconSize().height() == 16
assert controller.host.shapeSwitchLayout.count() == 1
assert form.handles["sbc_size"].field_block.isHidden()
assert not controller.host.isHidden()
assert not form.handles["sbc_size_h"].field_block.isHidden()

form.handles["sbc_size"].set_value(900.0)
form.resize(360, 120)
form.show()
app.processEvents()
scroll = form.tabs.currentWidget()
scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
scroll_before = scroll.verticalScrollBar().value()
assert scroll_before > 0
controller.host.shapeToggleButton.click()
app.processEvents()
assert form.tabs.tabText(0) == "기본 정보"
assert chrome_page.form_actions.layerTitleLabel.text() == "상수맨홀"
assert controller.host.parentWidget() is form.handles["sbc_size"].field_block
round_row = form.handles["sbc_size"].field_block.layout().itemAt(1).layout()
assert round_row.indexOf(controller.host) == 1
restored_scroll = form.tabs.currentWidget().verticalScrollBar()
assert restored_scroll.value() == min(scroll_before, restored_scroll.maximum())
assert form.values()["sbc_size_h"] == 800.0  # button click did not erase the draft
assert binding.save()

saved = layer.getFeature(feature_id)
assert saved["sbc_size"] == 900.0
assert _clean(saved["sbc_size_h"]) is None
assert _clean(saved["sbc_size_v"]) is None
assert controller.shape == "round"

binding.dispose()

# The second family keeps its shared depth for both shapes.
dpg_names = ("dpg_std", "dpg_std_h", "dpg_std_v", "dpg_dep")
dpg_fields = [field(name, "WTL_VALV_PS") for name in dpg_names]
dpg_definition = {"fields": dpg_fields, "rules": []}
dpg_layer = QgsVectorLayer(
    "Point?crs=EPSG:4326&field=dpg_std:double&field=dpg_std_h:double&field=dpg_std_v:double&field=dpg_dep:double",
    "depth-shape-smoke",
    "memory",
)
dpg_layer.setCustomProperty("geoflow/standard_name", "WTL_VALV_PS")
dpg_layer.setCustomProperty("geoflow/definition_layer_id", "runtime-valve-layer-id")
dpg_feature = QgsFeature(dpg_layer.fields())
dpg_feature.setAttributes([None, 500.0, 400.0, 1200.0])
assert dpg_layer.dataProvider().addFeature(dpg_feature)
dpg_id = next(dpg_layer.getFeatures()).id()
dpg_form = DynamicForm(dpg_definition, dpg_fields, layer="WTL_VALV_PS")
dpg_controller = ShapeSwitchController(
    dpg_layer, dpg_form, SHAPE_SWITCH_CONFIGS[1], dpg_form
)
dpg_page = SimpleNamespace(note=QLabel(), dirty=False, feature_id=dpg_id)
dpg_page.update_dirty = lambda: None
dpg_binding = DynamicFormBinding(dpg_page, dpg_layer, dpg_form, True)
dpg_binding.load(dpg_layer.getFeature(dpg_id))
assert dpg_controller.shape == "rect"
assert dpg_controller.host.parentWidget() is dpg_form.handles["dpg_std_v"].field_block
dpg_form.handles["dpg_std"].set_value(700.0)
dpg_controller.host.shapeToggleButton.click()
assert dpg_controller.host.parentWidget() is dpg_form.handles["dpg_std"].field_block
assert dpg_binding.save()
dpg_saved = dpg_layer.getFeature(dpg_id)
assert dpg_saved["dpg_std"] == 700.0
assert _clean(dpg_saved["dpg_std_h"]) is None
assert _clean(dpg_saved["dpg_std_v"]) is None
assert dpg_saved["dpg_dep"] == 1200.0
dpg_binding.dispose()

# Unsupported and incomplete definitions fail closed without raising.
outside_layer = QgsVectorLayer("Point?field=sbc_size:double", "outside", "memory")
outside_layer.setCustomProperty("geoflow/standard_name", "ROAD_TEST_PS")
outside_form = DynamicForm(definition, fields, layer="ROAD_TEST_PS")
outside_controller = ShapeSwitchController(
    outside_layer, outside_form, SHAPE_SWITCH_CONFIGS[0], outside_form
)
assert not outside_controller.enabled
assert outside_controller.host.isHidden()

partial_fields = [field("sbc_size"), field("sbc_size_h")]
partial_form = DynamicForm({"fields": partial_fields, "rules": []}, partial_fields,
                           layer="WTL_MANH_PS")
partial_controller = ShapeSwitchController(
    layer, partial_form, SHAPE_SWITCH_CONFIGS[0], partial_form
)
assert not partial_controller.enabled
assert partial_controller.host.isHidden()

# Both switch instances can hold opposite shapes on the same object.
combined_fields = [field(name) for name in (
    "sbc_size", "sbc_size_h", "sbc_size_v",
    "dpg_std", "dpg_std_h", "dpg_std_v", "dpg_dep",
)]
combined_form = DynamicForm({"fields": combined_fields, "rules": []}, combined_fields,
                            layer="WTL_MANH_PS")
cover_switch, chamber_switch = create_shape_switches(layer, combined_form, combined_form)
combined_form.load_values({
    "sbc_size": 900.0,
    "dpg_std_h": 500.0,
    "dpg_std_v": 400.0,
    "dpg_dep": 1200.0,
})
assert cover_switch.shape == "round"
assert chamber_switch.shape == "rect"
cover_switch.host.shapeToggleButton.click()
assert cover_switch.shape == "rect"
assert chamber_switch.shape == "rect"
chamber_switch.host.shapeToggleButton.click()
assert cover_switch.shape == "rect"
assert chamber_switch.shape == "round"
assert not combined_form.handles["dpg_dep"].field_block.isHidden()

# Current central checkbox widget remains the standard QCheckBox implementation.
status_field = field("status")
status_field.update(semantic_data_type="boolean", widget_type="boolean")
status_form = DynamicForm({"fields": [status_field], "rules": []}, [status_field])
assert isinstance(status_form.handles["status"].editor, QCheckBox)

# New features receive the current work date as a real attribute. The commit
# callback deliberately clears the member FID to reproduce the original race.
date_field = field("date")
date_field.update(semantic_data_type="date", widget_type="date", label="작업일")
date_definition = {"fields": [date_field], "rules": []}
date_layer = QgsVectorLayer("Point?crs=EPSG:4326&field=date:date", "date-smoke", "memory")
date_layer.setCustomProperty("geoflow/standard_name", "WTL_MANH_PS")
date_form = DynamicForm(date_definition, [date_field], layer="WTL_MANH_PS")
date_page = SimpleNamespace(note=QLabel(), dirty=False, feature_id=None)
date_page.update_dirty = lambda: None
date_binding = DynamicFormBinding(date_page, date_layer, date_form, True)

saved_ids = []
for x in (1.0, 2.0):
    if not date_layer.isEditable():
        assert date_layer.startEditing()
    new_feature = QgsFeature(date_layer.fields())
    new_feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, x)))
    assert date_layer.addFeature(new_feature)
    temporary_id = new_feature.id()
    date_page.feature_id = temporary_id
    date_binding.load(date_layer.getFeature(temporary_id), force=True)
    today = QDate.currentDate().toString("yyyy-MM-dd")
    assert date_form.values()["date"] == today, (
        temporary_id,
        list(date_layer.editBuffer().addedFeatures()),
        sole_new_feature(date_layer, temporary_id),
        date_form.values()["date"],
        date_binding.source_original,
    )

    def clear_reentrant_fid(*_args):
        date_binding.feature_id = None
        date_page.feature_id = None

    date_layer.afterCommitChanges.connect(clear_reentrant_fid)
    assert date_binding.save()
    date_layer.afterCommitChanges.disconnect(clear_reentrant_fid)
    assert date_binding.feature_id is not None
    assert date_page.feature_id == date_binding.feature_id
    saved_feature = date_layer.getFeature(date_binding.feature_id)
    assert saved_feature.isValid()
    saved_date = saved_feature["date"]
    saved_text = (saved_date.toString("yyyy-MM-dd")
                  if hasattr(saved_date, "toString") else str(saved_date)[:10])
    assert saved_text == today
    saved_ids.append(date_binding.feature_id)

assert saved_ids[0] != saved_ids[1]

# Existing dates, including a past date, are loaded without a today override.
existing_layer = QgsVectorLayer("Point?field=date:date", "existing-date", "memory")
existing_feature = QgsFeature(existing_layer.fields())
existing_feature.setAttribute("date", QDate(2020, 5, 6))
assert existing_layer.dataProvider().addFeature(existing_feature)
existing_id = next(existing_layer.getFeatures()).id()
existing_form = DynamicForm(date_definition, [date_field], layer="WTL_MANH_PS")
existing_page = SimpleNamespace(note=QLabel(), dirty=False, feature_id=existing_id)
existing_page.update_dirty = lambda: None
existing_binding = DynamicFormBinding(existing_page, existing_layer, existing_form, True)
existing_binding.load(existing_layer.getFeature(existing_id))
assert existing_form.values()["date"] == "2020-05-06"
assert not existing_binding.dirty
assert existing_binding.save()
past_saved = existing_layer.getFeature(existing_id)["date"]
past_text = (past_saved.toString("yyyy-MM-dd")
             if hasattr(past_saved, "toString") else str(past_saved)[:10])
assert past_text == "2020-05-06"

null_feature = QgsFeature(existing_layer.fields())
assert existing_layer.dataProvider().addFeature(null_feature)
null_id = max(existing_layer.allFeatureIds())
existing_binding.load(existing_layer.getFeature(null_id), force=True)
assert existing_form.values()["date"] is None
assert not existing_binding.dirty
existing_binding.dispose()
date_binding.dispose()

# Deleting the currently bound feature clears only stale form state.  The
# QGIS edit buffer keeps the DELETE so commit/sync can process it, while form
# transition guards no longer see the deleted FID as an unsaved form draft.
delete_layer = QgsVectorLayer("Point?field=sbc_size:double", "delete-form", "memory")
delete_feature = QgsFeature(delete_layer.fields())
delete_feature["sbc_size"] = 300.0
assert delete_layer.dataProvider().addFeature(delete_feature)
delete_id = next(delete_layer.getFeatures()).id()
delete_form = DynamicForm(
    {"fields": [field("sbc_size")], "rules": []}, [field("sbc_size")]
)
delete_page = SimpleNamespace(note=QLabel(), dirty=False, feature_id=delete_id)
delete_page.update_dirty = lambda: None
delete_binding = DynamicFormBinding(
    delete_page, delete_layer, delete_form, True
)
delete_binding.load(delete_layer.getFeature(delete_id))
assert delete_layer.startEditing()
assert delete_layer.deleteFeature(delete_id)
assert delete_binding.is_feature_deleted()
assert delete_binding.has_pending_feature_edit()
assert delete_binding.clear_deleted()
assert delete_binding.feature_id is None and delete_page.feature_id is None
assert delete_id in set(delete_layer.editBuffer().deletedFeatureIds())
assert not delete_binding.has_pending_feature_edit()

cleared_deleted_pages = []
transition_host = SimpleNamespace(
    pages={"deleted": SimpleNamespace(
        binding=SimpleNamespace(is_feature_deleted=lambda: True)
    )},
    _clear_deleted_page=cleared_deleted_pages.append,
    _update_page_dirty=lambda _page: (_ for _ in ()).throw(
        AssertionError("deleted page must bypass the unsaved-form guard")
    ),
)
assert DynamicFormHost.guard_transition(transition_host, "edit stop")
assert len(cleared_deleted_pages) == 1
delete_binding.dispose()
delete_layer.rollBack()

if isinstance(app, QgsApplication):
    app.exitQgis()
print("qgis shape switch smoke: OK")
