"""QGIS 4 runtime regression checks for varchar code-backed checkboxes."""
import sys
from pathlib import Path
from types import SimpleNamespace

from qgis.PyQt.QtWidgets import QLabel
from qgis.core import QgsApplication, QgsFeature, QgsVariantUtils, QgsVectorLayer

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from geoflow_connector.forms.dynamic.binding import DynamicFormBinding, canonical_value
from geoflow_connector.forms.dynamic.boolean_codes import boolean_code_values
from geoflow_connector.forms.dynamic.form import DynamicForm
from geoflow_connector.forms.dynamic.rules import validate


APP = QgsApplication.instance() or QgsApplication([], False)
APP.initQgis()

STANDARDS = (
    "WTL_PIPE_PS", "WTL_PIPE_LM", "WTL_MANH_PS", "WTL_VALV_PS",
    "WTL_FIRE_PS", "WTL_FLOW_PS", "WTL_ETC_PS", "WTL_SPLY_LS",
)


def status_field(standard, *, storage_type="character varying", codes=True):
    return {
        "id": f"{standard.lower()}-status",
        "field_name": "status",
        "layer_standard_name": standard,
        "semantic_data_type": "boolean",
        "widget_type": "boolean",
        "label": "작업상태",
        "visible": True,
        "required": False,
        "readonly": False,
        "display_order": 1,
        "layout": {},
        "reference_codes": ([
            {"id": "status-off", "value": "미완료", "label": "미완료", "order": 1},
            {"id": "status-on", "value": "완료", "label": "완료", "order": 2},
        ] if codes else []),
        "storage": {"kind": "column", "key": "status", "data_type": storage_type},
    }


def binding_for(layer, field, feature_id):
    definition = {"fields": [field], "rules": []}
    form = DynamicForm(definition, [field], layer=field["layer_standard_name"])
    page = SimpleNamespace(note=QLabel(), dirty=False, feature_id=feature_id)
    page.update_dirty = lambda: None
    binding = DynamicFormBinding(page, layer, form, True)
    binding.load(layer.getFeature(feature_id), force=True)
    return form, page, binding


def add_feature(layer, value):
    feature = QgsFeature(layer.fields())
    feature.setAttribute("status", value)
    assert layer.dataProvider().addFeature(feature)
    return max(candidate.id() for candidate in layer.getFeatures())


# The mapping is ordered by the already-normalized central sort order. Raw
# checkbox booleans are canonicalized before reference-code validation.
probe = status_field(STANDARDS[0])
assert boolean_code_values(probe) == ("미완료", "완료")
fallback_probe = status_field(STANDARDS[0], storage_type="")
assert boolean_code_values(fallback_probe) == ("미완료", "완료")
assert canonical_value(probe, False) == "미완료"
assert canonical_value(probe, True) == "완료"
assert validate({"fields": [probe], "rules": []}, [probe], {probe["id"]: False}) == []
assert validate({"fields": [probe], "rules": []}, [probe], {probe["id"]: True}) == []
assert validate({"fields": [probe], "rules": []}, [probe], {probe["id"]: None}) == []


def save_new_status(clicks):
    field = status_field("WTL_PIPE_PS")
    layer = QgsVectorLayer("Point?field=status:string", "new-status", "memory")
    assert layer.startEditing()
    feature = QgsFeature(layer.fields())
    assert layer.addFeature(feature)
    form, _page, binding = binding_for(layer, field, feature.id())
    editor = form.handles[field["id"]].editor
    for _ in range(clicks):
        editor.click()
    assert binding.save()
    saved = next(layer.getFeatures())["status"]
    binding.dispose()
    return saved


# New feature: untouched NULL, explicit OFF, and explicit ON.
assert QgsVariantUtils.isNull(save_new_status(0))
assert save_new_status(2) == "미완료"
assert save_new_status(1) == "완료"


for standard in STANDARDS:
    field = status_field(standard)
    layer = QgsVectorLayer("Point?field=status:string", standard, "memory")

    null_id = add_feature(layer, None)
    incomplete_id = add_feature(layer, "미완료")
    complete_id = add_feature(layer, "완료")

    # Existing NULL is visually unchecked but remains NULL while untouched.
    form, _page, binding = binding_for(layer, field, null_id)
    editor = form.handles[field["id"]].editor
    assert not editor.isChecked()
    assert form.values()[field["id"]] is None
    assert binding.save()
    assert QgsVariantUtils.isNull(layer.getFeature(null_id)["status"])

    # Explicit OFF means the user interacted, even though the final visual
    # state is the same as the initial NULL representation.
    editor.click()
    editor.click()
    assert binding.save()
    assert layer.getFeature(null_id)["status"] == "미완료"
    binding.dispose()

    # Existing code values reverse-map correctly and round-trip unchanged.
    form, _page, binding = binding_for(layer, field, incomplete_id)
    editor = form.handles[field["id"]].editor
    assert not editor.isChecked()
    assert form.values()[field["id"]] == "미완료"
    assert binding.save()
    assert layer.getFeature(incomplete_id)["status"] == "미완료"
    editor.click()
    assert binding.save()
    assert layer.getFeature(incomplete_id)["status"] == "완료"
    binding.dispose()

    form, _page, binding = binding_for(layer, field, complete_id)
    editor = form.handles[field["id"]].editor
    assert editor.isChecked()
    assert form.values()[field["id"]] == "완료"
    assert binding.save()
    assert layer.getFeature(complete_id)["status"] == "완료"
    editor.click()
    assert binding.save()
    assert layer.getFeature(complete_id)["status"] == "미완료"
    binding.dispose()


# A real boolean storage field remains a normal True/False checkbox, even if
# its physical name happens to be status. It never receives Korean code text.
boolean_field = status_field("BOOL_TEST", storage_type="boolean", codes=True)
assert boolean_code_values(boolean_field) is None
boolean_layer = QgsVectorLayer("Point?field=status:boolean", "BOOL_TEST", "memory")
boolean_id = add_feature(boolean_layer, False)
boolean_form, _page, boolean_binding = binding_for(
    boolean_layer, boolean_field, boolean_id
)
boolean_editor = boolean_form.handles[boolean_field["id"]].editor
assert boolean_form.values()[boolean_field["id"]] is False
boolean_editor.click()
assert boolean_binding.save()
assert boolean_layer.getFeature(boolean_id)["status"] is True
boolean_binding.dispose()

print("qgis boolean code runtime: OK")
