from inspect import getsource
from unittest import TestCase

from control.services.account_password_reset_schema_readiness import (
    OUTBOX_TABLE,
    TOKEN_TABLE,
    inspect_account_password_reset_schema_readiness,
)


class AccountPasswordResetSchemaReadinessTests(TestCase):
    def test_audit_targets_only_schema_metadata(self):
        source = getsource(inspect_account_password_reset_schema_readiness)
        self.assertIn("information_schema.columns", source)
        self.assertIn("pg_indexes", source)
        self.assertIn("django_migrations", source)
        self.assertIn("0006_account_password_reset_schema", source)
        for mutation in ("INSERT INTO", "UPDATE ", "DELETE FROM", "ALTER TABLE", "DROP TABLE"):
            self.assertNotIn(mutation, source.upper())

    def test_expected_password_reset_tables_are_explicit(self):
        self.assertEqual(TOKEN_TABLE, "account_password_reset_tokens")
        self.assertEqual(OUTBOX_TABLE, "account_password_reset_delivery_outbox")
