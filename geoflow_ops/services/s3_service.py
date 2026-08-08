"""Private S3 presign and upload-verification helpers."""
from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
from typing import Literal, Optional
from urllib.parse import quote

import boto3
from botocore.client import Config


class S3ObjectVerificationError(RuntimeError):
    pass


@dataclass(frozen=True)
class UploadedObjectMetadata:
    size_bytes: int
    content_type: str
    server_side_encryption: str
    kms_key_id: str
    encryption_matches: bool


def get_s3_client():
    return boto3.client(
        "s3",
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        region_name=os.environ.get("AWS_REGION", "ap-northeast-2"),
        config=Config(signature_version="s3v4"),
    )


def get_bucket_name() -> str:
    bucket = os.environ.get("AWS_S3_BUCKET")
    if not bucket:
        raise ValueError("AWS_S3_BUCKET not configured")
    return bucket


def get_sse_config() -> dict:
    kms_key_id = os.environ.get("AWS_KMS_KEY_ID")
    if kms_key_id:
        return {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": kms_key_id}
    return {"ServerSideEncryption": "AES256"}


def build_object_key(
    tenant_db_alias: str,
    entity_type: Literal["employee", "contract", "orgunit", "event"],
    entity_id: str,
    purpose: str,
    extension: str,
    event_id: Optional[str] = None,
) -> str:
    now = datetime.now(dt_timezone.utc)
    yyyy = now.strftime("%Y")
    mm = now.strftime("%m")
    unique_id = uuid.uuid4().hex
    folders = {
        "employee": "employees",
        "contract": "contracts",
        "orgunit": "orgunits",
        "event": "events",
    }
    if entity_type not in folders:
        raise ValueError("Unsupported entity type")
    if entity_type == "event":
        if not event_id or str(event_id) != str(entity_id):
            raise ValueError("Canonical event id is required")
        entity_id = str(event_id)
    return (
        f"tenants/{tenant_db_alias}/{folders[entity_type]}/{entity_id}/"
        f"{purpose}/{yyyy}/{mm}/{unique_id}.{extension}"
    )


def generate_presigned_put_url(
    object_key: str,
    mime_type: Optional[str] = None,
    expires_in: int = 3600,
) -> dict:
    client = get_s3_client()
    sse = get_sse_config()
    params = {"Bucket": get_bucket_name(), "Key": object_key, **sse}
    if mime_type:
        params["ContentType"] = mime_type
    url = client.generate_presigned_url("put_object", Params=params, ExpiresIn=expires_in)
    headers = {}
    if mime_type:
        headers["Content-Type"] = mime_type
    if sse.get("ServerSideEncryption"):
        headers["x-amz-server-side-encryption"] = sse["ServerSideEncryption"]
    if sse.get("SSEKMSKeyId"):
        headers["x-amz-server-side-encryption-aws-kms-key-id"] = sse["SSEKMSKeyId"]
    return {"presigned_url": url, "headers": headers}


def _safe_download_filename(filename: Optional[str]) -> str:
    value = str(filename or "download").strip()
    value = re.sub(r"[\r\n\\\"]+", "_", value)
    value = "".join(ch for ch in value if ord(ch) >= 32 and ord(ch) != 127)
    return value[:255] or "download"


def generate_presigned_get_url(
    object_key: str,
    expires_in: int = 3600,
    content_type: Optional[str] = None,
    disposition: Optional[str] = None,
    filename: Optional[str] = None,
) -> str:
    if disposition not in (None, "inline", "attachment"):
        raise ValueError("Unsupported disposition")
    params = {"Bucket": get_bucket_name(), "Key": object_key}
    if content_type:
        params["ResponseContentType"] = content_type
    if disposition == "inline":
        params["ResponseContentDisposition"] = "inline"
    elif disposition == "attachment":
        safe_name = _safe_download_filename(filename)
        params["ResponseContentDisposition"] = (
            "attachment; filename*=UTF-8''" + quote(safe_name, safe="")
        )
    return get_s3_client().generate_presigned_url(
        "get_object", Params=params, ExpiresIn=expires_in
    )


def head_private_object(object_key: str) -> UploadedObjectMetadata:
    try:
        response = get_s3_client().head_object(
            Bucket=get_bucket_name(),
            Key=object_key,
        )
    except Exception as exc:
        raise S3ObjectVerificationError("Unable to verify uploaded object") from exc

    expected = get_sse_config()
    actual_sse = str(response.get("ServerSideEncryption") or "")
    actual_kms = str(response.get("SSEKMSKeyId") or "")
    expected_sse = str(expected.get("ServerSideEncryption") or "")
    expected_kms = str(expected.get("SSEKMSKeyId") or "")
    encryption_matches = actual_sse == expected_sse
    if expected_sse == "aws:kms":
        encryption_matches = (
            encryption_matches and bool(actual_kms) and actual_kms == expected_kms
        )

    return UploadedObjectMetadata(
        size_bytes=int(response.get("ContentLength") or 0),
        content_type=str(response.get("ContentType") or "")
        .split(";", 1)[0]
        .strip()
        .lower(),
        server_side_encryption=actual_sse,
        kms_key_id=actual_kms,
        encryption_matches=encryption_matches,
    )


def extract_extension(filename: str) -> str:
    """Return a short safe extension suitable for a private S3 object key."""

    if "." not in str(filename or ""):
        return "bin"
    extension = str(filename).rsplit(".", 1)[-1].strip().lower()
    if not re.fullmatch(r"[a-z0-9]{1,16}", extension):
        return "bin"
    return extension
