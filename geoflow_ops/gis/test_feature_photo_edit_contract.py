"""Static safety contract for additive, non-destructive photo editing."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class FeaturePhotoEditContractTests(unittest.TestCase):
    def test_original_key_is_preserved_and_edited_key_is_separate(self):
        source = (ROOT / "geoflow_ops/gis/feature_photo_views.py").read_text(encoding="utf-8")
        self.assertIn("edited_object_key", source)
        self.assertIn("original_download_url", source)
        self.assertIn("display_download_url", source)
        self.assertIn("edit_presign", source)
        self.assertIn("edit_finalize", source)
        self.assertNotIn("SET object_key=", source)

    def test_tenant_migration_is_additive_and_has_no_drop_table(self):
        source = (ROOT / "geoflow_ops/migrations/0041_gis_feature_photo_edited_representation.py").read_text(encoding="utf-8")
        self.assertIn("ADD COLUMN IF NOT EXISTS edited_object_key", source)
        self.assertIn("edit_data jsonb", source)
        self.assertNotIn("DROP TABLE", source.upper())

    def test_deploy_requires_explicit_apply(self):
        source = (ROOT / "control/management/commands/deploy_gis_photo_phase3.py").read_text(encoding="utf-8")
        self.assertIn('parser.add_argument("--apply"', source)
        self.assertIn("Explicit --apply required", source)
        self.assertIn("tenant_cursor", source)
        workflow = (ROOT / ".github/workflows/gis-definition-code-deploy.yml").read_text(encoding="utf-8")
        self.assertIn("photo_phase3_required=yes", workflow)
        self.assertIn("deploy_gis_photo_phase3 --apply", workflow)


if __name__ == "__main__":
    unittest.main()
