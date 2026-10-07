from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]


class FeaturePhotoCatalogV2ContractTests(TestCase):
    def test_tenant_columns_and_all_three_or_none_server_validation(self):
        migration = (ROOT / "migrations/0043_gis_feature_photo_catalog_v2.py").read_text()
        view = (ROOT / "gis/feature_photo_views.py").read_text()
        for column in ("template_id", "variant_id", "title"):
            self.assertIn(f"ADD COLUMN IF NOT EXISTS {column}", migration)
        self.assertIn("def _selection", view)
        self.assertIn("Template, Variant, 사진 항목을 모두 선택하세요.", view)
        self.assertIn("template_id,variant_id,slot_id,title", view)

    def test_extra_photo_has_nullable_catalogue_ids_and_title_note(self):
        view = (ROOT / "gis/feature_photo_views.py").read_text()
        self.assertIn("return None, None, None", view)
        self.assertIn('_postgres_text(body.get("title") or "")[:200]', view)
        self.assertIn('str(body.get("note") or "")[:2000]', view)

    def test_ops_attachments_is_not_used(self):
        view = (ROOT / "gis/feature_photo_views.py").read_text()
        self.assertNotIn("ops.attachments", view)
