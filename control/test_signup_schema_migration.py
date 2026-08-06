import importlib

from django.db import migrations, models
from django.test import SimpleTestCase, override_settings

from control.db_router import TenantRouter
from control.models import SignupRequest, SignupRequestEvent


class SignupSchemaMigrationStaticTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.migration = importlib.import_module(
            "control.migrations.0002_signup_core_schema"
        )

    def test_migration_creates_only_core_signup_tables(self):
        created = {
            operation.options["db_table"]
            for operation in self.migration.Migration.operations
            if isinstance(operation, migrations.CreateModel)
        }

        self.assertEqual(created, {"signup_requests", "signup_request_events"})
        self.assertTrue(
            {"users", "join_requests", "user_group_map"}.isdisjoint(created)
        )

    def test_signup_models_are_managed_by_control_migrations(self):
        self.assertTrue(SignupRequest._meta.managed)
        self.assertTrue(SignupRequestEvent._meta.managed)
        self.assertEqual(SignupRequest._meta.app_label, "control")
        self.assertEqual(SignupRequestEvent._meta.app_label, "control")

    @override_settings(CENTRAL_DB_ALIAS="central", DEFAULT_TENANT_DB_ALIAS="tenant")
    def test_control_signup_models_migrate_only_on_central_database(self):
        router = TenantRouter()

        for model in (SignupRequest, SignupRequestEvent):
            self.assertTrue(
                router.allow_migrate(
                    "central",
                    model._meta.app_label,
                    model_name=model._meta.model_name,
                )
            )
            self.assertFalse(
                router.allow_migrate(
                    "tenant",
                    model._meta.app_label,
                    model_name=model._meta.model_name,
                )
            )

    def test_request_constraints_include_status_version_and_one_open_request(self):
        constraints = {constraint.name: constraint for constraint in SignupRequest._meta.constraints}

        self.assertIsInstance(constraints["signup_req_status_valid"], models.CheckConstraint)
        self.assertIsInstance(
            constraints["signup_req_version_positive"], models.CheckConstraint
        )
        self.assertIsInstance(
            constraints["signup_req_one_open_user"], models.UniqueConstraint
        )
        self.assertIsNotNone(constraints["signup_req_one_open_user"].condition)

    def test_event_constraints_and_append_only_contract_are_declared(self):
        constraint_names = {
            constraint.name for constraint in SignupRequestEvent._meta.constraints
        }

        self.assertEqual(
            constraint_names,
            {"signup_evt_type_valid", "signup_evt_from_valid", "signup_evt_to_valid"},
        )
        self.assertIn("Append-only", SignupRequestEvent.__doc__)

    def test_foreign_keys_use_restrictive_deletion(self):
        for model, field_names in (
            (SignupRequest, ("user", "decided_by_user")),
            (SignupRequestEvent, ("signup_request", "actor_user")),
        ):
            for field_name in field_names:
                self.assertIs(
                    model._meta.get_field(field_name).remote_field.on_delete,
                    models.RESTRICT,
                )
