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
        # Editing never overwrites the original. Explicit photo replacement is
        # a separate confirmed action and writes a new immutable object key.
        self.assertIn("_replacement_key", source)
        self.assertIn('action in {"replace_presign", "replace_finalize"}', source)

    def test_annotation_edit_data_is_validated_without_new_schema(self):
        source = (ROOT / "geoflow_ops/gis/feature_photo_views.py").read_text(encoding="utf-8")
        validator = (ROOT / "geoflow_ops/gis/photo_edit_data.py").read_text(encoding="utf-8")
        self.assertIn("validate_edit_data", source)
        self.assertIn("MAX_ANNOTATIONS = 200", validator)
        self.assertIn("MAX_POINTS = 2000", validator)
        self.assertIn('format_name == "raster-jpeg"', validator)
        self.assertIn('format_name != "annotation-json"', validator)

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
