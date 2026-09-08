from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class GISProjectReadinessWorkflowContractTests(unittest.TestCase):
    def setUp(self):
        self.workflow = (ROOT / ".github/workflows/geoflow-tenant-group-locator.yml").read_text()
        self.diagnostic = (ROOT / "scripts/ops/diagnose_gis_project_readiness.py").read_text()

    def test_workflow_is_manual_exact_release_and_production_gated(self):
        self.assertIn("workflow_dispatch:", self.workflow)
        self.assertNotIn("push:", self.workflow)
        self.assertIn("release/stabilized-deploy", self.workflow)
        self.assertIn("environment: production", self.workflow)
        self.assertIn('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"', self.workflow)

    def test_workflow_uses_strict_ssh_and_removes_uploaded_diagnostic(self):
        self.assertIn("StrictHostKeyChecking=yes", self.workflow)
        self.assertIn("IdentitiesOnly=yes", self.workflow)
        self.assertIn("trap 'rm -f", self.workflow)
        self.assertIn("diagnose_gis_project_readiness.py", self.workflow)

    def test_diagnostic_forces_read_only_database_sessions(self):
        self.assertIn("connection.set_session(readonly=True", self.diagnostic)
        self.assertGreaterEqual(self.diagnostic.count("SET LOCAL TRANSACTION READ ONLY"), 2)
        self.assertIn("statement_timeout", self.diagnostic)

    def test_diagnostic_has_no_database_mutation_statements(self):
        lowered = self.diagnostic.lower()
        for forbidden in (
            "insert into ", "update gis.", "delete from ", "create table ",
            "alter table ", "drop table ", "truncate ",
        ):
            self.assertNotIn(forbidden, lowered)

    def test_diagnostic_checks_complete_catalog_to_layer_plan_chain(self):
        for marker in (
            "catalog.category_node", "catalog.category_facet_option",
            "gis.scope_binding", "gis.capability_feature", "gis.project_profile",
            "gis.profile_feature", "gis_project_layer_plan_count",
        ):
            self.assertIn(marker, self.diagnostic)

    def test_diagnostic_supports_legacy_scope_item_without_active_or_ord(self):
        self.assertIn('scope_has_active = _column_exists', self.diagnostic)
        self.assertIn('"TRUE AS active"', self.diagnostic)
        self.assertIn('active_filter = " AND s.active" if scope_has_active else ""', self.diagnostic)
        self.assertIn('order_clause = "ord, id" if scope_has_ord else "id"', self.diagnostic)


if __name__ == "__main__":
    unittest.main()
