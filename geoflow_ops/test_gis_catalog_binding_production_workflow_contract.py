from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class GISCatalogBindingProductionWorkflowContractTests(unittest.TestCase):
    def setUp(self):
        self.workflow = (
            ROOT / ".github/workflows/gis-catalog-binding-cheonan-production.yml"
        ).read_text()

    def test_workflow_is_manual_release_and_production_gated(self):
        self.assertIn("workflow_dispatch:", self.workflow)
        self.assertNotIn("push:", self.workflow)
        self.assertIn("environment: production", self.workflow)
        self.assertIn("github.ref_name == 'release/stabilized-deploy'", self.workflow)
        self.assertIn("SYNC_GIS_CATALOG_BINDINGS:cheonan:cheonan_db", self.workflow)

    def test_workflow_is_locked_to_current_deployed_release_and_tenant(self):
        self.assertIn("9cfe158281ae2506cad9e2631edc973dab6deb06", self.workflow)
        self.assertIn("--group-code cheonan", self.workflow)
        self.assertIn("--db-alias cheonan_db", self.workflow)
        self.assertIn("unexpected_deployed_release", self.workflow)

    def test_workflow_uses_strict_ssh_and_cleans_temporary_script(self):
        self.assertIn("StrictHostKeyChecking=yes", self.workflow)
        self.assertIn("IdentitiesOnly=yes", self.workflow)
        self.assertIn("trap 'rm -f", self.workflow)

    def test_workflow_does_not_deploy_restart_or_run_unrelated_mutations(self):
        lowered = self.workflow.lower()
        for forbidden in (
            "systemctl restart",
            "git checkout",
            "git reset",
            "manage.py migrate",
            "insert into",
            "delete from",
            "update prj.",
        ):
            self.assertNotIn(forbidden, lowered)

    def test_workflow_checks_gis_endpoint_after_sync(self):
        self.assertIn("http://127.0.0.1:8011/gis/", self.workflow)
        self.assertIn("RESULT gis_catalog_binding_cheonan_production=SUCCESS", self.workflow)


if __name__ == "__main__":
    unittest.main()
