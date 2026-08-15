from __future__ import annotations

from typing import Any, Protocol

from botocore.exceptions import ClientError

from control.services.tenant_provisioning_runtime_policy import (
    normalize_tenant_secret_resource_pattern,
    runtime_policy_matches_exact_tenant_secret_read,
)


class IamGetRolePolicyClient(Protocol):
    """Minimal read-only IAM client surface permitted by this adapter."""

    def get_role_policy(self, *, RoleName: str, PolicyName: str) -> dict[str, Any]: ...


class AwsIamInlineTenantSecretGrantReadOnlyVerifier:
    """Read-only verifier for one dedicated inline tenant-secret IAM grant.

    The caller injects an IAM client plus the already-reviewed runtime role and
    inline policy names. This adapter performs only ``GetRolePolicy`` and validates
    that the returned document is the exact single-secret policy defined by the
    runtime policy contract. It never creates, attaches, updates, detaches, or
    deletes a policy and never constructs an AWS session or credential source.

    ``NoSuchEntity`` is a definitive not-ready result. Permission, transport,
    throttling, malformed response, or any other ambiguous failure propagates or
    fails closed rather than being interpreted as safe.
    """

    read_only = True

    def __init__(
        self,
        client: IamGetRolePolicyClient,
        *,
        role_name: object,
        policy_name: object,
        secret_resource_pattern: object,
    ):
        if client is None:
            raise ValueError("iam_client_required")

        normalized_role = str(role_name or "").strip()
        normalized_policy = str(policy_name or "").strip()
        if not normalized_role:
            raise ValueError("runtime_role_name_required")
        if not normalized_policy:
            raise ValueError("runtime_policy_name_required")

        self._client = client
        self._role_name = normalized_role
        self._policy_name = normalized_policy
        self._secret_resource_pattern = normalize_tenant_secret_resource_pattern(
            secret_resource_pattern
        )

    def exact_grant_ready(self) -> bool:
        try:
            response = self._client.get_role_policy(
                RoleName=self._role_name,
                PolicyName=self._policy_name,
            )
        except ClientError as exc:
            error = exc.response.get("Error", {}) if exc.response else {}
            code = str(error.get("Code") or "")
            if code == "NoSuchEntity":
                return False
            raise

        if not isinstance(response, dict):
            return False
        policy_document = response.get("PolicyDocument")
        return runtime_policy_matches_exact_tenant_secret_read(
            policy_document,
            secret_resource_pattern=self._secret_resource_pattern,
        )
