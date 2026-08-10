from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent
RUNTIME_POLICY = ROOT / "docs" / "phase2-runtime-iam-policy-template.json"
TRUST_POLICY = ROOT / "docs" / "phase2-ec2-trust-policy-template.json"


class Phase2IAMPolicyContractTests(unittest.TestCase):
    def _runtime(self) -> dict:
        return json.loads(RUNTIME_POLICY.read_text(encoding="utf-8"))

    def _trust(self) -> dict:
        return json.loads(TRUST_POLICY.read_text(encoding="utf-8"))

    def test_runtime_policy_contains_only_required_service_actions(self):
        policy = self._runtime()
        actions = set()
        resources = []
        for statement in policy["Statement"]:
            raw_actions = statement.get("Action", [])
            if isinstance(raw_actions, str):
                raw_actions = [raw_actions]
            actions.update(raw_actions)
            raw_resources = statement.get("Resource", [])
            if isinstance(raw_resources, str):
                raw_resources = [raw_resources]
            resources.extend(raw_resources)

        self.assertEqual(
            actions,
            {
                "secretsmanager:GetSecretValue",
                "s3:ListBucket",
                "s3:GetObject",
                "s3:PutObject",
            },
        )
        self.assertNotIn("*", resources)
        self.assertNotIn("s3:DeleteObject", actions)
        self.assertFalse(any(action.startswith("iam:") for action in actions))
        self.assertFalse(any(action.startswith("ec2:") for action in actions))
        self.assertFalse(any(action.startswith("rds:") for action in actions))

    def test_s3_scope_is_private_tenant_prefix_only(self):
        policy = self._runtime()
        list_statement = next(
            item for item in policy["Statement"] if item["Sid"] == "ListPrivateTenantPrefix"
        )
        object_statement = next(
            item
            for item in policy["Statement"]
            if item["Sid"] == "ReadWritePrivateTenantObjects"
        )
        self.assertEqual(
            list_statement["Condition"]["StringLike"]["s3:prefix"],
            ["tenants/*"],
        )
        self.assertEqual(
            object_statement["Resource"],
            ["arn:aws:s3:::${GEOFLOW_BUCKET_NAME}/tenants/*"],
        )

    def test_secret_scope_uses_placeholders_not_real_identifiers(self):
        policy_text = RUNTIME_POLICY.read_text(encoding="utf-8")
        self.assertIn("${AWS_REGION}", policy_text)
        self.assertIn("${ACCOUNT_ID}", policy_text)
        self.assertIn("${TENANT_SECRET_NAME_PREFIX}", policy_text)
        self.assertIn("${GEOFLOW_BUCKET_NAME}", policy_text)
        self.assertNotRegex(policy_text, r"\b\d{12}\b")

    def test_trust_policy_allows_only_ec2_assume_role(self):
        policy = self._trust()
        self.assertEqual(policy["Version"], "2012-10-17")
        self.assertEqual(len(policy["Statement"]), 1)
        statement = policy["Statement"][0]
        self.assertEqual(statement["Effect"], "Allow")
        self.assertEqual(statement["Principal"], {"Service": "ec2.amazonaws.com"})
        self.assertEqual(statement["Action"], "sts:AssumeRole")


if __name__ == "__main__":
    unittest.main()
