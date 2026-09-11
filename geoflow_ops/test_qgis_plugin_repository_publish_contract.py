from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class QgisPluginRepositoryPublishContractTests(unittest.TestCase):
    def test_publish_is_exact_bucket_prefix_and_test_only(self):
        source = (ROOT / "scripts/ops/publish_qgis_plugin_repository.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("only_test_channel_is_authorized", source)
        self.assertIn("tenant_prefix_forbidden", source)
        self.assertIn("immutable_package_collision", source)
        self.assertIn('QGIS_PLUGIN_REPOSITORY_FILE_NAME = "geoflow_connector.zip"', source)
        self.assertIn("repository_package_version_mismatch", source)
        self.assertIn("PUBLISH_QGIS_PLUGIN:{channel}", source)
        self.assertNotIn("delete_object", source)
        self.assertNotIn("put_bucket", source)

    def test_workflow_uses_protected_environment_and_exact_confirmation(self):
        workflow = (
            ROOT / ".github/workflows/qgis-plugin-test-repository-publish.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("environment: production", workflow)
        self.assertIn("PUBLISH_QGIS_PLUGIN:test:geoflow-upload:qgis-plugins", workflow)
        self.assertIn("geoflow_connector-0.7.6.zip", workflow)
        self.assertIn("release/stabilized-deploy", workflow)
        self.assertNotIn("tenants/", workflow)
        self.assertNotIn("aws s3 sync", workflow)
        self.assertNotIn("apply_qgis_plugin_s3_access.py", workflow)
        self.assertNotIn("iam:", workflow.lower())


if __name__ == "__main__":
    unittest.main()
