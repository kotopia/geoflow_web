from pathlib import Path
from unittest import TestCase


CONTROL_DIR = Path(__file__).resolve().parent
MIGRATION_PATH = (
    CONTROL_DIR / "migrations/0004_signup_verification_delivery_outbox.py"
)


class SignupVerificationOutboxSchemaTests(TestCase):
    def test_migration_adds_revocation_before_single_live_constraint(self):
        source = MIGRATION_PATH.read_text(encoding="utf-8")

        add_field = source.index('name="revoked_at"')
        cleanup = source.index("REVOKE_OLDER_UNCONSUMED_TOKENS_SQL")
        one_live = source.index('name="signup_vtoken_one_live"')
        self.assertLess(add_field, one_live)
        self.assertLess(cleanup, one_live)
        self.assertIn("revoked_at__isnull=True", source)
        self.assertIn("consumed_at__isnull=True", source)
        self.assertIn('name="signup_vtoken_one_terminal"', source)

    def test_migration_keeps_only_newest_preexisting_unconsumed_token_live(self):
        source = MIGRATION_PATH.read_text(encoding="utf-8")

        self.assertIn(
            "PARTITION BY signup_request_id, purpose",
            source,
        )
        self.assertIn("ORDER BY created_at DESC, id DESC", source)
        self.assertIn("ranked.position > 1", source)
        self.assertIn(
            "GREATEST(CURRENT_TIMESTAMP, token.created_at)",
            source,
        )
        run_sql = source[source.index("migrations.RunSQL("):source.index(
            "migrations.AddConstraint(",
            source.index("migrations.RunSQL("),
        )]
        self.assertNotIn("reverse_sql", run_sql)

    def test_outbox_schema_contains_intent_and_lease_metadata_only(self):
        source = MIGRATION_PATH.read_text(encoding="utf-8")

        for required in (
            'db_table": "signup_verification_delivery_outbox"',
            '"available_at"',
            '"attempt_count"',
            '"lease_id"',
            '"claim_expires_at"',
            '"last_error_code"',
            'name="signup_outbox_one_active"',
        ):
            self.assertIn(required, source)

        for forbidden in (
            "raw_token",
            "verification_link",
            "recipient_email",
            "message_body",
            "password_hash",
        ):
            self.assertNotIn(forbidden, source)

    def test_token_cleanup_makes_automatic_reverse_intentionally_unavailable(self):
        source = MIGRATION_PATH.read_text(encoding="utf-8")

        self.assertIn("Irreversible by design", source)
        self.assertIn("previously superseded verification tokens", source)

    def test_model_state_matches_revocation_and_outbox_schema(self):
        source = (CONTROL_DIR / "models.py").read_text(encoding="utf-8")

        for required in (
            "revoked_at = models.DateTimeField(null=True, blank=True)",
            'name="signup_vtoken_one_live"',
            "class SignupVerificationDeliveryOutbox(models.Model):",
            'db_table = "signup_verification_delivery_outbox"',
            'name="signup_outbox_one_active"',
        ):
            self.assertIn(required, source)
        for forbidden in (
            "raw_token",
            "recipient_email",
            "verification_link = models.",
        ):
            self.assertNotIn(forbidden, source)

    def test_migration_is_additive_and_does_not_drop_existing_tables(self):
        source = MIGRATION_PATH.read_text(encoding="utf-8")

        for forbidden in (
            "DeleteModel",
            "RemoveField",
            "DROP TABLE",
            "DROP COLUMN",
        ):
            self.assertNotIn(forbidden, source)

    def test_control_router_keeps_migration_on_central_alias(self):
        router_source = (CONTROL_DIR / "db_router.py").read_text(encoding="utf-8")

        self.assertIn('CENTRAL_APPS = {"control", "catalog"}', router_source)
        self.assertIn("return db == settings.CENTRAL_DB_ALIAS", router_source)
