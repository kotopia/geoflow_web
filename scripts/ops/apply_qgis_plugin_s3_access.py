#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import unquote


BUCKET = "geoflow-upload"
PREFIX = "qgis-plugins"
POLICY_NAME = "GeoFlowQgisPluginRepository20260910"
CONFIRMATION = "GRANT_QGIS_PLUGIN_S3:geoflow-upload:qgis-plugins"


def fail(reason: str) -> None:
    raise SystemExit(f"qgis_plugin_s3_access_blocker={reason}")


def policy_document() -> dict[str, Any]:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ReadWriteQgisPluginRepository",
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:PutObject"],
                "Resource": [f"arn:aws:s3:::{BUCKET}/{PREFIX}/*"],
            }
        ],
    }


def canonical(document: Any) -> str:
    if isinstance(document, str):
        document = json.loads(unquote(document))
    return json.dumps(document, sort_keys=True, separators=(",", ":"))


def principal_target(arn: str) -> tuple[str, str]:
    marker = ":user/"
    if marker in arn:
        username = arn.split(marker, 1)[1].rsplit("/", 1)[-1]
        if username:
            return "user", username
    marker = ":assumed-role/"
    if marker in arn:
        role_name = arn.split(marker, 1)[1].split("/", 1)[0]
        if role_name:
            return "role", role_name
    fail("unsupported_runtime_principal")


def classify(exc: BaseException) -> str:
    try:
        from botocore.exceptions import ClientError
    except Exception:
        return "unknown"
    if isinstance(exc, ClientError):
        return str((exc.response.get("Error") or {}).get("Code") or "unknown")
    return "unknown"


def get_policy(iam, kind: str, name: str):
    try:
        if kind == "user":
            response = iam.get_user_policy(UserName=name, PolicyName=POLICY_NAME)
        else:
            response = iam.get_role_policy(RoleName=name, PolicyName=POLICY_NAME)
        return response.get("PolicyDocument")
    except Exception as exc:
        if classify(exc) == "NoSuchEntity":
            return None
        fail("policy_read_" + classify(exc))


def put_policy(iam, kind: str, name: str, document: dict[str, Any]) -> None:
    encoded = json.dumps(document, separators=(",", ":"))
    try:
        if kind == "user":
            iam.put_user_policy(
                UserName=name, PolicyName=POLICY_NAME, PolicyDocument=encoded
            )
        else:
            iam.put_role_policy(
                RoleName=name, PolicyName=POLICY_NAME, PolicyDocument=encoded
            )
    except Exception as exc:
        fail("policy_put_" + classify(exc))


def delete_policy(iam, kind: str, name: str) -> None:
    try:
        if kind == "user":
            iam.delete_user_policy(UserName=name, PolicyName=POLICY_NAME)
        else:
            iam.delete_role_policy(RoleName=name, PolicyName=POLICY_NAME)
    except Exception as exc:
        fail("policy_delete_" + classify(exc))


def clients():
    import boto3

    session = boto3.Session(region_name=os.environ.get("AWS_REGION", "ap-northeast-2"))
    credentials = session.get_credentials()
    if credentials is None:
        fail("runtime_credentials_missing")
    sts = session.client("sts")
    iam = session.client("iam")
    try:
        arn = str(sts.get_caller_identity().get("Arn") or "")
    except Exception as exc:
        fail("sts_" + classify(exc))
    kind, name = principal_target(arn)
    return iam, kind, name


def validate_inputs(confirmation: str) -> None:
    if confirmation != CONFIRMATION:
        fail("confirmation_mismatch")
    if str(os.environ.get("AWS_S3_BUCKET") or "").strip() != BUCKET:
        fail("bucket_mismatch")


def apply(marker: Path, confirmation: str) -> None:
    validate_inputs(confirmation)
    iam, kind, name = clients()
    expected = policy_document()
    current = get_policy(iam, kind, name)
    if current is not None:
        if canonical(current) != canonical(expected):
            fail("policy_name_collision")
        print("qgis_plugin_s3_access=already_present")
        return

    put_policy(iam, kind, name, expected)
    verified = get_policy(iam, kind, name)
    if verified is None or canonical(verified) != canonical(expected):
        try:
            delete_policy(iam, kind, name)
        except SystemExit:
            fail("policy_verification_failed_rollback_failed")
        print("qgis_plugin_s3_access_rollback=ok")
        fail("policy_verification_failed")
    try:
        marker.write_text("created\n", encoding="utf-8")
    except OSError:
        try:
            delete_policy(iam, kind, name)
        except SystemExit:
            fail("marker_write_failed_rollback_failed")
        fail("marker_write_failed")
    print("qgis_plugin_s3_access=created")
    print("qgis_plugin_s3_access_scope=geoflow-upload/qgis-plugins/*")


def rollback(marker: Path, confirmation: str) -> None:
    validate_inputs(confirmation)
    if not marker.is_file() or marker.read_text(encoding="utf-8") != "created\n":
        print("qgis_plugin_s3_access_rollback=not_owned")
        return
    iam, kind, name = clients()
    current = get_policy(iam, kind, name)
    if current is None:
        marker.unlink(missing_ok=True)
        print("qgis_plugin_s3_access_rollback=already_absent")
        return
    if canonical(current) != canonical(policy_document()):
        fail("rollback_policy_changed")
    delete_policy(iam, kind, name)
    marker.unlink(missing_ok=True)
    print("qgis_plugin_s3_access_rollback=ok")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("apply", "rollback"))
    parser.add_argument("--marker", type=Path, required=True)
    parser.add_argument("--confirm", required=True)
    args = parser.parse_args()
    if args.operation == "apply":
        apply(args.marker, args.confirm)
    else:
        rollback(args.marker, args.confirm)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
