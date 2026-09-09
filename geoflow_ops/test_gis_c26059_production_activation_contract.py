from pathlib import Path
import importlib.util
import unittest


ROOT = Path(__file__).resolve().parents[1]


class GISC26059ProductionActivationContractTests(unittest.TestCase):
    def setUp(self):
        self.workflow = (ROOT / ".github/workflows/gis-c26059-production-activation.yml").read_text()
        self.script = (ROOT / "scripts/ops/activate_c26059_gis_foundation.py").read_text()

    def test_workflow_is_manual_exact_release_and_production_gated(self):
        self.assertIn("workflow_dispatch:", self.workflow)
        self.assertNotIn("push:", self.workflow)
        self.assertIn("environment: production", self.workflow)
        self.assertIn("release/stabilized-deploy", self.workflow)
        self.assertIn('test "$(git rev-parse FETCH_HEAD)" = "$GITHUB_SHA"', self.workflow)
        self.assertIn("ACTIVATE_C26059_GIS", self.workflow)

    def test_workflow_does_not_deploy_or_restart_service(self):
        lowered = self.workflow.lower()
        for forbidden in ("systemctl restart", "systemctl stop", "git reset", "git checkout"):
            self.assertNotIn(forbidden, lowered)

    def test_workflow_uses_strict_ssh_and_cleans_bundle(self):
        self.assertIn("StrictHostKeyChecking=yes", self.workflow)
        self.assertIn("IdentitiesOnly=yes", self.workflow)
        self.assertIn("trap 'rm -rf", self.workflow)

    def test_script_is_locked_to_exact_approved_target(self):
        for marker in (
            'PROJECT_ID = "98d5b8f2-3940-49f7-801d-83c7dbeff99b"',
            'PROJECT_CODE = "C26059"', 'GROUP_CODE = "cheonan"',
            'DB_ALIAS = "cheonan_db"', 'CONFIRMATION = "ACTIVATE_C26059_GIS"',
        ):
            self.assertIn(marker, self.script)

    def test_script_pins_reviewed_sql_hashes(self):
        self.assertEqual(self.script.count('reviewed GIS SQL hash mismatch'), 1)
        for sql_name in (
            "gis-schema-foundation.sql", "gis-initial-feature-tables-v0.1.sql",
            "gis-metadata-seed-v0.1.sql", "gis-scope-capability-v0.1.sql",
            "gis-sync-revision-v1.sql",
        ):
            self.assertIn(sql_name, self.script)

    def test_prepared_sql_removes_dev_guards_and_destructive_index_cleanup(self):
        path = ROOT / "scripts/ops/activate_c26059_gis_foundation.py"
        spec = importlib.util.spec_from_file_location("gis_activation", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        prepared = "\n".join(module._prepared_sources(ROOT / "docs/architecture"))
        self.assertNotIn("Safety stop:", prepared)
        self.assertNotIn("DROP INDEX", prepared)
        self.assertNotIn("GEOFLOW_DEV_BASE", prepared)
        self.assertIn("GEOFLOW_BASE_V1", prepared)
        self.assertNotIn("SELECT p.id, 0, 0", prepared)

    def test_script_requires_empty_gis_schema_and_existing_postgis(self):
        self.assertIn("pg_extension WHERE extname='postgis'", self.script)
        self.assertIn("gis schema already exists", self.script)
        self.assertNotIn("CREATE EXTENSION", self.script)

    def test_script_rehearses_rollback_before_commit(self):
        rehearsal = self.script.index("commit=False")
        apply = self.script.index("commit=True")
        self.assertLess(rehearsal, apply)
        self.assertIn("connection.rollback()", self.script)
        self.assertIn("connection.commit()", self.script)
        self.assertIn("pg_advisory_xact_lock", self.script)
        self.assertIn("lock_timeout", self.script)
        self.assertIn("statement_timeout", self.script)

    def test_script_validates_exact_water_only_layer_plan(self):
        self.assertIn('(11, 2, 9, 0)', self.script)
        self.assertIn("project capability must resolve to WATER only", self.script)
        self.assertIn("business project/scope row counts changed", self.script)

    def test_script_does_not_mutate_business_scope_or_project(self):
        lowered = self.script.lower()
        for forbidden in (
            "insert into prj.", "update prj.", "delete from prj.",
            "insert into catalog.", "update catalog.", "delete from catalog.",
            "drop schema", "drop table", "truncate ",
        ):
            self.assertNotIn(forbidden, lowered)


if __name__ == "__main__":
    unittest.main()
