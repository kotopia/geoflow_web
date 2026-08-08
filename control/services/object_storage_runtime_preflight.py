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

    return tuple(checks)
