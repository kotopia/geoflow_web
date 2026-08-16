from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "phase4-event-production-readonly-audit.yml"


class Phase4EventProductionAuditContractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source = WORKFLOW.read_text(encoding="utf-8")

    def test_audit_uses_protected_production_environment(self):
        self.assertIn("environment: production", self.source)
        self.assertIn("service='geoflow-stabilized.service'", self.source)
        self.assertNotIn("iroomsng", self.source.lower())

    def test_audit_is_exact_release_bound(self):
        self.assertIn('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"', self.source)
        self.assertIn("phase4_event_audit_blocker=release_advanced", self.source)

    def test_audit_uses_dynamic_tenant_metadata_not_static_alias(self):
        self.assertIn("GroupDBConfig", self.source)
        self.assertIn("resolve_tenant_db_password", self.source)
        self.assertNotIn("cheonan_db", self.source)

    def test_every_tenant_connection_is_forced_read_only(self):
        self.assertIn("conn.set_session(readonly=True, autocommit=False)", self.source)
        self.assertIn("SHOW transaction_read_only", self.source)
        self.assertIn('central_cur.execute("SET LOCAL TRANSACTION READ ONLY")', self.source)

    def test_audit_does_not_select_business_text_or_payload_content(self):
        lowered = self.source.lower()
        self.assertNotIn("select title", lowered)
        self.assertNotIn("select memo", lowered)
        self.assertNotIn("select payload", lowered)
        self.assertIn("aggregate-only diagnostic", lowered)

    def test_audit_contains_no_sql_data_or_schema_mutation(self):
        lowered = self.source.lower()
        forbidden = (
            "cur.execute(\"update ",
            "cur.execute(\"insert ",
            "cur.execute(\"delete ",
            "cur.execute(\"alter ",
            "cur.execute(\"create ",
            "cur.execute(\"drop ",
            "cur.execute(\"truncate ",
        )
        for token in forbidden:
            self.assertNotIn(token, lowered)
