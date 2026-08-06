import importlib

from django.db import migrations, models
from django.test import SimpleTestCase, override_settings

from control.db_router import TenantRouter
from control.models import SignupEmailVerificationToken


class SignupEmailVerificationTokenSchemaTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.migration = importlib.import_module(
            "control.migrations.0003_signup_email_verification_tokens"
        )

    def test_migration_creates_only_email_verification_token_table(self):
        created = {
            operation.options["db_table"]
            for operation in self.migration.Migration.operations
            if isinstance(operation, migrations.CreateModel)
        }

        self.assertEqual(created, {"signup_email_verification_tokens"})
        self.assertTrue(
            {
                "users",
                "signup_requests",
                "signup_request_events",
                "join_requests",
                "user_group_map",
                "employee_profile",
            }.isdisjoint(created)
        )

    def test_migration_depends_on_signup_core_schema(self):
        self.assertEqual(
            self.migration.Migration.dependencies,
            [("control", "0002_signup_core_schema")],
        )

    def test_model_is_managed_by_control_migrations(self):
        self.assertTrue(SignupEmailVerificationToken._meta.managed)
        self.assertEqual(SignupEmailVerificationToken._meta.app_label, "control")
        self.assertEqual(
            SignupEmailVerificationToken._meta.db_table,
            "signup_email_verification_tokens",
        )

    def test_schema_has_no_raw_token_storage(self):
        field_names = {
            field.name for field in SignupEmailVerificationToken._meta.get_fields()
        }

        self.assertIn("token_digest", field_names)
        self.assertIn("digest_algorithm", field_names)
        self.assertIn("digest_key_id", field_names)
        self.assertNotIn("token", field_names)
        self.assertNotIn("raw_token", field_names)
        self.assertNotIn("token_value", field_names)

        digest_field = SignupEmailVerificationToken._meta.get_field("token_digest")
        self.assertEqual(digest_field.max_length, 64)

    def test_purpose_expiry_single_use_and_binding_fields_are_declared(self):
        model = SignupEmailVerificationToken

        self.assertEqual(
            {value for value, _label in model.Purpose.choices},
            {"signup_email_verification"},
        )
        self.assertEqual(
            {value for value, _label in model.DigestAlgorithm.choices},
            {"hmac_sha256"},
        )
        self.assertFalse(model._meta.get_field("expires_at").null)
        self.assertTrue(model._meta.get_field("consumed_at").null)
        self.assertEqual(
            model._meta.get_field("signup_request").remote_field.model._meta.db_table,
            "signup_requests",
        )
        self.assertIs(
            model._meta.get_field("signup_request").remote_field.on_delete,
            models.RESTRICT,
        )

    def test_constraints_cover_digest_purpose_expiry_and_consumption(self):
        constraints = {
            constraint.name: constraint
            for constraint in SignupEmailVerificationToken._meta.constraints
        }

        self.assertEqual(
            set(constraints),
            {
                "signup_vtoken_purpose_valid",
                "signup_vtoken_digest_alg",
                "signup_vtoken_digest_uq",
                "signup_vtoken_expiry_order",
                "signup_vtoken_used_order",
            },
        )
        self.assertIsInstance(
            constraints["signup_vtoken_digest_uq"], models.UniqueConstraint
        )
        self.assertEqual(
            constraints["signup_vtoken_digest_uq"].fields,
            ("digest_algorithm", "digest_key_id", "token_digest"),
        )
        for name in (
            "signup_vtoken_purpose_valid",
            "signup_vtoken_digest_alg",
            "signup_vtoken_expiry_order",
            "signup_vtoken_used_order",
        ):
            self.assertIsInstance(constraints[name], models.CheckConstraint)

    @override_settings(CENTRAL_DB_ALIAS="central", DEFAULT_TENANT_DB_ALIAS="tenant")
    def test_model_migrates_only_on_central_database(self):
        router = TenantRouter()
        model = SignupEmailVerificationToken

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

    def test_schema_draft_does_not_define_delivery_or_route_operations(self):
        operation_types = {
            type(operation) for operation in self.migration.Migration.operations
        }

        self.assertEqual(operation_types, {migrations.CreateModel})
