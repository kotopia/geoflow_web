from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ops" / "diagnose_qgis_runtime_principal.py"
WORKFLOW = ROOT / ".github" / "workflows" / "qgis-runtime-principal-diagnostic.yml"


def load_module():
    spec = importlib.util.spec_from_file_location("qgis_runtime_principal", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class QgisRuntimePrincipalDiagnosticContractTests(unittest.TestCase):
    def test_principal_is_reduced_to_approved_labels(self):
        module = load_module()
        self.assertEqual(
            module.principal_label(
                "arn:aws:iam::123456789012:user/geoflow-webgis-s3-user"
            ),
            "geoflow-webgis-s3-user",
        )
        self.assertEqual(
            module.principal_label("arn:aws:iam::123456789012:user/webgis-admin"),
            "webgis-admin",
        )
        self.assertEqual(
            module.principal_label(
                "arn:aws:sts::123456789012:assumed-role/runtime/session"
            ),
            "assumed-role",
        )
        self.assertEqual(
            module.principal_label("arn:aws:iam::123456789012:user/unexpected"),
            "other-user",
        )
        self.assertEqual(module.principal_label("unexpected"), "other")

    def test_script_calls_only_sts_and_never_prints_raw_identity(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("django.setup()", text)
        self.assertIn('session.client("sts")', text)
        self.assertNotIn('client("s3")', text)
        self.assertNotIn('client("iam")', text)
        self.assertNotIn('print(identity', text)
        self.assertNotIn('print(arn', text)

    def test_workflow_is_protected_and_read_only(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("environment: production", text)
        self.assertIn("diagnose_qgis_runtime_principal.py", text)
        self.assertIn("release/stabilized-deploy", text)
        self.assertNotIn("publish_qgis_plugin_repository.py", text)
        self.assertNotIn("put_object", text.lower())
        self.assertNotIn("iam", text.lower())
        self.assertNotIn("systemctl restart", text)


if __name__ == "__main__":
    unittest.main()
