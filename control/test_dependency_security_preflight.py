from django.test import SimpleTestCase

from control.services.dependency_security_preflight import (
    inspect_django_security_baseline,
)


class DjangoSecurityBaselineTests(SimpleTestCase):
    def test_current_approved_patch_or_newer_5_2_patch_passes(self):
        self.assertTrue(
            inspect_django_security_baseline(
                version=(5, 2, 16, "final", 0)
            ).ready
        )
        self.assertTrue(
            inspect_django_security_baseline(
                version=(5, 2, 17, "final", 0)
            ).ready
        )

    def test_older_5_2_patch_fails(self):
        result = inspect_django_security_baseline(
            version=(5, 2, 4, "final", 0)
        )
        self.assertFalse(result.ready)
        self.assertNotIn("5.2.4", result.message)

    def test_unreviewed_feature_series_fails_even_when_numerically_newer(self):
        self.assertFalse(
            inspect_django_security_baseline(
                version=(6, 0, 7, "final", 0)
            ).ready
        )
