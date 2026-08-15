from copy import deepcopy

from botocore.exceptions import ClientError
from django.test import SimpleTestCase

from control.services.tenant_provisioning_iam_readers import (
    AwsIamInlineTenantSecretGrantReadOnlyVerifier,
)
from control.services.tenant_provisioning_runtime_policy import (
    TenantProvisioningRuntimePolicyError,
    build_exact_tenant_secret_read_policy,
)


class FakeIamClient:
    def __init__(self, *, response=None, error_code=None):
        self.response = response
        self.error_code = error_code
        self.calls = []

    def get_role_policy(self, *, RoleName, PolicyName):
        self.calls.append(("get_role_policy", RoleName, PolicyName))
        if self.error_code:
            raise ClientError(
                {"Error": {"Code": self.error_code, "Message": "private provider detail"}},
                "GetRolePolicy",
            )
        return self.response

    def put_role_policy(self, **kwargs):
        raise AssertionError("put_role_policy_forbidden")

    def delete_role_policy(self, **kwargs):
        raise AssertionError("delete_role_policy_forbidden")

    def attach_role_policy(self, **kwargs):
        raise AssertionError("attach_role_policy_forbidden")


class TenantProvisioningIamReadOnlyVerifierTests(SimpleTestCase):
    def setUp(self):
        self.secret_id = (
            "geoflow/tenant-db/2f0b2fc5-4baa-4fea-b4aa-2ba6e1e0dc11/password"
        )
        self.resource = (
            "arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:"
            f"{self.secret_id}-??????"
        )
        self.policy = build_exact_tenant_secret_read_policy(
            secret_resource_pattern=self.resource,
        )

    def _verifier(self, client):
        return AwsIamInlineTenantSecretGrantReadOnlyVerifier(
            client,
            role_name="geoflow-runtime-role",
            policy_name="geoflow-tenant-db-secret-read",
            secret_id=self.secret_id,
            secret_resource_pattern=self.resource,
        )

    def test_exact_inline_grant_is_ready_using_get_only(self):
        client = FakeIamClient(response={"PolicyDocument": self.policy})
        verifier = self._verifier(client)

        self.assertTrue(verifier.read_only)
        self.assertTrue(verifier.exact_grant_ready())
        self.assertEqual(
            client.calls,
            [
                (
                    "get_role_policy",
                    "geoflow-runtime-role",
                    "geoflow-tenant-db-secret-read",
                )
            ],
        )

    def test_missing_inline_grant_is_definitively_not_ready(self):
        client = FakeIamClient(error_code="NoSuchEntity")

        self.assertFalse(self._verifier(client).exact_grant_ready())
        self.assertEqual(len(client.calls), 1)

    def test_ambiguous_provider_failure_propagates_fail_closed(self):
        client = FakeIamClient(error_code="AccessDenied")

        with self.assertRaises(ClientError):
            self._verifier(client).exact_grant_ready()

        self.assertEqual(len(client.calls), 1)

    def test_broader_or_mutating_policy_is_not_ready(self):
        changed = deepcopy(self.policy)
        changed["Statement"][0]["Action"] = [
            "secretsmanager:GetSecretValue",
            "secretsmanager:PutSecretValue",
        ]
        client = FakeIamClient(response={"PolicyDocument": changed})

        self.assertFalse(self._verifier(client).exact_grant_ready())

    def test_different_resource_is_not_ready(self):
        changed = deepcopy(self.policy)
        changed["Statement"][0]["Resource"] = (
            "arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:"
            "geoflow/tenant-db/33bfa40e-d2e5-4f75-a2dc-3945d815f863/password-??????"
        )
        client = FakeIamClient(response={"PolicyDocument": changed})

        self.assertFalse(self._verifier(client).exact_grant_ready())

    def test_resource_for_different_plan_secret_is_rejected_before_provider_read(self):
        client = FakeIamClient(response={"PolicyDocument": self.policy})
        other_secret_id = (
            "geoflow/tenant-db/33bfa40e-d2e5-4f75-a2dc-3945d815f863/password"
        )

        with self.assertRaises(TenantProvisioningRuntimePolicyError) as caught:
            AwsIamInlineTenantSecretGrantReadOnlyVerifier(
                client,
                role_name="geoflow-runtime-role",
                policy_name="geoflow-tenant-db-secret-read",
                secret_id=other_secret_id,
                secret_resource_pattern=self.resource,
            )

        self.assertEqual(caught.exception.code, "secret_resource_plan_mismatch")
        self.assertEqual(client.calls, [])

    def test_malformed_provider_response_fails_closed(self):
        for response in (None, {}, {"PolicyDocument": "not-a-document"}):
            with self.subTest(response=response):
                client = FakeIamClient(response=response)
                self.assertFalse(self._verifier(client).exact_grant_ready())

    def test_constructor_rejects_missing_identity_before_provider_read(self):
        client = FakeIamClient(response={"PolicyDocument": self.policy})

        with self.assertRaisesRegex(ValueError, "runtime_role_name_required"):
            AwsIamInlineTenantSecretGrantReadOnlyVerifier(
                client,
                role_name="",
                policy_name="policy",
                secret_id=self.secret_id,
                secret_resource_pattern=self.resource,
            )
        with self.assertRaisesRegex(ValueError, "runtime_policy_name_required"):
            AwsIamInlineTenantSecretGrantReadOnlyVerifier(
                client,
                role_name="role",
                policy_name="",
                secret_id=self.secret_id,
                secret_resource_pattern=self.resource,
            )

        self.assertEqual(client.calls, [])
