from inspect import getsource
from unittest import TestCase

from control.services.signup_schema_readiness import (
    SqlSignupSchemaReadinessRepository,
)


class SignupSchemaReadinessContractTests(TestCase):
    def test_audit_is_read_only(self):
        source = "\n".join(
            (
                getsource(SqlSignupSchemaReadinessRepository._table_exists),
                getsource(SqlSignupSchemaReadinessRepository._columns),
                getsource(SqlSignupSchemaReadinessRepository._constraints),
                getsource(SqlSignupSchemaReadinessRepository._indexes),
                getsource(SqlSignupSchemaReadinessRepository._unique_index_column_sets),
                getsource(SqlSignupSchemaReadinessRepository.inspect),
            )
        ).upper()
        for forbidden in (
            "INSERT ",
            "UPDATE ",
            "DELETE ",
            "ALTER ",
            "CREATE ",
            "DROP ",
            "TRUNCATE ",
        ):
            self.assertNotIn(forbidden, source)

    def test_launch_requires_modern_join_request_columns(self):
        import control.services.signup_schema_readiness as module

        required = module._REQUIRED_COLUMNS["join_requests"]
        self.assertIn("requested_email", required)
        self.assertIn("requested_role_code", required)
        self.assertIn("decided_at", required)
        self.assertIn("decided_by", required)
        self.assertNotIn("email", required)
        self.assertNotIn("role_id", required)


    def test_launch_requires_erasure_and_outbox_runtime_columns(self):
        import control.services.signup_schema_readiness as module

        for column in ("first_name", "last_name", "last_login"):
            self.assertIn(column, module._REQUIRED_COLUMNS["auth_user"])
        for column in ("lease_id", "claimed_at", "claim_expires_at", "last_error_code"):
            self.assertIn(
                column,
                module._REQUIRED_COLUMNS["signup_verification_delivery_outbox"],
            )
        for column in ("purpose", "digest_algorithm", "created_at"):
            self.assertIn(
                column,
                module._REQUIRED_COLUMNS["signup_email_verification_tokens"],
            )

    def test_launch_requires_signup_integrity_constraints(self):
        import control.services.signup_schema_readiness as module

        constraints = {
            name
            for values in module._REQUIRED_CONSTRAINTS.values()
            for name in values
        }
        indexes = {
            name
            for values in module._REQUIRED_INDEXES.values()
            for name in values
        }
        self.assertIn("signup_req_decision_state", constraints)
        self.assertIn("signup_outbox_state_valid", constraints)
        for required in (
            "signup_req_one_open_user",
            "signup_vtoken_one_live",
            "signup_outbox_one_active",
        ):
            self.assertIn(required, indexes)
            self.assertNotIn(required, constraints)

    def test_partial_signup_schema_is_reported(self):
        source = getsource(SqlSignupSchemaReadinessRepository.inspect)
        self.assertIn("partial_signup_schema", source)


class SignupSchemaUpsertContractTests(TestCase):
    def test_launch_requires_join_and_membership_upsert_uniqueness(self):
        import control.services.signup_schema_readiness as module

        self.assertIn(
            frozenset(("email",)),
            module._REQUIRED_UNIQUE_COLUMN_SETS["users"],
        )
        self.assertIn(
            frozenset(("username",)),
            module._REQUIRED_UNIQUE_COLUMN_SETS["auth_user"],
        )
        self.assertIn(
            frozenset(("user_id", "group_id")),
            module._REQUIRED_UNIQUE_COLUMN_SETS["user_group_map"],
        )
        self.assertIn(
            frozenset(("user_id", "group_id", "requested_email")),
            module._REQUIRED_UNIQUE_COLUMN_SETS["join_requests"],
        )

    def test_unique_index_introspection_uses_postgres_catalog_read_only(self):
        source = getsource(
            SqlSignupSchemaReadinessRepository._unique_index_column_sets
        ).upper()
        self.assertIn("PG_INDEX", source)
        self.assertIn("INDISUNIQUE=TRUE", source)
        self.assertIn("INDPRED IS NULL", source)
        for forbidden in ("INSERT ", "UPDATE ", "DELETE ", "CREATE ", "DROP "):
            self.assertNotIn(forbidden, source)


class SignupDjangoBridgeSchemaContractTests(TestCase):
    def test_launch_requires_django_session_bridge_schema(self):
        import control.services.signup_schema_readiness as module

        required = module._REQUIRED_COLUMNS["auth_user"]
        for column in (
            "username",
            "email",
            "password",
            "is_active",
            "is_staff",
            "is_superuser",
        ):
            self.assertIn(column, required)
