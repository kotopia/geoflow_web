"""DB-free contract tests for the QGIS GIS-photo Phase 3 integration."""
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parent


class PhotoPhase2ContractTests(unittest.TestCase):
    def test_manifest_policy_is_revision_cached_and_same_origin(self):
        source = (ROOT / "api/photos.py").read_text(encoding="utf-8")
        self.assertIn('photo_policy_revision', source)
        self.assertIn('CACHE_PREFIX = "GeoFlowConnector/photoPolicies/"', source)
        self.assertIn('(base.scheme, base.netloc)', source)
        self.assertIn('photo_policy_revision_mismatch', source)
        self.assertIn('ready project_id=', source)

    def test_photo_ui_uses_gis_api_without_aws_credentials_or_ops_attachments(self):
        source = (ROOT / "ui/photo_section.py").read_text(encoding="utf-8")
        self.assertIn('/api/layers/{layer_id}/features/{self.feature_uuid}/photos/', source)
        self.assertIn('put_presigned_bytes', source)
        self.assertIn('"action": "finalize"', source)
        self.assertIn('delete_json', source)
        for forbidden in ('AWS_ACCESS_KEY', 'AWS_SECRET_ACCESS_KEY', 'ops.attachments'):
            self.assertNotIn(forbidden, source)

    def test_catalogue_selection_is_local_not_feature_ext_data(self):
        binding = (ROOT / "forms/dynamic/binding.py").read_text(encoding="utf-8")
        section = (ROOT / "ui/photo_section.py").read_text(encoding="utf-8")
        self.assertNotIn("pending_capture_mode", binding)
        self.assertNotIn('photo["capture_mode"]', binding)
        self.assertIn("GeoFlowConnector/photoLastSelection/", section)
        self.assertIn('settings.setValue(prefix + "template_id"', section)
        self.assertIn('settings.setValue(prefix + "variant_id"', section)

    def test_form_host_places_photos_in_policy_gated_dedicated_tab(self):
        source = (ROOT / "ui/form_host.py").read_text(encoding="utf-8")
        self.assertIn('PhotoSection', source)
        self.assertIn('page.tabs = page.form.tabs', source)
        self.assertIn('page.form.add_auxiliary_tab(page.photos, "사진", visible=False)', source)
        self.assertIn('p.form.set_auxiliary_tab_visible(p.photos, visible)', source)
        self.assertIn('availabilityChanged.connect', source)
        self.assertIn('page.photos.set_feature(feature)', source)

    def test_async_policy_ready_refreshes_current_feature_without_form_rebuild(self):
        host = (ROOT / "ui/form_host.py").read_text(encoding="utf-8")
        section = (ROOT / "ui/photo_section.py").read_text(encoding="utf-8")
        self.assertIn("changed.connect(self._photo_policy_changed)", host)
        self.assertIn("page.photos.refresh_policy()", host)
        self.assertIn("page.feature_id is None", host)
        self.assertNotIn("photo_signature", host)
        self.assertIn('if state in {"idle", "loading"}:', section)
        self.assertIn('if state == "error":', section)
        self.assertIn('if state == "unavailable":', section)
        self.assertIn("service_project_id != active_project_id", section)

    def test_policy_states_control_tab_selectors_and_retry(self):
        source = (ROOT / "ui/photo_section.py").read_text(encoding="utf-8")
        self.assertIn("사진 정책을 불러오는 중입니다.", source)
        self.assertIn("이 레이어에 적용된 사진 정책이 없습니다.", source)
        self.assertIn("사진 정책을 불러오지 못했습니다.", source)
        ui = (ROOT / "ui/forms/photo_tab.ui").read_text(encoding="utf-8")
        self.assertIn("다시 시도", ui)
        self.assertIn("self.template_select", source)
        self.assertIn("self.variant_select", source)

    def test_layer_uuid_and_visibility_are_runtime_diagnosable(self):
        source = (ROOT / "ui/photo_section.py").read_text(encoding="utf-8")
        self.assertIn("definition_layer_id", source)
        self.assertIn("policy_found=", source)
        self.assertIn("visible=", source)

    def test_variant_selection_is_remembered_and_uploads_are_bounded(self):
        source = (ROOT / "ui/photo_section.py").read_text(encoding="utf-8")
        self.assertIn("def _template_changed", source)
        self.assertIn("def _variant_changed", source)
        self.assertIn("self._remember_selection()", source)
        self.assertIn("normalize_photo(path)", source)
        self.assertIn('{"decimal", "number"}', source)
        self.assertIn("저장 대기 중입니다", source)
        self.assertIn('"template_id": operation["template_id"]', source)
        self.assertIn('"variant_id": operation["variant_id"]', source)

    def test_feature_scoped_quick_capture_and_pending_reclassification(self):
        header = (ROOT / "ui/form_header.py").read_text(encoding="utf-8")
        section = (ROOT / "ui/photo_section.py").read_text(encoding="utf-8")
        host = (ROOT / "ui/form_host.py").read_text(encoding="utf-8")
        self.assertIn("QToolButton.ToolButtonPopupMode.MenuButtonPopup", header)
        self.assertIn("bind_action_button(page.header.photoButton)", host)
        self.assertIn("def quick_capture(self):", section)
        self.assertIn("next_photo_slot", section)
        self.assertIn("def reclassify_pending", section)
        self.assertIn("사진 파일은 유지하고 분류만 변경했습니다.", section)
        self.assertIn("self._set_available(self._tab_needed())", section)

    def test_responsive_cards_internal_viewer_and_editor_are_used(self):
        section = (ROOT / "ui/photo_section.py").read_text(encoding="utf-8")
        tab = (ROOT / "ui/forms/photo_tab.ui").read_text(encoding="utf-8")
        self.assertIn("ResponsivePhotoLabel", section)
        self.assertIn("display_download_url", section)
        self.assertIn("PhotoStudioDialog", section)
        self.assertNotIn("QDesktopServices", section)
        self.assertIn("ScrollBarAlwaysOff", tab)
        editor = (ROOT / "ui/photo_studio.py").read_text(encoding="utf-8")
        self.assertIn("ScrollHandDrag", editor)
        self.assertIn("wheelEvent", editor)
        for tool in ('"line"', '"arrow"', '"rectangle"', '"ellipse"', '"text"'):
            if tool != '"arrow"':
                self.assertIn(tool, editor)
        self.assertIn("undo_stack", editor)
        self.assertIn("redo_stack", editor)

    def test_icons_are_centralized_and_edits_upload_from_memory(self):
        icons = (ROOT / "ui/photo_icons.py").read_text(encoding="utf-8")
        self.assertIn("ICON_NAMES", icons)
        self.assertIn('"location"', icons)
        self.assertIn('f"number_{n}"', icons)
        client = (ROOT / "api/client.py").read_text(encoding="utf-8")
        self.assertIn("def put_presigned_bytes", client)
        section = (ROOT / "ui/photo_section.py").read_text(encoding="utf-8")
        self.assertIn('"action": "edit_presign"', section)
        self.assertIn('"action": "edit_finalize"', section)

    def test_phase4_ui_shells_and_photo_studio_contract(self):
        tab = ROOT / "ui/forms/photo_tab.ui"
        studio_ui = ROOT / "ui/forms/photo_studio.ui"
        ET.parse(tab)
        studio_tree = ET.parse(studio_ui)
        tab_text = tab.read_text(encoding="utf-8")
        self.assertIn('name="templateCombo"', tab_text)
        self.assertIn('name="variantCombo"', tab_text)
        self.assertIn('name="managerButton"', tab_text)
        self.assertIn('name="cardsScrollArea"', tab_text)
        self.assertIn("ScrollBarAlwaysOff", tab_text)
        dialog = studio_tree.find("./widget[@class='QDialog']")
        self.assertIsNotNone(dialog)
        property_names = {
            element.get("name") for element in dialog.findall("./property")
        }
        self.assertIn("geometry", property_names)
        self.assertNotIn("size", property_names)
        studio = (ROOT / "ui/photo_studio.py").read_text(encoding="utf-8")
        for tool in ('"line"', '"polyline"', '"freehand"', '"rectangle"', '"ellipse"', '"text"'):
            self.assertIn(tool, studio)
        self.assertIn("QTimer.singleShot(0, self.fit_to_window)", studio)
        self.assertIn("annotation_icon(name)", studio)
        section = (ROOT / "ui/photo_section.py").read_text(encoding="utf-8")
        self.assertIn('feather_icon("camera")', section)

    def test_photo_studio_fixed_toolbar_is_designer_owned(self):
        ui = (ROOT / "ui/forms/photo_studio.ui").read_text(encoding="utf-8")
        studio = (ROOT / "ui/photo_studio.py").read_text(encoding="utf-8")
        buttons = (
            "btnPrevious", "btnNext", "btnZoomIn", "btnZoomOut", "btnFit",
            "btnActualSize", "btnSelect", "btnPan", "btnLine", "btnRectangle",
            "btnEllipse", "btnText", "btnIcon", "btnRotateLeft",
            "btnRotateRight", "btnUndo", "btnRedo",
        )
        for name in buttons:
            self.assertIn(f'name="{name}"', ui)
        self.assertIn("Wire the fixed Designer widgets", studio)
        self.assertIn("self._setup_line_menu()", studio)
        self.assertIn("self._setup_icon_menu()", studio)

    def test_expired_photo_urls_do_not_reclassify_normal_api_forbidden(self):
        client = (ROOT / "api/client.py").read_text(encoding="utf-8")
        studio = (ROOT / "ui/photo_studio.py").read_text(encoding="utf-8")
        self.assertIn("class GeoFlowPresignedUrlExpired", client)
        self.assertIn("def is_presigned_url_expired", client)
        self.assertIn("not same_origin and is_presigned_url_expired", client)
        self.assertIn("GeoFlow 연결 세션이 만료되었습니다.", studio)
        self.assertIn("if not self.session_expired:", studio)
        self.assertIn("self._allow_reject = True", studio)

    def test_phase5_annotations_are_persistent_and_reeditable(self):
        studio = (ROOT / "ui/photo_studio.py").read_text(encoding="utf-8")
        annotations = (ROOT / "ui/photo_annotations.py").read_text(encoding="utf-8")
        handles = (ROOT / "ui/photo_annotation_handles.py").read_text(encoding="utf-8")
        ui = (ROOT / "ui/forms/photo_studio.ui").read_text(encoding="utf-8")
        self.assertIn('"format": "annotation-json"', annotations)
        self.assertIn("is_editable_document(edit_data)", studio)
        self.assertIn("restore_state(document)", studio)
        self.assertIn("annotation_state()", studio)
        self.assertIn("ItemIsSelectable", annotations)
        self.assertIn("ItemIsMovable", annotations)
        self.assertIn("ItemIgnoresTransformations", handles)
        self.assertIn("delete_vertex", annotations)
        self.assertIn("add_vertex", annotations)
        self.assertIn('name="propertyPanel"', ui)
        self.assertIn("기존 raster 편집본", studio)

    def test_phase5_undo_render_and_original_are_separate(self):
        studio = (ROOT / "ui/photo_studio.py").read_text(encoding="utf-8")
        self.assertIn("self.undo_stack.append(before)", studio)
        self.assertIn("self.redo_stack.append(self.annotation_state())", studio)
        self.assertIn("self._photo_pixmap(photo, \"original\")", studio)
        self.assertIn('document["render"]', studio)
        self.assertIn("encode_qimage(self.render_image())", studio)

    def test_phase6_object_session_queues_photos_until_top_save(self):
        section = (ROOT / "ui/photo_section.py").read_text(encoding="utf-8")
        host = (ROOT / "ui/form_host.py").read_text(encoding="utf-8")
        for queue in ("pending_add", "pending_replace", "pending_edit", "pending_delete"):
            self.assertIn(queue, section)
        self.assertIn("def commit_pending(self):", section)
        self.assertIn("def discard_pending", section)
        self.assertIn("page.photos.commit_pending()", host)
        self.assertIn("현재 객체 저장", host)
        self.assertIn("저장 후 이동", host)
        self.assertIn("변경 취소 후 이동", host)
        self.assertIn("계속 편집", host)
        upload_draft = section.split("def upload(self, slot, extras):", 1)[1].split(
            "def delete_photo", 1
        )[0]
        edit_draft = section.split("def _save_edit", 1)[1].split(
            "def replace_photo_dialog", 1
        )[0]
        replace_draft = section.split("def _replace_photo", 1)[1].split(
            "def upload", 1
        )[0]
        for draft in (upload_draft, edit_draft, replace_draft):
            self.assertNotIn("post_json", draft)
            self.assertNotIn("put_presigned_bytes", draft)

    def test_phase6_studio_visibility_shift_and_handles(self):
        studio = (ROOT / "ui/photo_studio.py").read_text(encoding="utf-8")
        handles = (ROOT / "ui/photo_annotation_handles.py").read_text(encoding="utf-8")
        self.assertIn("self.propertyPanel.setVisible(False)", studio)
        self.assertIn("self.propertyPanel.setVisible(visible)", studio)
        self.assertIn("Qt.KeyboardModifier.ShiftModifier", studio)
        self.assertIn("size = max(abs(dx), abs(dy))", studio)
        self.assertIn("편집 적용", studio)
        self.assertIn("적용 후 닫기", studio)
        self.assertIn('self.role == "vertex"', handles)
        self.assertIn('self.role == "rotate"', handles)
        self.assertIn("SizeFDiagCursor", handles)

    def test_phase4_normalization_exif_and_replace_contract(self):
        normalizer = (ROOT / "ui/photo_normalizer.py").read_text(encoding="utf-8")
        self.assertIn("MAX_PHOTO_BYTES = 500 * 1024", normalizer)
        self.assertIn("LONG_EDGE = 1920", normalizer)
        self.assertIn("ImageOps.exif_transpose", normalizer)
        self.assertIn('"GPSLatitude"', normalizer)
        self.assertIn('"GPSImgDirection"', normalizer)
        section = (ROOT / "ui/photo_section.py").read_text(encoding="utf-8")
        self.assertIn('"action": "replace_presign"', section)
        self.assertIn('"action": "replace_finalize"', section)
        self.assertIn('"image_metadata": normalized.image_metadata', section)

    def test_feather_icons_are_compiled_and_packaged(self):
        qrc = (ROOT / "resources/feather.qrc").read_text(encoding="utf-8")
        compiled = ROOT / "resources/feather_rc.py"
        self.assertTrue(compiled.is_file())
        for icon in ("zoom-in", "zoom-out", "maximize", "target", "rotate-ccw",
                     "rotate-cw", "trash-2", "edit-2", "refresh-cw", "save",
                     "corner-up-left", "corner-up-right", "type", "square", "circle"):
            self.assertIn(f'alias="{icon}.svg"', qrc)


if __name__ == "__main__":
    unittest.main()
