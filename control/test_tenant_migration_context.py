from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from control.db_router import TenantRouter
from control.tenant_migration_context import (
    allow_tenant_provisioning_migrations,
    current_provisioning_migration_alias,
)


@override_settings(
    CENTRAL_DB_ALIAS="default",
    DEFAULT_TENANT_DB_ALIAS="cheonan_db",
)
class TenantMigrationContextTests(SimpleTestCase):
    def setUp(self):
        self.router = TenantRouter()

    def test_dynamic_tenant_alias_is_denied_by_default(self):
        self.assertFalse(
            self.router.allow_migrate("new_tenant_db", "geoflow_ops")
        )
        self.assertIsNone(current_provisioning_migration_alias())

    def test_exact_dynamic_alias_is_allowed_only_inside_explicit_context(self):
        with allow_tenant_provisioning_migrations("new_tenant_db"):
            self.assertEqual(
                current_provisioning_migration_alias(),
                "new_tenant_db",
            )
            self.assertTrue(
                self.router.allow_migrate("new_tenant_db", "geoflow_ops")
            )
            self.assertTrue(
                self.router.allow_migrate("new_tenant_db", "webgisapp")
            )
            self.assertFalse(
                self.router.allow_migrate("other_tenant_db", "geoflow_ops")
            )

        self.assertIsNone(current_provisioning_migration_alias())
        self.assertFalse(
            self.router.allow_migrate("new_tenant_db", "geoflow_ops")
        )

    def test_default_legacy_tenant_alias_remains_allowed(self):
        self.assertTrue(
            self.router.allow_migrate("cheonan_db", "geoflow_ops")
        )

    def test_central_apps_never_follow_dynamic_tenant_context(self):
        with allow_tenant_provisioning_migrations("new_tenant_db"):
            self.assertTrue(self.router.allow_migrate("default", "control"))
            self.assertTrue(self.router.allow_migrate("default", "catalog"))
            self.assertFalse(
                self.router.allow_migrate("new_tenant_db", "control")
            )
            self.assertFalse(
                self.router.allow_migrate("new_tenant_db", "catalog")
            )

    def test_unclassified_apps_stay_central(self):
        with allow_tenant_provisioning_migrations("new_tenant_db"):
            self.assertTrue(self.router.allow_migrate("default", "auth"))
            self.assertFalse(
                self.router.allow_migrate("new_tenant_db", "auth")
            )

    def test_context_is_restored_after_exception(self):
        with self.assertRaises(RuntimeError):
            with allow_tenant_provisioning_migrations("new_tenant_db"):
                self.assertEqual(
                    current_provisioning_migration_alias(),
                    "new_tenant_db",
                )
                raise RuntimeError("test")

        self.assertIsNone(current_provisioning_migration_alias())

    def test_nested_context_restores_outer_alias(self):
        with allow_tenant_provisioning_migrations("outer_db"):
            self.assertEqual(current_provisioning_migration_alias(), "outer_db")
            with allow_tenant_provisioning_migrations("inner_db"):
                self.assertEqual(
                    current_provisioning_migration_alias(),
                    "inner_db",
                )
            self.assertEqual(current_provisioning_migration_alias(), "outer_db")
        self.assertIsNone(current_provisioning_migration_alias())

    def test_blank_and_central_aliases_are_rejected(self):
        for alias in ("", "   ", "default"):
            with self.subTest(alias=alias):
                with self.assertRaises(ImproperlyConfigured):
                    with allow_tenant_provisioning_migrations(alias):
                        pass
