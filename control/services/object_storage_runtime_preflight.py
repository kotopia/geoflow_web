from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass


EXPECTED_AWS_REGION = "ap-northeast-2"


@dataclass(frozen=True)
class ObjectStorageRuntimeCheck:
    code: str
    ready: bool
    message: str


def _enabled(environ: Mapping[str, str], name: str) -> bool:
    return str(environ.get(name) or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }


def inspect_object_storage_runtime(
    *,
    environ: Mapping[str, str] = os.environ,
) -> tuple[ObjectStorageRuntimeCheck, ...]:
    """Inspect S3 configuration shape only; never create an AWS client or make I/O."""

    checks: list[ObjectStorageRuntimeCheck] = []

    bucket = str(environ.get("AWS_S3_BUCKET") or "").strip()
    checks.append(
        ObjectStorageRuntimeCheck(
            code="s3_bucket_configured",
            ready=bool(bucket),
            message=(
                "Private S3 bucket is configured."
                if bucket
                else "Configure the private S3 bucket for production attachments."
            ),
        )
    )

    region = str(environ.get("AWS_REGION") or EXPECTED_AWS_REGION).strip()
    region_ready = region == EXPECTED_AWS_REGION
    checks.append(
        ObjectStorageRuntimeCheck(
            code="s3_region",
            ready=region_ready,
            message=(
                "S3 region matches the approved Seoul region."
                if region_ready
                else "Use the approved Seoul AWS region for GeoFlow object storage."
            ),
        )
    )

    access_key_present = bool(str(environ.get("AWS_ACCESS_KEY_ID") or "").strip())
    secret_key_present = bool(
        str(environ.get("AWS_SECRET_ACCESS_KEY") or "").strip()
    )
    credential_pair_ready = access_key_present == secret_key_present
    checks.append(
        ObjectStorageRuntimeCheck(
            code="aws_credential_pair",
            ready=credential_pair_ready,
            message=(
                "AWS static credentials are either paired or omitted for the runtime role."
                if credential_pair_ready
                else "Do not configure only one half of an AWS static credential pair."
            ),
        )
    )

    role_only_required = _enabled(environ, "AWS_REQUIRE_ROLE_CREDENTIALS")
    static_or_profile_source_present = any(
        bool(str(environ.get(name) or "").strip())
        for name in (
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
            "AWS_PROFILE",
            "AWS_DEFAULT_PROFILE",
            "AWS_SHARED_CREDENTIALS_FILE",
        )
    )
    role_only_ready = not role_only_required or not static_or_profile_source_present
    checks.append(
        ObjectStorageRuntimeCheck(
            code="aws_role_only_runtime",
            ready=role_only_ready,
            message=(
                "Role-only AWS runtime guard is enabled and no static/profile credential source is configured."
                if role_only_required and role_only_ready
                else (
                    "Remove static/profile AWS credential sources before enabling role-only runtime."
                    if role_only_required
                    else "Role-only AWS runtime guard is not enabled yet; compatibility mode remains active."
                )
            ),
        )
    )

    return tuple(checks)
