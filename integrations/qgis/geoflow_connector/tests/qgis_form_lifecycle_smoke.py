"""QGIS 4 offscreen checks for worker widgets and feature-scoped discard."""
from types import SimpleNamespace

from qgis.PyQt.QtCore import QDate
from qgis.PyQt.QtWidgets import QApplication, QLabel, QComboBox, QLineEdit
from qgis.core import (
    QgsApplication, QgsFeature, QgsGeometry, QgsPointXY, QgsVariantUtils,
    QgsVectorLayer,
)

from geoflow_connector.api.references import fields_with_worker_references
from geoflow_connector.forms.dynamic.binding import DynamicFormBinding
from geoflow_connector.forms.dynamic.form import DynamicForm
from geoflow_connector.ui.form_host import Main as DynamicFormHost


app = QApplication.instance() or QgsApplication([], False)
if isinstance(app, QgsApplication):
    app.initQgis()


def field(name, widget_type="text", semantic="text"):
    return {
        "id": name,
        "layer_standard_name": "WTL_MANH_PS",
        "semantic_data_type": semantic,
        "widget_type": widget_type,
        "label": name,
        "visible": True,
        "required": False,
        "readonly": False,
        "display_order": 1,
        "layout": {},
        "reference_codes": [],
        "storage": {"kind": "column", "key": name},
    }


def binding_for(layer, fields, feature_id):
    form = DynamicForm({"fields": fields, "rules": []}, fields)
    page = SimpleNamespace(note=QLabel(), dirty=False, feature_id=feature_id)
    page.update_dirty = lambda: None
    binding = DynamicFormBinding(page, layer, form, True)
    binding.load(layer.getFeature(feature_id), force=True)
    return form, page, binding


# Worker choices populate only a centrally selected combo/relation widget.
catalog = {
    "workers": [{"id": "worker-1", "name": "작업자 1", "resolved": True}],
}
text_worker = fields_with_worker_references([field("worker_id", "text")], catalog)[0]
combo_worker = fields_with_worker_references([field("worker_id", "combo")], catalog)[0]
assert text_worker["widget_type"] == "text"
assert text_worker["reference_codes"] == []
assert combo_worker["widget_type"] == "combo"
assert combo_worker["reference_codes"][0]["value"] == "worker-1"
text_form = DynamicForm({"fields": [text_worker], "rules": []}, [text_worker])
combo_form = DynamicForm({"fields": [combo_worker], "rules": []}, [combo_worker])
assert isinstance(text_form.handles["worker_id"].editor, QLineEdit)
assert not isinstance(text_form.handles["worker_id"].editor, QComboBox)
assert isinstance(combo_form.handles["worker_id"].editor, QComboBox)


# Existing feature attribute and geometry edits are rolled back when isolated.
existing_layer = QgsVectorLayer("Point?field=name:string", "existing", "memory")
existing = QgsFeature(existing_layer.fields())
existing.setAttribute("name", "original")
existing.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(1, 1)))
assert existing_layer.dataProvider().addFeature(existing)
existing_id = next(existing_layer.getFeatures()).id()
existing_form, existing_page, existing_binding = binding_for(
    existing_layer, [field("name")], existing_id
)
assert existing_layer.startEditing()
assert existing_layer.changeAttributeValue(existing_id, 0, "changed")
assert existing_layer.changeGeometry(
    existing_id, QgsGeometry.fromPointXY(QgsPointXY(9, 9))
)
assert existing_binding.has_pending_feature_edit()
assert existing_binding.discard()
restored = existing_layer.getFeature(existing_id)
assert restored["name"] == "original"
assert restored.geometry().asPoint() == QgsPointXY(1, 1)
assert not existing_layer.isModified()
existing_binding.dispose()


def discard_new(uri, geometry):
    layer = QgsVectorLayer(uri, "new-discard", "memory")
    assert layer.startEditing()
    feature = QgsFeature(layer.fields())
    feature.setGeometry(geometry)
    assert layer.addFeature(feature)
    temporary_id = feature.id()
    form, page, binding = binding_for(layer, [field("name")], temporary_id)
    assert binding.has_pending_feature_edit()
    assert binding.discard()
    assert binding.feature_id is None
    assert page.feature_id is None
    assert layer.featureCount() == 0
    assert not layer.isModified()
    binding.dispose()
    return layer


discard_new(
    "Point?field=name:string",
    QgsGeometry.fromPointXY(QgsPointXY(2, 2)),
)
discard_new(
    "LineString?field=name:string",
    QgsGeometry.fromPolylineXY([QgsPointXY(0, 0), QgsPointXY(2, 2)]),
)


# Rolling back the current layer never touches another layer's pending edit.
other_layer = QgsVectorLayer("Point?field=name:string", "other", "memory")
assert other_layer.startEditing()
other_feature = QgsFeature(other_layer.fields())
other_feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(5, 5)))
assert other_layer.addFeature(other_feature)
current_layer = discard_new(
    "Point?field=name:string",
    QgsGeometry.fromPointXY(QgsPointXY(3, 3)),
)
assert not current_layer.isModified()
assert other_layer.isModified()
assert other_layer.featureCount() == 1
other_layer.rollBack()


# Regression: saving a changed existing date replaces the complete baseline;
# selecting another object must not compare the committed value to the old date.
date_layer = QgsVectorLayer("Point?field=date:date", "date-baseline", "memory")
date_feature = QgsFeature(date_layer.fields())
date_feature["date"] = QDate(2026, 10, 12)
date_feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(6, 6)))
assert date_layer.dataProvider().addFeature(date_feature)
date_id = next(date_layer.getFeatures()).id()
date_form, date_page, date_binding = binding_for(
    date_layer, [field("date", "date", "date")], date_id
)
date_form.handles["date"].editor.setDate(QDate(2026, 10, 8))
assert date_binding.has_actual_changes()
assert date_binding.save()
assert date_binding.original["date"] == "2026-10-08"
assert date_form.values()["date"] == "2026-10-08"
assert not date_binding.has_actual_changes()
assert not date_binding.has_pending_feature_edit()
date_binding.dispose()

null_date_layer = QgsVectorLayer("Point?field=date:date", "null-date", "memory")
null_date_feature = QgsFeature(null_date_layer.fields())
null_date_feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(7, 7)))
assert null_date_layer.dataProvider().addFeature(null_date_feature)
null_date_id = next(null_date_layer.getFeatures()).id()
null_date_form, _null_date_page, null_date_binding = binding_for(
    null_date_layer, [field("date", "date", "date")], null_date_id
)
assert null_date_form.values()["date"] is None
assert null_date_form.handles["date"].editor.specialValueText() == "선택"
assert not null_date_binding.has_actual_changes()
assert null_date_binding.save()
assert QgsVariantUtils.isNull(null_date_layer.getFeature(null_date_id)["date"])
null_date_binding.dispose()


# With unrelated edits in the same layer, only the current uncommitted new
# feature is removed; the other feature remains buffered.
shared_layer = QgsVectorLayer("Point?field=name:string", "shared", "memory")
assert shared_layer.startEditing()
first = QgsFeature(shared_layer.fields())
first.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(10, 10)))
second = QgsFeature(shared_layer.fields())
second.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(20, 20)))
assert shared_layer.addFeature(first)
assert shared_layer.addFeature(second)
_form, shared_page, shared_binding = binding_for(
    shared_layer, [field("name")], second.id()
)
assert shared_binding.discard()
assert shared_binding.feature_id is None
assert shared_page.feature_id is None
assert shared_layer.isModified()
assert set(shared_layer.editBuffer().addedFeatures()) == {first.id()}
shared_layer.rollBack()
shared_binding.dispose()


# New-feature system defaults establish the initial form baseline. They are
# written on first save without appearing as user edits, and the authoritative
# post-commit reload leaves the same form clean for navigation.
default_fields = [
    field("name"),
    field("worker_id", "text", "text"),
    field("survey_date", "date", "date"),
]
default_layer = QgsVectorLayer(
    "Point?field=name:string&field=worker_id:string&field=survey_date:date",
    "default-save", "memory",
)
assert default_layer.startEditing()
default_feature = QgsFeature(default_layer.fields())
default_feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(30, 30)))
assert default_layer.addFeature(default_feature)
default_form = DynamicForm({"fields": default_fields, "rules": []}, default_fields)
default_page = SimpleNamespace(note=QLabel(), dirty=False, feature_id=default_feature.id())
default_page.update_dirty = lambda: None
default_binding = DynamicFormBinding(
    default_page, default_layer, default_form, True,
    user_context={"worker_link_status": "linked", "worker_id": "worker-1"},
)
default_binding.load(default_layer.getFeature(default_feature.id()), force=True)
assert default_form.values()["worker_id"] == "worker-1"
assert default_form.values()["survey_date"] == QDate.currentDate().toString("yyyy-MM-dd")
assert not default_binding.has_actual_changes()
assert not default_binding.dirty
default_form.handles["name"].editor.insert("입력")
assert default_binding.has_actual_changes()
assert default_binding.save()
assert not default_binding.dirty
assert not default_page.dirty
assert not default_binding.has_pending_feature_edit()
assert not default_binding.has_actual_changes()
saved_default = default_layer.getFeature(default_binding.feature_id)
assert saved_default["worker_id"] == "worker-1"
assert saved_default["survey_date"].toString("yyyy-MM-dd") == QDate.currentDate().toString("yyyy-MM-dd")
assert default_form.values()["name"] == "입력"
# Geometry-only edits belong to the layer edit session and do not activate the
# per-object Dynamic Form navigation guard.
assert default_layer.changeGeometry(
    default_binding.feature_id,
    QgsGeometry.fromPointXY(QgsPointXY(31, 31)),
)
guard_host = SimpleNamespace(
    formStack=SimpleNamespace(currentWidget=lambda: default_page),
    save_button=SimpleNamespace(setText=lambda _text: None),
)
default_page.binding = default_binding
assert not DynamicFormHost._update_page_dirty(guard_host, default_page)
# A real form attribute edit still activates that guard.
default_form.handles["name"].editor.insert(" 후속")
assert default_binding.has_actual_changes()
assert DynamicFormHost._update_page_dirty(guard_host, default_page)
default_binding.dispose()


if isinstance(app, QgsApplication):
    app.exitQgis()
print("qgis form lifecycle smoke: OK")
