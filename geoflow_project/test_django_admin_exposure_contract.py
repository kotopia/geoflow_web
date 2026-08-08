from pathlib import Path
from unittest import TestCase


PROJECT_DIR = Path(__file__).resolve().parent


class DjangoAdminExposureContractTests(TestCase):
    def test_stock_admin_is_debug_only(self):
        source = (PROJECT_DIR / "urls.py").read_text(encoding="utf-8")

        self.assertIn("if settings.DEBUG:", source)
        self.assertIn("urlpatterns.insert(0, path('admin/', admin.site.urls))", source)
        self.assertNotIn("urlpatterns = [\n    path('admin/'", source)


if __name__ == "__main__":
    unittest.main()
