from pathlib import Path
from unittest import TestCase


CONTROL_DIR = Path(__file__).resolve().parent


class CategoriesAdminGuardContractTests(TestCase):
    def test_category_views_require_central_admin_and_get_only(self):
        source = (CONTROL_DIR / "views_categories.py").read_text(encoding="utf-8")

        self.assertIn("from control.decorators import require_central_admin", source)
        self.assertIn(
            "@require_GET\n@require_central_admin\ndef categories_page",
            source,
        )
        self.assertIn(
            "@require_GET\n@require_central_admin\ndef category_options",
            source,
        )

    def test_category_urls_remain_under_central_control_namespace(self):
        source = (CONTROL_DIR / "urls.py").read_text(encoding="utf-8")
        self.assertIn('path("categories/", categories_page', source)
        self.assertIn('path("categories/options/", category_options', source)


if __name__ == "__main__":
    unittest.main()
