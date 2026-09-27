"""DB-free contract tests for the QGIS GIS-photo Phase 3 integration."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent


class PhotoPhase2ContractTests(unittest.TestCase):
    def test_manifest_policy_is_revision_cached_and_same_origin(self):
        source = (ROOT / "api/photos.py").read_text(encoding="utf-8")
        self.assertIn('photo_policy_revision', source)
        self.assertIn('CACHE_PREFIX = "GeoFlowConnector/photoPolicies/"', source)
        self.assertIn('(base.scheme, base.netloc)', source)
        self.assertIn('photo_policy_revision_mismatch', source)
        self.assertIn('fetch_ready revision=', source)

    def test_photo_ui_uses_gis_api_without_aws_credentials_or_ops_attachments(self):
        source = (ROOT / "ui/photo_section.py").read_text(encoding="utf-8")
        self.assertIn('/api/layers/{layer_id}/features/{self.feature_uuid}/photos/', source)
        self.assertIn('put_presigned_file', source)
        self.assertIn('"action": "finalize"', source)
        self.assertIn('delete_json', source)
        for forbidden in ('AWS_ACCESS_KEY', 'AWS_SECRET_ACCESS_KEY', 'ops.attachments'):
            self.assertNotIn(forbidden, source)

    def test_capture_mode_is_stored_in_official_ext_data_key(self):
        source = (ROOT / "forms/dynamic/binding.py").read_text(encoding="utf-8")
        self.assertIn('photo["capture_mode"] = mode', source)
        self.assertIn('extension["photo"] = photo', source)
        self.assertIn('{"DIRECT", "INDIRECT", "GENERAL"}', source)

    def test_form_host_places_photos_in_policy_gated_dedicated_tab(self):
        source = (ROOT / "ui/form_host.py").read_text(encoding="utf-8")
        self.assertIn('PhotoSection', source)
        self.assertIn('page.tabs.addTab(scroll, "기본정보")', source)
        self.assertIn('page.photo_tab_index = page.tabs.addTab(photo_scroll, "사진")', source)
        self.assertIn('setTabVisible(page.photo_tab_index, False)', source)
        self.assertIn('availabilityChanged.connect', source)
        self.assertIn('page.photos.set_feature(feature)', source)

    def test_layer_uuid_and_visibility_are_runtime_diagnosable(self):
        source = (ROOT / "ui/photo_section.py").read_text(encoding="utf-8")
        self.assertIn("definition_layer_id", source)
        self.assertIn("policy_found=", source)
        self.assertIn("visible=", source)

    def test_mode_switch_protects_unsaved_form_and_uploads_are_bounded(self):
        source = (ROOT / "ui/photo_section.py").read_text(encoding="utf-8")
        self.assertIn("binding.has_actual_changes()", source)
        self.assertIn("25 * 1024 * 1024", source)
        self.assertIn('{"decimal", "number"}', source)
        self.assertIn("저장 후 변경", source)
        self.assertIn("기존 사진 보존", source)
        self.assertIn("기존 사진 삭제 후 변경", source)

    def test_responsive_cards_internal_viewer_and_editor_are_used(self):
        section = (ROOT / "ui/photo_section.py").read_text(encoding="utf-8")
        host = (ROOT / "ui/form_host.py").read_text(encoding="utf-8")
        self.assertIn("ResponsivePhotoLabel", section)
        self.assertIn("display_download_url", section)
        self.assertIn("PhotoViewerDialog", section)
        self.assertIn("PhotoEditorDialog", section)
        self.assertNotIn("QDesktopServices", section)
        self.assertIn("ScrollBarAlwaysOff", host)
        viewer = (ROOT / "ui/photo_viewer.py").read_text(encoding="utf-8")
        self.assertIn("ScrollHandDrag", viewer)
        self.assertIn("wheelEvent", viewer)
        editor = (ROOT / "ui/photo_editor.py").read_text(encoding="utf-8")
        for tool in ('"line"', '"arrow"', '"rect"', '"ellipse"', '"text"'):
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


if __name__ == "__main__":
    unittest.main()
