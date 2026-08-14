from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock

from botocore.exceptions import ClientError


PROBE_PATH = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "ops"
    / "phase2_aws_role_readiness_probe.py"
)


def _load_probe():
    spec = importlib.util.spec_from_file_location("phase2_role_readiness_probe", PROBE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load Phase 2 role readiness probe")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Phase2AwsRoleReadinessProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.probe = _load_probe()

    def _client_error(self, code: str) -> ClientError:
        return ClientError(
            {"Error": {"Code": code, "Message": "redacted test message"}},
            "TestOperation",
        )

    def test_access_denied_is_reported_as_bounded_category(self):
        self.assertEqual(
            self.probe.classify_aws_error(self._client_error("AccessDeniedException")),
            "access_denied",
        )

    def test_endpoint_mismatch_is_reported_without_identifier(self):
        self.assertEqual(
            self.probe.classify_aws_error(
                self._client_error("AuthorizationHeaderMalformed")
            ),
            "region_or_endpoint",
        )

    def test_minimum_s3_contract_does_not_require_head_bucket(self):
        self.assertTrue(self.probe.s3_minimum_policy_ready("ok", "ok"))
        self.assertTrue(
            self.probe.s3_minimum_policy_ready("ok", "not_tested_no_object")
        )
        self.assertFalse(self.probe.s3_minimum_policy_ready("failed", "ok"))
        self.assertFalse(self.probe.s3_minimum_policy_ready("ok", "failed"))

    def test_policy_inventory_reports_counts_only(self):
        iam = Mock()
        iam.list_role_policies.return_value = {
            "PolicyNames": ["redacted-inline"],
            "IsTruncated": False,
        }
        iam.list_attached_role_policies.return_value = {
            "AttachedPolicies": [
                {"PolicyName": "redacted-managed", "PolicyArn": "redacted"}
            ],
            "IsTruncated": False,
        }
        session = Mock()
        session.client.return_value = iam

        self.assertEqual(
            self.probe.inventory_role_policies(session, "redacted-role"),
            ("ok", 1, 1, "no"),
        )
        iam.list_role_policies.assert_called_once_with(
            RoleName="redacted-role",
            MaxItems=1000,
        )
        iam.list_attached_role_policies.assert_called_once_with(
            RoleName="redacted-role",
            MaxItems=1000,
        )

    def test_policy_inventory_access_denied_is_bounded(self):
        iam = Mock()
        iam.list_role_policies.side_effect = self._client_error("AccessDenied")
        session = Mock()
        session.client.return_value = iam

        self.assertEqual(
            self.probe.inventory_role_policies(session, "redacted-role"),
            ("access_denied", None, None, "unknown"),
        )

    def test_policy_inventory_requires_no_static_fallback_values(self):
        self.assertEqual(
            self.probe.inventory_role_policies(None, "redacted-role"),
            ("no_static_fallback", None, None, "unknown"),
        )

    def test_output_vocabulary_is_fixed_and_identifier_safe(self):
        self.assertEqual(
            self.probe.SAFE_ERROR_KINDS,
            (
                "access_denied",
                "not_found",
                "kms_or_decryption",
                "region_or_endpoint",
                "no_credentials",
                "transport",
                "resolver_validation",
                "other",
            ),
        )


if __name__ == "__main__":
    unittest.main()
