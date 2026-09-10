from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ops" / "apply_qgis_plugin_s3_access.py"
WORKFLOW = ROOT / ".github" / "workflows" / "qgis-plugin-test-repository-publish.yml"


def load_module():
    spec = importlib.util.spec_from_file_location("qgis_plugin_s3_access", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class QgisPluginS3AccessContractTests(unittest.TestCase):
    def test_policy_is_exact_object_scope_without_delete_or_acl(self):
        module = load_module()
        policy = module.policy_document()
        encoded = json.dumps(policy)
        self.assertEqual(
            policy["Statement"][0]["Action"],
            ["s3:GetObject", "s3:PutObject"],
        )
        self.assertEqual(
            policy["Statement"][0]["Resource"],
            ["arn:aws:s3:::geoflow-upload/qgis-plugins/*"],
        )
        self.assertNotIn("DeleteObject", encoded)
        self.assertNotIn("PutObjectAcl", encoded)
        self.assertNotIn("tenants/", encoded)

    def test_principal_resolution_is_fail_closed(self):
        module = load_module()
        self.assertEqual(
            module.principal_target("arn:aws:iam::123456789012:user/path/runtime"),
            ("user", "runtime"),
        )
        self.assertEqual(
            module.principal_target(
                "arn:aws:sts::123456789012:assumed-role/runtime-role/session"
            ),
            ("role", "runtime-role"),
        )
        with self.assertRaises(SystemExit):
            module.principal_target("arn:aws:iam::123456789012:root")

    def test_repository_bucket_is_independent_from_attachment_bucket_setting(self):
        module = load_module()
        with patch.dict(os.environ, {"AWS_S3_BUCKET": "another-private-bucket"}):
            module.validate_inputs(module.CONFIRMATION)
        self.assertEqual(module.BUCKET, "geoflow-upload")
        self.assertEqual(
            module.policy_document()["Statement"][0]["Resource"],
            ["arn:aws:s3:::geoflow-upload/qgis-plugins/*"],
        )

    def test_workflow_applies_before_publish_and_rolls_back_on_failure(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("apply_qgis_plugin_s3_access.py", text)
        self.assertIn(
            "GRANT_QGIS_PLUGIN_S3:geoflow-upload:qgis-plugins", text
        )
        self.assertIn("rollback_qgis_access", text)
        self.assertIn("qgis_access_created", text)
        self.assertLess(
            text.rindex("apply_qgis_plugin_s3_access.py\" apply"),
            text.rindex("publish_qgis_plugin_repository.py\""),
        )

    def test_created_policy_is_marked_and_owned_rollback_removes_only_it(self):
        module = load_module()

        class FakeIam:
            document = None
            deleted = False

            def get_user_policy(self, **kwargs):
                if self.document is None:
                    class Missing(Exception):
                        response = {"Error": {"Code": "NoSuchEntity"}}

                    raise Missing()
                return {"PolicyDocument": self.document}

            def put_user_policy(self, **kwargs):
                self.document = json.loads(kwargs["PolicyDocument"])

            def delete_user_policy(self, **kwargs):
                self.deleted = True
                self.document = None

        fake = FakeIam()
        module.classify = lambda exc: str(exc.response["Error"]["Code"])
        module.clients = lambda: (fake, "user", "runtime")
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"AWS_S3_BUCKET": "geoflow-upload"}
        ):
            marker = Path(directory) / "created"
            module.apply(marker, module.CONFIRMATION)
            self.assertTrue(marker.is_file())
            self.assertEqual(
                module.canonical(fake.document),
                module.canonical(module.policy_document()),
            )
            module.rollback(marker, module.CONFIRMATION)
            self.assertTrue(fake.deleted)
            self.assertFalse(marker.exists())

    def test_preexisting_exact_policy_is_not_marked_for_rollback(self):
        module = load_module()

        class FakeIam:
            document = module.policy_document()

            def get_user_policy(self, **kwargs):
                return {"PolicyDocument": self.document}

        fake = FakeIam()
        module.clients = lambda: (fake, "user", "runtime")
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"AWS_S3_BUCKET": "geoflow-upload"}
        ):
            marker = Path(directory) / "created"
            module.apply(marker, module.CONFIRMATION)
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
