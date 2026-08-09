from importlib import import_module
from unittest import TestCase

from django.db import migrations


class JoinRequestDecisionAuditMigrationTests(TestCase):
    def test_migration_adds_missing_legacy_audit_columns_idempotently(self):
        module = import_module(
            "control.migrations.0005_join_request_decision_audit_columns"
        )
        sql = module.ADD_JOIN_REQUEST_DECISION_AUDIT_COLUMNS_SQL.upper()

        self.assertIn("ALTER TABLE JOIN_REQUESTS", sql)
        self.assertIn(
            "ADD COLUMN IF NOT EXISTS DECIDED_AT TIMESTAMPTZ NULL",
            sql,
        )
        self.assertIn(
            "ADD COLUMN IF NOT EXISTS DECIDED_BY UUID NULL",
            sql,
        )
        self.assertNotIn("DROP COLUMN", sql)
        self.assertNotIn("UPDATE JOIN_REQUESTS", sql)

    def test_reverse_does_not_delete_existing_audit_data(self):
        module = import_module(
            "control.migrations.0005_join_request_decision_audit_columns"
        )
        operation = module.Migration.operations[0]

        self.assertIsInstance(operation, migrations.RunSQL)
        self.assertEqual(operation.reverse_sql, migrations.RunSQL.noop)
        self.assertEqual(
            module.Migration.dependencies,
            [("control", "0004_signup_verification_delivery_outbox")],
        )
