"""QGIS 4.2.2 offscreen regression proof for Photo Policy-driven tabs."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QApplication, QLabel
from qgis.core import QgsApplication, QgsFeature, QgsVectorLayer, Qgis

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from geoflow_connector.forms.dynamic.form import DynamicForm
from geoflow_connector.forms.dynamic.layout_model import central_photo_tab_spec
from geoflow_connector.ui.form_actions import FormActionToolbar
from geoflow_connector.ui.form_host import Main as FormHost
from geoflow_connector.ui.photo_section import PhotoSection


APP = QApplication.instance() or QgsApplication([], False)
if isinstance(APP, QgsApplication):
    APP.initQgis()


def field(name, order, *, widget="text", tab="기본정보", storage=None):
    return {
        "id": name, "field_name": name, "label": "사진" if widget == "photo" else name,
        "layer_standard_name": "WTL_PIPE_PS", "semantic_data_type": widget,
        "widget_type": widget, "visible": True, "required": False,
        "readonly": False, "display_order": order,
        "layout": {"tab": tab, "section": "속성"}, "reference_codes": [],
        "storage": storage or {"kind": "column", "key": name},
    }


basic = field("pip_dep", 1)
photo = field(
    "facility_photos", 2, widget="photo", tab="사진",
    storage={"kind": "ops.attachments"},
)
policy = {
    "allow_extra_photo": True,
    "templates": [{
        "id": "template", "name": "상수심도",
        "variants": [{"id": "default", "name": "기본", "slots": []}],
    }],
}

layer = QgsVectorLayer("Point?field=id:string&field=pip_dep:double", "상수심도", "memory")
layer.setCustomProperty("geoflow/managed", True)
layer.setCustomProperty("geoflow/definition_layer_id", "depth-layer")
layer.setCustomProperty("geoflow/standard_name", "WTL_PIPE_PS")


def add_feature(depth):
    row = QgsFeature(layer.fields())
    row["id"] = str(uuid4())
    row["pip_dep"] = depth
    assert layer.dataProvider().addFeature(row)
    return next(candidate for candidate in layer.getFeatures() if candidate["id"] == row["id"])


feature = add_feature(1.024)


def make_case(fields, photos):
    """Build the same managed-layer auxiliary-tab wiring used by FormHost."""
    client = Mock()
    client.get_json.return_value = {"photos": list(photos)}
    service = SimpleNamespace(
        state="ready", project_id="project", revision="runtime",
        policy=lambda layer_id: policy if layer_id == "depth-layer" else None,
    )
    plugin = SimpleNamespace(
        active_context={"manifest": {"project": {"id": "project"}}},
        active_client=client, _photo_policy_service=service,
        iface=SimpleNamespace(
            messageBar=lambda: SimpleNamespace(pushMessage=lambda *args, **kwargs: None)
        ),
    )
    form = DynamicForm({"fields": fields, "rules": []}, fields, layer="WTL_PIPE_PS")
    header = FormActionToolbar(form)
    header.set_layer_title("상수심도")
    form.set_header_widget(header)
    page = SimpleNamespace(
        form=form, tabs=form.tabs, note=QLabel(), standard="WTL_PIPE_PS",
        binding=SimpleNamespace(can_save=True, feature_id=feature.id()),
        update_dirty=lambda: None,
    )
    section = PhotoSection(plugin, page, layer, form.tabs)
    page.photos = section
    spec = central_photo_tab_spec(fields)
    metadata = spec or {"title": "사진", "index": None}
    index = form.add_auxiliary_tab(
        section, metadata["title"], visible=False, index=metadata["index"]
    )
    section.tabNeededChanged.connect(
        lambda needed, p=page: FormHost._sync_photo_tab(p, needed)
    )
    section.bind_action_button(header.photoButton)
    return SimpleNamespace(
        client=client, plugin=plugin, form=form, header=header, page=page,
        section=section, spec=spec, initial_index=index,
    )


existing_photo = {"id": str(uuid4()), "original_name": "existing.jpg"}

# Case A: no Final Form photo field, but policy + one server photo shows the fallback tab.
case_a = make_case([basic], [existing_photo])
case_a.section.set_feature(feature)
case_a.form.resize(560, 720)
case_a.form.show()
APP.processEvents()
case_a_index = case_a.form.tabs.indexOf(case_a.section)
assert case_a.spec is None
assert case_a.form.tabs.count() == 2
assert case_a_index >= 0 and case_a.form.tabs.tabText(case_a_index) == "사진"
assert case_a.form.tabs.isTabVisible(case_a_index)
assert len(case_a.section.photos) == 1
assert case_a.section.photoCountLabel.text() == "사진 1장"

# Header geometry remains compact and the Photo Policy icon is available.
buttons = [
    case_a.header.saveButton, case_a.header.previousButton, case_a.header.nearbyButton,
    case_a.header.layoutButton, case_a.header.referenceRefreshButton,
    case_a.header.photoButton,
]
assert case_a.header.isVisible() and case_a.header.height() == 32
assert all(button.isVisible() and not button.isHidden() for button in buttons)
assert all(button.width() == 28 and button.height() == 28 for button in buttons)
assert case_a.header.photoButton.isEnabled()
assert case_a.form.tabs.cornerWidget(Qt.Corner.TopRightCorner) is None

with patch("geoflow_connector.ui.form_host.QgsMessageLog.logMessage") as photo_log:
    FormHost._log_photo_runtime(
        case_a.page, has_photo_capability=True, photo_tab=None,
        tab_count_before=1, stage="runtime-test",
    )
photo_message = photo_log.call_args.args[0]
assert all(token in photo_message for token in (
    "[PHOTO]", "layer=wtl_pipe_ps", "definition_photo_section=false",
    "policy_found=yes", "tab_needed=true", "tab_visible=true",
    "photo_tab_index=1", "existing_photos=1",
)), photo_message

# A local form-layout rebuild must retain the fallback auxiliary tab and state.
case_a.form.set_form_layout({
    "version": 1, "layer": "WTL_PIPE_PS",
    "tabs": [{
        "title": "기본정보",
        "groups": [{"title": "속성", "rows": [["pip_dep"]]}],
    }],
})
APP.processEvents()
assert case_a.form.tabs.indexOf(case_a.section) == case_a_index
assert case_a.form.tabs.isTabVisible(case_a_index)

# Case B: no Final Form photo field + policy + zero photos keeps the tab hidden.
case_b = make_case([basic], [])
case_b.section.set_feature(feature)
case_b.form.show()
APP.processEvents()
case_b_index = case_b.form.tabs.indexOf(case_b.section)
assert case_b_index >= 0
assert not case_b.form.tabs.isTabVisible(case_b_index)
assert case_b.header.photoButton.isVisible() and case_b.header.photoButton.isEnabled()

# Case C: short-click capture creates pending_add, shows the tab, and selects it.
def queue_pending(_slot):
    case_b.section.pending_add.append({
        "local_id": "pending:" + str(uuid4()),
        "template_id": None, "variant_id": None, "slot_id": None,
        "title": "", "note": "", "original_name": "pending.jpg",
        "extra_data": {}, "data": b"not-an-image",
    })
    case_b.section._notify_dirty()
    case_b.section.render()
    case_b.section._select_dynamic_tab()


case_b.section._capture_slot = queue_pending
case_b.header.photoButton.click()
APP.processEvents()
assert len(case_b.section.pending_add) == 1
assert case_b.form.tabs.isTabVisible(case_b_index)
assert case_b.form.tabs.currentIndex() == case_b_index

# Manager action also exposes and selects the existing auxiliary tab.
case_b.section.pending_add.clear()
case_b.section.extra_section_open = False
case_b.section.render()
assert not case_b.form.tabs.isTabVisible(case_b_index)
case_b.section.open_manager()
APP.processEvents()
assert case_b.form.tabs.isTabVisible(case_b_index)
assert case_b.form.tabs.currentIndex() == case_b_index

# Case D: a fresh form (restart equivalent) reselects and reloads the existing photo.
case_d = make_case([basic], [existing_photo])
case_d.section.set_feature(feature)
APP.processEvents()
case_d_index = case_d.form.tabs.indexOf(case_d.section)
assert case_d.form.tabs.isTabVisible(case_d_index)
assert len(case_d.section.photos) == 1

# Async policy refresh also re-synchronizes visibility for the selected feature.
case_d.form.set_auxiliary_tab_visible(case_d.section, False)
assert not case_d.form.tabs.isTabVisible(case_d_index)
case_d.section.refresh_policy()
FormHost._sync_photo_tab(case_d.page)
assert case_d.form.tabs.isTabVisible(case_d_index)

# Case E: an explicit Final Form photo field still supplies its title and index.
case_e = make_case([basic, photo], [existing_photo])
assert case_e.spec == {"title": "사진", "index": 1}
case_e.section.set_feature(feature)
APP.processEvents()
case_e_index = case_e.form.tabs.indexOf(case_e.section)
assert case_e_index == 1
assert case_e.form.tabs.tabText(case_e_index) == "사진"
assert case_e.form.tabs.isTabVisible(case_e_index)

artifact = Path(__file__).resolve().parents[1] / "test_artifacts" / "form_header_photo_qgis422.png"
artifact.parent.mkdir(exist_ok=True)
assert case_a.form.grab().save(str(artifact))

result = {
    "qgis_version": Qgis.QGIS_VERSION,
    "cases": {
        "A": {"photo_field": False, "photos": 1, "visible": True},
        "B": {"photo_field": False, "photos": 0, "visible": False},
        "C": {"pending": 1, "visible": True, "selected": True},
        "D": {"restart_existing": 1, "visible": True},
        "E": {"explicit_index": case_e_index, "title": "사진", "visible": True},
    },
    "photo_log": photo_message,
    "artifact": str(artifact),
}
print("qgis form header/photo runtime: " + json.dumps(result, ensure_ascii=False))
