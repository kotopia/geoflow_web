from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass

import boto3


SECRET_REFERENCE_PREFIX = "aws-secretsmanager:"


class TenantDBCredentialError(RuntimeError):
    """Raised when a tenant database credential cannot be safely resolved."""


@dataclass(frozen=True)
class TenantDBSecretReference:
    secret_id: str
    json_key: str | None = None


def _enabled(environ: Mapping[str, str], name: str) -> bool:
    return str(environ.get(name) or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }


def parse_tenant_db_secret_reference(value: object) -> TenantDBSecretReference | None:
    text = str(value or "").strip()
    if not text.startswith(SECRET_REFERENCE_PREFIX):
        return None

    payload = text[len(SECRET_REFERENCE_PREFIX):]
    secret_id, separator, json_key = payload.partition("#")
    secret_id = secret_id.strip()
    json_key = json_key.strip() if separator else ""
    if not secret_id:
        raise TenantDBCredentialError("Tenant database secret reference is invalid")
    if separator and not json_key:
        raise TenantDBCredentialError("Tenant database secret reference is invalid")
    return TenantDBSecretReference(secret_id=secret_id, json_key=json_key or None)


def is_tenant_db_secret_reference(value: object) -> bool:
    try:
        return parse_tenant_db_secret_reference(value) is not None
    except TenantDBCredentialError:
        return False


def _secretsmanager_client(environ: Mapping[str, str]):
    return boto3.client(
        "secretsmanager",
        region_name=str(environ.get("AWS_REGION") or "ap-northeast-2").strip(),
    )


def resolve_tenant_db_password(
    stored_value: object,
    *,
    environ: Mapping[str, str] = os.environ,
    client=None,
) -> str:
    """Resolve a tenant DB password without logging or returning secret metadata."""

    raw = str(stored_value or "").strip()
    if not raw:
        raise TenantDBCredentialError("Tenant database credential is unavailable")

    reference = parse_tenant_db_secret_reference(raw)
    require_reference = _enabled(environ, "TENANT_DB_REQUIRE_SECRET_REFERENCES")
    if reference is None:
        if require_reference:
            raise TenantDBCredentialError(
                "Tenant database credential must use a secret reference"
            )
        return raw

    secret_client = client or _secretsmanager_client(environ)
    try:
        response = secret_client.get_secret_value(SecretId=reference.secret_id)
    except Exception as exc:
        raise TenantDBCredentialError(
            "Tenant database secret could not be resolved"
        ) from exc

    secret_string = response.get("SecretString")
    if not isinstance(secret_string, str) or not secret_string:
        raise TenantDBCredentialError("Tenant database secret is unavailable")

    if reference.json_key is None:
        return secret_string

    try:
        payload = json.loads(secret_string)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TenantDBCredentialError(
            "Tenant database secret payload is invalid"
        ) from exc
    if not isinstance(payload, dict):
        raise TenantDBCredentialError("Tenant database secret payload is invalid")

    resolved = payload.get(reference.json_key)
    if not isinstance(resolved, str) or not resolved:
        raise TenantDBCredentialError("Tenant database secret key is unavailable")
    return resolved
