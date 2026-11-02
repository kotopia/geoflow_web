from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class QgisPluginRepositoryPublishContractTests(unittest.TestCase):
    def test_publish_is_exact_bucket_prefix_and_channel_isolated(self):
        source = (ROOT / "scripts/ops/publish_qgis_plugin_repository.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("test_repository_changed", source)
        self.assertIn("tenant_prefix_forbidden", source)
        self.assertIn("immutable_package_collision", source)
        self.assertIn("QGIS_PLUGIN_REPOSITORY_FILE_NAME = 'geoflow_connector.zip'", source)
        self.assertIn("repository_version_invalid", source)
        self.assertIn("PUBLISH_QGIS_PLUGIN:{channel}", source)
        self.assertNotIn("delete_object", source)
        self.assertNotIn("put_bucket", source)

    def test_workflow_uses_protected_environment_and_exact_confirmation(self):
        workflow = (
            ROOT / ".github/workflows/qgis-plugin-test-repository-publish.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("environment: production", workflow)
        self.assertIn("PUBLISH_QGIS_PLUGIN:test:geoflow-upload:qgis-plugins", workflow)
        self.assertNotIn("geoflow_connector-1.4.2.zip", workflow)
        self.assertIn("PLUGIN_VERSION", workflow)
        self.assertNotIn("  push:", workflow)
        self.assertIn("release/stabilized-deploy", workflow)
        self.assertNotIn("tenants/", workflow)
        self.assertNotIn("aws s3 sync", workflow)
        self.assertNotIn("apply_qgis_plugin_s3_access.py", workflow)
        self.assertNotIn("iam:", workflow.lower())

    def test_stable_only_workflow_preserves_operational_boundaries(self):
        workflow = (ROOT / '.github/workflows/qgis-plugin-stable-repository-publish.yml').read_text(encoding='utf-8')
        for token in ("if: github.event_name == 'workflow_dispatch' && github.ref_name == 'release/stabilized-deploy'", 'environment: production',
                      'PUBLISH_QGIS_PLUGIN:stable:geoflow-upload:qgis-plugins',
                      '--release-manifest', '--inventory', '--verify-http',
                      'stable_release_descriptor_mismatch', 'merge-base',
                      'StrictHostKeyChecking=yes', 'flock -x 9'):
            self.assertIn(token, workflow)
        for forbidden in ('systemctl restart', 'migrate_all_tenants',
                          'manage.py migrate', 'aws s3 sync', 'iam:', 'git reset --hard'):
            self.assertNotIn(forbidden, workflow)

    def test_plugin_only_push_never_starts_server_deployment(self):
        from scripts.ci.gis_deploy_scope import requires_server_deploy
        plugin = ['integrations/qgis/geoflow_connector/ui/form_host.py',
                  'docs/operations/qgis-plugin-stable-release.json',
                  '.github/workflows/gis-definition-code-deploy.yml']
        self.assertFalse(requires_server_deploy(plugin))
        self.assertFalse(requires_server_deploy([]))
        for server_path in ('control/services/gis_definitions.py',
                            'geoflow_project/settings.py', 'unknown/server.py',
                            'scripts/ops/publish_qgis_plugin_repository.py'):
            self.assertTrue(requires_server_deploy(plugin + [server_path]))
        workflow = (ROOT / '.github/workflows/gis-definition-code-deploy.yml').read_text(encoding='utf-8')
        self.assertIn('needs: classify-release', workflow)
        self.assertIn("needs.classify-release.outputs.server_deploy == 'true'", workflow)
        self.assertIn('environment: production', workflow)


if __name__ == "__main__":
    unittest.main()
