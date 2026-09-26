"""DB-free contract tests for the QGIS GIS-photo Phase 2 integration."""
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

    def test_form_host_appends_relation_section_below_dynamic_fields(self):
        source = (ROOT / "ui/form_host.py").read_text(encoding="utf-8")
        self.assertIn('PhotoSection', source)
        self.assertIn('page.form._root_layout.addWidget(page.photos)', source)
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


if __name__ == "__main__":
    unittest.main()
