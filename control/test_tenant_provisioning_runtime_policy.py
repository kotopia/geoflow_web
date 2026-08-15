from copy import deepcopy

from django.test import SimpleTestCase

from control.services.tenant_provisioning_runtime_policy import (
    TenantProvisioningRuntimePolicyError,
    build_exact_tenant_secret_read_policy,
    normalize_tenant_secret_resource_pattern,
    runtime_policy_matches_exact_tenant_secret_read,
)


class TenantProvisioningRuntimePolicyTests(SimpleTestCase):
    def setUp(self):
        self.resource = (
            "arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:"
            "geoflow/tenant-db/2f0b2fc5-4baa-4fea-b4aa-2ba6e1e0dc11/password-??????"
        )

    def test_builds_only_get_secret_value_for_exact_tenant_secret_family(self):
        policy = build_exact_tenant_secret_read_policy(
            secret_resource_pattern=self.resource,
        )

        self.assertEqual(
            policy,
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Sid": "GeoFlowTenantDbSecretRead",
                        "Effect": "Allow",
                        "Action": "secretsmanager:GetSecretValue",
                        "Resource": self.resource,
                    }
                ],
            },
        )
        self.assertTrue(
            runtime_policy_matches_exact_tenant_secret_read(
                policy,
                secret_resource_pattern=self.resource,
            )
        )

    def test_provider_suffix_is_the_only_wildcard_allowed(self):
        invalid = (
            "arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:"
            "geoflow/tenant-db/*/password-??????"
        )

        with self.assertRaises(TenantProvisioningRuntimePolicyError) as caught:
            normalize_tenant_secret_resource_pattern(invalid)

        self.assertEqual(caught.exception.code, "secret_resource_pattern_not_exact")

    def test_suffix_must_be_exactly_six_single_character_wildcards(self):
        too_short = (
            "arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:"
            "geoflow/tenant-db/2f0b2fc5-4baa-4fea-b4aa-2ba6e1e0dc11/password-?????"
        )
        broad_star = (
            "arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:"
            "geoflow/tenant-db/2f0b2fc5-4baa-4fea-b4aa-2ba6e1e0dc11/password-*"
        )

        for invalid in (too_short, broad_star):
            with self.subTest(invalid=invalid):
                with self.assertRaises(TenantProvisioningRuntimePolicyError) as caught:
                    normalize_tenant_secret_resource_pattern(invalid)
                self.assertEqual(
                    caught.exception.code,
                    "secret_resource_pattern_not_exact",
                )

    def test_non_tenant_secret_resource_is_rejected(self):
        invalid = (
            "arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:"
            "geoflow/shared/password-??????"
        )

        with self.assertRaises(TenantProvisioningRuntimePolicyError) as caught:
            build_exact_tenant_secret_read_policy(secret_resource_pattern=invalid)

        self.assertEqual(caught.exception.code, "secret_resource_pattern_invalid")

    def test_any_extra_action_fails_closed(self):
        policy = build_exact_tenant_secret_read_policy(
            secret_resource_pattern=self.resource,
        )
        changed = deepcopy(policy)
        changed["Statement"][0]["Action"] = [
            "secretsmanager:GetSecretValue",
            "secretsmanager:PutSecretValue",
        ]

        self.assertFalse(
            runtime_policy_matches_exact_tenant_secret_read(
                changed,
                secret_resource_pattern=self.resource,
            )
        )

    def test_broader_resource_fails_closed(self):
        policy = build_exact_tenant_secret_read_policy(
            secret_resource_pattern=self.resource,
        )
        changed = deepcopy(policy)
        changed["Statement"][0]["Resource"] = (
            "arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:"
            "geoflow/tenant-db/*"
        )

        self.assertFalse(
            runtime_policy_matches_exact_tenant_secret_read(
                changed,
                secret_resource_pattern=self.resource,
            )
        )

    def test_different_tenant_resource_fails_closed(self):
        policy = build_exact_tenant_secret_read_policy(
            secret_resource_pattern=self.resource,
        )
        other = (
            "arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:"
            "geoflow/tenant-db/33bfa40e-d2e5-4f75-a2dc-3945d815f863/password-??????"
        )

        self.assertFalse(
            runtime_policy_matches_exact_tenant_secret_read(
                policy,
                secret_resource_pattern=other,
            )
        )

    def test_extra_statement_or_policy_field_fails_closed(self):
        policy = build_exact_tenant_secret_read_policy(
            secret_resource_pattern=self.resource,
        )
        extra_statement = deepcopy(policy)
        extra_statement["Statement"].append(
            {
                "Effect": "Allow",
                "Action": "secretsmanager:DescribeSecret",
                "Resource": self.resource,
            }
        )
        extra_field = deepcopy(policy)
        extra_field["Statement"][0]["Condition"] = {"StringEquals": {"x": "y"}}

        self.assertFalse(
            runtime_policy_matches_exact_tenant_secret_read(
                extra_statement,
                secret_resource_pattern=self.resource,
            )
        )
        self.assertFalse(
            runtime_policy_matches_exact_tenant_secret_read(
                extra_field,
                secret_resource_pattern=self.resource,
            )
        )

    def test_malformed_document_or_expected_pattern_fails_closed(self):
        self.assertFalse(
            runtime_policy_matches_exact_tenant_secret_read(
                None,
                secret_resource_pattern=self.resource,
            )
        )
        self.assertFalse(
            runtime_policy_matches_exact_tenant_secret_read(
                {},
                secret_resource_pattern="",
            )
        )
