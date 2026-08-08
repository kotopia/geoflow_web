from types import SimpleNamespace

from django.test import SimpleTestCase

from control.services.django_secret_preflight import inspect_django_secret_key


class DjangoSecretKeyPreflightTests(SimpleTestCase):
    def test_long_non_development_secret_passes_without_echoing_value(self):
        secret = "S" * 64
        check = inspect_django_secret_key(
            settings_obj=SimpleNamespace(SECRET_KEY=secret)
        )
        self.assertTrue(check.ready)
        self.assertNotIn(secret, check.message)

    def test_short_or_django_insecure_secret_fails(self):
        short = inspect_django_secret_key(
            settings_obj=SimpleNamespace(SECRET_KEY="short-secret")
        )
        insecure = inspect_django_secret_key(
            settings_obj=SimpleNamespace(
                SECRET_KEY="django-insecure-" + ("x" * 80)
            )
        )
        self.assertFalse(short.ready)
        self.assertFalse(insecure.ready)
