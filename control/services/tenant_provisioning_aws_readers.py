from __future__ import annotations

from typing import Any, Protocol

from botocore.exceptions import ClientError


class SecretsManagerDescribeClient(Protocol):
    """Minimal Secrets Manager client surface permitted by this adapter."""

    def describe_secret(self, *, SecretId: str) -> dict[str, Any]: ...


class AwsSecretsManagerReadOnlyCatalog:
    """Read-only Secrets Manager metadata reader for one exact secret id.

    The caller must inject a client. This module deliberately does not construct
    boto3 sessions/clients, discover credentials, read secret values, or expose
    any mutation method. A successful ``DescribeSecret`` definitively means the
    target exists. Only AWS ``ResourceNotFoundException`` is treated as a
    definitive absence; permission, transport, throttling, and other ambiguous
    failures propagate so the outer provisioning readiness contract fails closed.
    """

    read_only = True

    def __init__(self, client: SecretsManagerDescribeClient):
        if client is None:
            raise ValueError("secrets_manager_client_required")
        self._client = client

    def secret_exists(self, *, secret_id: str) -> bool:
        exact_secret_id = str(secret_id or "").strip()
        if not exact_secret_id:
            raise ValueError("secret_id_required")

        try:
            self._client.describe_secret(SecretId=exact_secret_id)
        except ClientError as exc:
            error = exc.response.get("Error", {}) if exc.response else {}
            code = str(error.get("Code") or "")
            if code == "ResourceNotFoundException":
                return False
            raise

        return True
