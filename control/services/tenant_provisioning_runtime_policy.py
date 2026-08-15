from __future__ import annotations

import re
from typing import Any, Mapping


_POLICY_VERSION = "2012-10-17"
_POLICY_SID = "GeoFlowTenantDbSecretRead"
_GET_SECRET_VALUE = "secretsmanager:GetSecretValue"
_SECRET_RESOURCE_PATTERN = re.compile(
    r"^arn:[a-z0-9-]+:secretsmanager:[a-z0-9-]+:[0-9]{12}:"
    r"secret:geoflow/tenant-db/"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
    r"/password-\*$"
)


class TenantProvisioningRuntimePolicyError(RuntimeError):
    """Fail-closed runtime policy contract error with a non-secret reason code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def normalize_tenant_secret_resource_pattern(value: object) -> str:
    """Validate the one allowed future tenant-secret ARN pattern.

    AWS Secrets Manager appends a six-character suffix to secret ARNs. A future
    provisioning backend therefore cannot know the final ARN before secret
    creation; the narrow pre-provision contract is the exact GeoFlow tenant secret
    path plus only the provider suffix wildcard (``-*``). No other wildcard or
    resource family is accepted here.
    """

    text = str(value or "").strip()
    if not text:
        raise TenantProvisioningRuntimePolicyError("secret_resource_pattern_required")
    if text.count("*") != 1 or "?" in text:
        raise TenantProvisioningRuntimePolicyError("secret_resource_pattern_not_exact")
    if not _SECRET_RESOURCE_PATTERN.fullmatch(text):
        raise TenantProvisioningRuntimePolicyError("secret_resource_pattern_invalid")
    return text


def build_exact_tenant_secret_read_policy(
    *,
    secret_resource_pattern: object,
) -> dict[str, Any]:
    """Build the only reviewed runtime grant document for one tenant secret.

    This function is pure data construction. It creates no IAM client, performs no
    AWS call, and cannot attach or broaden a policy. The document grants only
    ``secretsmanager:GetSecretValue`` to the exact tenant-secret ARN family needed
    to accommodate Secrets Manager's provider-generated suffix.
    """

    resource = normalize_tenant_secret_resource_pattern(secret_resource_pattern)
    return {
        "Version": _POLICY_VERSION,
        "Statement": [
            {
                "Sid": _POLICY_SID,
                "Effect": "Allow",
                "Action": _GET_SECRET_VALUE,
                "Resource": resource,
            }
        ],
    }


def runtime_policy_matches_exact_tenant_secret_read(
    policy_document: object,
    *,
    secret_resource_pattern: object,
) -> bool:
    """Return True only for the exact reviewed single-secret policy document.

    Any additional statement, action, resource, condition, principal, NotAction,
    NotResource, wildcard action, or broader resource necessarily makes the
    document unequal and therefore fails closed.
    """

    try:
        expected = build_exact_tenant_secret_read_policy(
            secret_resource_pattern=secret_resource_pattern,
        )
    except TenantProvisioningRuntimePolicyError:
        return False

    if not isinstance(policy_document, Mapping):
        return False
    return dict(policy_document) == expected
