from types import SimpleNamespace

from django.test import SimpleTestCase

from control.services.database_runtime_preflight import inspect_database_runtime


class DatabaseRuntimePreflightTests(SimpleTestCase):
    def _ready_env(self):
        return {
            "CENTRAL_DB_NAME": "central",
            "CENTRAL_DB_USER": "central-user",
            "CENTRAL_DB_PASSWORD": "central-secret",
            "CENTRAL_DB_HOST": "central.example.internal",
            "CENTRAL_DB_PORT": "5432",
            "ENABLE_TENANT_PROVISIONING": "0",
            "TENANT_DB_REQUIRE_SECRET_REFERENCES": "1",
        }

    def _ready_settings(self, sslmode="require"):
        return SimpleNamespace(
            DATABASES={
                "default": {
                    "ENGINE": "django.db.backends.postgresql",
                    "OPTIONS": {"sslmode": sslmode},
                },
            }
        )

    def _legacy_tenant_env(self):
        environ = self._ready_env()
        environ.update(
            {
                "TENANT_DB_NAME": "tenant",
                "TENANT_DB_USER": "tenant-user",
                "TENANT_DB_PASSWORD": "tenant-secret",
                "TENANT_DB_HOST": "tenant.example.internal",
                "TENANT_DB_PORT": "5432",
                "TENANT_DB_REQUIRE_SECRET_REFERENCES": "0",
            }
        )
        return environ

    def test_dynamic_secret_reference_configuration_passes_without_static_tenant_env(self):
        checks = inspect_database_runtime(
            settings_obj=self._ready_settings(),
            environ=self._ready_env(),
        )
        self.assertTrue(all(check.ready for check in checks))

    def test_legacy_tenant_fallback_shape_is_rejected_without_echoing_secrets(self):
        environ = self._legacy_tenant_env()
        secret = environ.pop("TENANT_DB_PASSWORD")
        environ.pop("TENANT_DB_USER")
        checks = inspect_database_runtime(
            settings_obj=self._ready_settings(),
            environ=environ,
        )
        failures = {check.code for check in checks if not check.ready}
        rendered = "\n".join(check.message for check in checks)
        self.assertIn("tenant_db_explicit_credentials", failures)
        self.assertIn("tenant_db_secret_references_required", failures)
        self.assertNotIn(secret, rendered)

    def test_local_central_host_or_enabled_provisioning_fail(self):
        environ = self._ready_env()
        environ["CENTRAL_DB_HOST"] = "localhost"
        environ["ENABLE_TENANT_PROVISIONING"] = "1"
        checks = inspect_database_runtime(
            settings_obj=self._ready_settings(),
            environ=environ,
        )
        failures = {check.code for check in checks if not check.ready}
        self.assertEqual(
            failures,
            {
                "central_db_nonlocal_host",
                "tenant_provisioning_disabled",
            },
        )

    def test_legacy_tenant_invalid_port_is_still_rejected(self):
        environ = self._legacy_tenant_env()
        environ["TENANT_DB_PORT"] = "invalid"
        checks = inspect_database_runtime(
            settings_obj=self._ready_settings(),
            environ=environ,
        )
        failures = {check.code for check in checks if not check.ready}
        self.assertEqual(
            failures,
            {
                "tenant_db_port",
                "tenant_db_secret_references_required",
            },
        )

    def test_unencrypted_postgres_sslmode_fails(self):
        checks = inspect_database_runtime(
            settings_obj=self._ready_settings(sslmode="disable"),
            environ=self._ready_env(),
        )
        failures = {check.code for check in checks if not check.ready}
        self.assertEqual(failures, {"database_transport_tls"})

    def test_secret_reference_enforcement_must_be_enabled(self):
        environ = self._legacy_tenant_env()
        checks = inspect_database_runtime(
            settings_obj=self._ready_settings(),
            environ=environ,
        )
        failures = {check.code for check in checks if not check.ready}
        self.assertEqual(failures, {"tenant_db_secret_references_required"})
