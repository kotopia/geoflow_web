from pathlib import Path
from unittest import TestCase


CATALOG_DIR = Path(__file__).resolve().parent


class CatalogUrlAuthorizationContractTests(TestCase):
    def test_every_admin_route_uses_central_admin_wrapper(self):
        source = (CATALOG_DIR / "urls.py").read_text(encoding="utf-8")
        admin_path_lines = [
            line.strip()
            for line in source.splitlines()
            if "path('admin/" in line
        ]
        self.assertGreater(len(admin_path_lines), 0)
        for line in admin_path_lines:
            self.assertTrue(
                "_admin(" in line or "_admin_post(" in line,
                msg=f"unguarded catalog admin route: {line}",
            )

    def test_delete_routes_are_post_only_at_url_boundary(self):
        source = (CATALOG_DIR / "urls.py").read_text(encoding="utf-8")
        delete_lines = [
            line.strip()
            for line in source.splitlines()
            if "path('admin/" in line and "/delete/'" in line
        ]
        self.assertGreater(len(delete_lines), 0)
        for line in delete_lines:
            self.assertIn("_admin_post(", line)

    def test_facet_options_is_not_anonymous(self):
        source = (CATALOG_DIR / "urls.py").read_text(encoding="utf-8")
        self.assertIn(
            "path('facet-options/', login_required(views.facet_options)",
            source,
        )


if __name__ == "__main__":
    unittest.main()
