"""Static contracts for bounded GIS master photos and private image metadata."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class FeaturePhotoMetadataContractTests(unittest.TestCase):
    def test_api_enforces_500kb_and_separates_metadata(self):
        source = (ROOT / "geoflow_ops/gis/feature_photo_views.py").read_text(encoding="utf-8")
        self.assertIn("_MAX_NORMALIZED_BYTES = 500 * 1024", source)
        self.assertIn("image_metadata", source)
        self.assertIn("extra_data,image_metadata", source)
        self.assertIn("_public_image_metadata", source)
        self.assertIn("replace_presign", source)
        self.assertIn("replace_finalize", source)
        self.assertIn("edited_object_key=NULL", source)

    def test_migration_is_additive_and_deploy_is_explicit(self):
        migration = (ROOT / "geoflow_ops/migrations/0042_gis_feature_photo_image_metadata.py").read_text(encoding="utf-8")
        self.assertIn("ADD COLUMN IF NOT EXISTS image_metadata", migration)
        self.assertNotIn("DROP TABLE", migration.upper())
        command = (ROOT / "control/management/commands/deploy_gis_photo_phase4.py").read_text(encoding="utf-8")
        self.assertIn('parser.add_argument("--apply"', command)
        workflow = (ROOT / ".github/workflows/gis-definition-code-deploy.yml").read_text(encoding="utf-8")
        self.assertIn("photo_phase4_required=yes", workflow)
        self.assertIn("deploy_gis_photo_phase4 --apply", workflow)


if __name__ == "__main__":
    unittest.main()
