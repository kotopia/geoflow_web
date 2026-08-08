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
            "TENANT_DB_NAME": "tenant",
            "TENANT_DB_USER": "tenant-user",
            "TENANT_DB_PASSWORD": "tenant-secret",
            "TENANT_DB_HOST": "tenant.example.internal",
            "TENANT_DB_PORT": "5432",
            "ENABLE_TENANT_PROVISIONING": "0",
        }

    def test_explicit_nonlocal_db_configuration_passes(self):
        checks = inspect_database_runtime(environ=self._ready_env())
        self.assertTrue(all(check.ready for check in checks))

    def test_tenant_fallback_shape_is_rejected_without_echoing_secrets(self):
        environ = self._ready_env()
        secret = environ.pop("TENANT_DB_PASSWORD")
        environ.pop("TENANT_DB_USER")
        checks = inspect_database_runtime(environ=environ)
        failures = {check.code for check in checks if not check.ready}
        rendered = "\n".join(check.message for check in checks)
        self.assertIn("tenant_db_explicit_credentials", failures)
        self.assertNotIn(secret, rendered)

    def test_local_host_invalid_port_or_enabled_provisioning_fail(self):
        environ = self._ready_env()
        environ["CENTRAL_DB_HOST"] = "localhost"
        environ["TENANT_DB_PORT"] = "invalid"
        environ["ENABLE_TENANT_PROVISIONING"] = "1"
        checks = inspect_database_runtime(environ=environ)
        failures = {check.code for check in checks if not check.ready}
        self.assertEqual(
            failures,
            {
                "central_db_nonlocal_host",
                "tenant_db_port",
                "tenant_provisioning_disabled",
            },
        )
