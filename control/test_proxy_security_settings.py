from unittest import TestCase

from geoflow_project.proxy_security_settings import (
    EXPECTED_PROXY_SSL_HEADER,
    PRELOAD_MINIMUM_SECONDS,
    load_proxy_security_settings,
)


class ProxySecuritySettingsTests(TestCase):
    def test_defaults_preserve_current_runtime_behavior(self):
        config = load_proxy_security_settings({})
        self.assertIsNone(config.proxy_ssl_header)
        self.assertFalse(config.ssl_redirect)
        self.assertEqual(config.hsts_seconds, 0)
        self.assertFalse(config.hsts_include_subdomains)
        self.assertFalse(config.hsts_preload)

    def test_trusted_proxy_contract_is_fixed_not_arbitrary(self):
        config = load_proxy_security_settings(
            {"DJANGO_TRUST_X_FORWARDED_PROTO": "1"}
        )
        self.assertEqual(config.proxy_ssl_header, EXPECTED_PROXY_SSL_HEADER)

    def test_https_redirect_can_be_staged_independently(self):
        config = load_proxy_security_settings(
            {"DJANGO_SECURE_SSL_REDIRECT": "true"}
        )
        self.assertTrue(config.ssl_redirect)
        self.assertIsNone(config.proxy_ssl_header)

    def test_short_hsts_can_be_staged_without_subdomains_or_preload(self):
        config = load_proxy_security_settings(
            {"DJANGO_SECURE_HSTS_SECONDS": "300"}
        )
        self.assertEqual(config.hsts_seconds, 300)
        self.assertFalse(config.hsts_include_subdomains)
        self.assertFalse(config.hsts_preload)

    def test_invalid_boolean_fails_closed(self):
        with self.assertRaisesRegex(
            RuntimeError,
            "Invalid boolean environment variable: DJANGO_TRUST_X_FORWARDED_PROTO",
        ):
            load_proxy_security_settings(
                {"DJANGO_TRUST_X_FORWARDED_PROTO": "sometimes"}
            )

    def test_hsts_flags_require_positive_duration(self):
        for name in (
            "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS",
            "DJANGO_SECURE_HSTS_PRELOAD",
        ):
            with self.subTest(name=name):
                with self.assertRaisesRegex(RuntimeError, "HSTS subdomain/preload"):
                    load_proxy_security_settings({name: "1"})

    def test_preload_requires_one_year_and_include_subdomains(self):
        with self.assertRaisesRegex(RuntimeError, "HSTS preload requires"):
            load_proxy_security_settings(
                {
                    "DJANGO_SECURE_HSTS_SECONDS": str(PRELOAD_MINIMUM_SECONDS),
                    "DJANGO_SECURE_HSTS_PRELOAD": "1",
                }
            )

        with self.assertRaisesRegex(RuntimeError, "HSTS preload requires"):
            load_proxy_security_settings(
                {
                    "DJANGO_SECURE_HSTS_SECONDS": str(
                        PRELOAD_MINIMUM_SECONDS - 1
                    ),
                    "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS": "1",
                    "DJANGO_SECURE_HSTS_PRELOAD": "1",
                }
            )

        config = load_proxy_security_settings(
            {
                "DJANGO_SECURE_HSTS_SECONDS": str(PRELOAD_MINIMUM_SECONDS),
                "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS": "1",
                "DJANGO_SECURE_HSTS_PRELOAD": "1",
            }
        )
        self.assertTrue(config.hsts_include_subdomains)
        self.assertTrue(config.hsts_preload)
