from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time


POLICY_NAME = "GeoFlowSurveySourceDelete20261005"
STATIC_NAMES = (
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
    "AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_SHARED_CREDENTIALS_FILE",
    "AWS_CONFIG_FILE",
)
KEY_RE = re.compile(r"^tenants/[^/]+/gis/[^/]+/survey-sources/[^/]+/[^/]+$")


def fail(code: str) -> int:
    print(f"survey_source_delete_policy_blocker={code}")
    print("survey_source_delete_policy_complete=no")
    return 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo")
    parser.add_argument("--cleanup-key", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        return fail("explicit_apply_required")
    if not KEY_RE.fullmatch(args.cleanup_key):
        return fail("cleanup_key_outside_survey_source_scope")

    sys.path.insert(0, args.repo)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geoflow_project.settings")
    import django
    django.setup()
    import boto3
    from botocore.exceptions import ClientError

    region = str(os.environ.get("AWS_REGION") or "ap-northeast-2").strip()
    bucket = str(os.environ.get("AWS_S3_BUCKET") or "").strip()
    access_key = str(os.environ.get("AWS_ACCESS_KEY_ID") or "").strip()
    secret_key = str(os.environ.get("AWS_SECRET_ACCESS_KEY") or "").strip()
    session_token = str(os.environ.get("AWS_SESSION_TOKEN") or "").strip()
    if not bucket:
        return fail("s3_bucket_not_configured")
    if not access_key or not secret_key:
        return fail("static_fallback_unavailable")

    admin_session = boto3.Session(
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        aws_session_token=session_token or None,
        region_name=region,
    )
    for name in STATIC_NAMES:
        os.environ.pop(name, None)
    os.environ.pop("AWS_EC2_METADATA_DISABLED", None)
    role_session = boto3.Session(region_name=region)
    credentials = role_session.get_credentials()
    if str(getattr(credentials, "method", "") or "") not in {"iam-role", "container-role"}:
        return fail("credential_source_not_role")
    arn = str(role_session.client("sts").get_caller_identity().get("Arn") or "")
    marker = ":assumed-role/"
    if marker not in arn:
        return fail("principal_not_assumed_role")
    role_name = arn.split(marker, 1)[1].split("/", 1)[0]
    if not role_name:
        return fail("role_name_unavailable")

    object_arn = f"arn:aws:s3:::{bucket}/tenants/*/gis/*/survey-sources/*"
    policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "DeleteSurveySourceObjectsOnly",
            "Effect": "Allow",
            "Action": ["s3:DeleteObject"],
            "Resource": [object_arn],
        }],
    }
    admin_session.client("iam").put_role_policy(
        RoleName=role_name,
        PolicyName=POLICY_NAME,
        PolicyDocument=json.dumps(policy, separators=(",", ":")),
    )
    print("survey_source_delete_policy_put=ok")
    print("survey_source_delete_policy_scope=tenants/*/gis/*/survey-sources/*")

    admin_s3 = admin_session.client("s3", region_name=region)
    existed = True
    try:
        admin_s3.head_object(Bucket=bucket, Key=args.cleanup_key)
    except ClientError as exc:
        code = str((exc.response.get("Error") or {}).get("Code") or "")
        if code in {"404", "NoSuchKey", "NotFound"}:
            existed = False
        else:
            raise
    if existed:
        role_s3 = role_session.client("s3", region_name=region)
        last_error = None
        for delay in (0, 2, 4, 8, 16):
            if delay:
                time.sleep(delay)
            try:
                role_s3.delete_object(Bucket=bucket, Key=args.cleanup_key)
                last_error = None
                break
            except ClientError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error

    try:
        admin_s3.head_object(Bucket=bucket, Key=args.cleanup_key)
    except ClientError as exc:
        code = str((exc.response.get("Error") or {}).get("Code") or "")
        if code not in {"404", "NoSuchKey", "NotFound"}:
            raise
    else:
        return fail("cleanup_object_still_exists")
    print("survey_source_orphan_found=" + ("yes" if existed else "no"))
    print("survey_source_orphan_cleanup=yes")
    print("survey_source_delete_policy_complete=yes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
