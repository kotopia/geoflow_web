from pathlib import Path
from unittest import TestCase


PROJECT_DIR = Path(__file__).resolve().parent


class PostLoginRouteGuardContractTests(TestCase):
    def test_after_login_route_requires_django_authentication(self):
        source = (PROJECT_DIR / "urls.py").read_text(encoding="utf-8")

        self.assertIn(
            "path('after-login/', login_required(views_auth.post_login_redirect), name='after_login')",
            source,
        )
        self.assertIn(
            "from django.contrib.auth.decorators import login_required",
            source,
        )


if __name__ == "__main__":
    unittest.main()
