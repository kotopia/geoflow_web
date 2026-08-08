import os
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from control.views_signup import _public_document_url


class SignupPublicEnvironmentOverrideTests(SimpleTestCase):
    @override_settings(
        DEBUG=False,
        SITE_ORIGIN="http://192.168.0.19:8000",
        SIGNUP_TERMS_URL="http://192.168.0.19:8000/terms/",
    )
    def test_production_environment_overrides_local_public_url_placeholders(self):
        with patch.dict(
            os.environ,
            {
                "SITE_ORIGIN": "https://geoflow.co.kr",
                "SIGNUP_TERMS_URL": "https://geoflow.co.kr/terms/",
            },
            clear=False,
        ):
            self.assertEqual(
                _public_document_url("SIGNUP_TERMS_URL"),
                "https://geoflow.co.kr/terms/",
            )

    @override_settings(
        DEBUG=False,
        SITE_ORIGIN="https://geoflow.co.kr",
    )
    def test_external_environment_document_url_remains_rejected(self):
        with patch.dict(
            os.environ,
            {
                "SITE_ORIGIN": "https://geoflow.co.kr",
                "SIGNUP_PRIVACY_URL": "https://attacker.invalid/privacy/",
            },
            clear=False,
        ):
            self.assertIsNone(_public_document_url("SIGNUP_PRIVACY_URL"))
