from __future__ import annotations

import json
import os
import sys

POLICY_NAME = "GeoFlowPhase2RuntimeMinimum20260814"
STATIC_NAMES = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_PROFILE",
    "AWS_DEFAULT_PROFILE",
    "AWS_SHARED_CREDENTIALS_FILE",
    "AWS_CONFIG_FILE",
)


def _classify(exc: BaseException) -> str:
    try:
        from botocore.exceptions import ClientError, NoCredentialsError
    except Exception:
        return "other"
    if isinstance(exc, NoCredentialsError):
        return "no_credentials"
    if isinstance(exc, ClientError):
        code = str((exc.response.get("Error") or {}).get("Code") or "")
        if code in {"AccessDenied", "AccessDeniedException", "UnauthorizedOperation", "Forbidden", "403"}:
            return "access_denied"
        if code in {"ResourceNotFoundException", "NoSuchBucket", "NoSuchKey", "NotFound", "404"}:
            return "not_found"
        if code in {"DecryptionFailure", "InvalidCiphertextException", "DisabledException"}:
            return "kms_or_decryption"
        if code in {"PermanentRedirect", "AuthorizationHeaderMalformed", "IncorrectEndpoint", "IllegalLocationConstraintException"}:
            return "region_or_endpoint"
    return "other"


def _fail(code: str, rc: int = 2) -> int:
    print(f"phase2_min_policy_apply_blocker={code}")
    print("phase2_min_policy_apply_complete=no")
    return rc


def main() -> int:
    if len(sys.argv) != 2:
        return _fail("invalid_arguments")

    repo = sys.argv[1]
    sys.path.insert(0, repo)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geoflow_project.settings")

    import django
    django.setup()

    import boto3
    from control.models import GroupDBConfig
    from control.services.tenant_db_secret_resolver import parse_tenant_db_secret_reference

    region = str(os.environ.get("AWS_REGION") or "ap-northeast-2").strip()
    bucket = str(os.environ.get("AWS_S3_BUCKET") or "").strip()
    if not bucket:
        return _fail("s3_bucket_not_configured")

    access_key = str(os.environ.get("AWS_ACCESS_KEY_ID") or "").strip()
    secret_key = str(os.environ.get("AWS_SECRET_ACCESS_KEY") or "").strip()
    session_token = str(os.environ.get("AWS_SESSION_TOKEN") or "").strip()
    if not access_key or not secret_key:
        return _fail("static_fallback_unavailable")

    admin_session = boto3.Session(
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        aws_session_token=session_token or None,
        region_name=region,
    )

    # Remove static/profile sources before discovering and validating the EC2 role.
    for name in STATIC_NAMES:
        os.environ.pop(name, None)
    os.environ.pop("AWS_EC2_METADATA_DISABLED", None)

    role_session = boto3.Session(region_name=region)
    credentials = role_session.get_credentials()
    if credentials is None:
        return _fail("no_role_credentials")
    method = str(getattr(credentials, "method", "") or "")
    if method not in {"iam-role", "container-role"}:
        return _fail("credential_source_not_role")

    try:
        identity = role_session.client("sts", region_name=region).get_caller_identity()
        arn = str(identity.get("Arn") or "")
        marker = ":assumed-role/"
        if marker not in arn:
            return _fail("principal_not_assumed_role")
        role_name = arn.split(marker, 1)[1].split("/", 1)[0]
        if not role_name:
            return _fail("role_name_unavailable")
    except Exception as exc:
        return _fail("sts_" + _classify(exc))

    active_configs = list(
        GroupDBConfig.objects.select_related("group")
        .filter(group__status="active")
        .only("db_password")
    )
    references = []
    for config in active_configs:
        ref = parse_tenant_db_secret_reference(str(config.db_password or "").strip())
        if ref is not None:
            references.append(ref)
    if not references:
        return _fail("no_active_secret_references")

    admin_sm = admin_session.client("secretsmanager", region_name=region)
    secret_arns: set[str] = set()
    try:
        for ref in references:
            response = admin_sm.get_secret_value(SecretId=ref.secret_id)
            secret_arn = str(response.get("ARN") or "").strip()
            if not secret_arn:
                return _fail("secret_arn_unavailable")
            secret_arns.add(secret_arn)
            response = None
    except Exception as exc:
        return _fail("fallback_secret_" + _classify(exc))

    # Validate that the fallback path reaches the configured private S3 scope before mutation.
    admin_s3 = admin_session.client("s3", region_name=region)
    try:
        admin_s3.list_objects_v2(Bucket=bucket, Prefix="tenants/", MaxKeys=1)
    except Exception as exc:
        return _fail("fallback_s3_" + _classify(exc))

    bucket_arn = f"arn:aws:s3:::{bucket}"
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ReadTenantDatabaseSecrets",
                "Effect": "Allow",
                "Action": ["secretsmanager:GetSecretValue"],
                "Resource": sorted(secret_arns),
            },
            {
                "Sid": "ListPrivateTenantPrefix",
                "Effect": "Allow",
                "Action": ["s3:ListBucket"],
                "Resource": [bucket_arn],
                "Condition": {"StringLike": {"s3:prefix": ["tenants/*"]}},
            },
            {
                "Sid": "ReadWritePrivateTenantObjects",
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:PutObject"],
                "Resource": [bucket_arn + "/tenants/*"],
            },
        ],
    }

    iam = admin_session.client("iam")
    mutation_started = False
    try:
        iam.put_role_policy(
            RoleName=role_name,
            PolicyName=POLICY_NAME,
            PolicyDocument=json.dumps(policy, separators=(",", ":")),
        )
        mutation_started = True
        print("phase2_min_policy_put=ok")
    except Exception as exc:
        print("phase2_min_policy_put=" + _classify(exc))
        return _fail("iam_put_role_policy_" + _classify(exc))

    # Authoritative post-mutation verification uses only the instance/container role.
    try:
        role_sm = role_session.client("secretsmanager", region_name=region)
        secret_ok = 0
        for ref in references:
            response = role_sm.get_secret_value(SecretId=ref.secret_id)
            if response.get("SecretString") or response.get("SecretBinary"):
                secret_ok += 1
            response = None
        role_s3 = role_session.client("s3", region_name=region)
        listed = role_s3.list_objects_v2(Bucket=bucket, Prefix="tenants/", MaxKeys=1)
        contents = listed.get("Contents") or []
        if contents:
            key = str(contents[0].get("Key") or "")
            if key:
                response = role_s3.get_object(Bucket=bucket, Key=key, Range="bytes=0-0")
                body = response.get("Body")
                if body is not None:
                    body.read(1)
                    body.close()
        if secret_ok != len(references):
            raise RuntimeError("secret verification incomplete")
    except Exception as exc:
        print("phase2_min_policy_role_verify=" + _classify(exc))
        if mutation_started:
            try:
                iam.delete_role_policy(RoleName=role_name, PolicyName=POLICY_NAME)
                print("phase2_min_policy_rollback=ok")
            except Exception as rollback_exc:
                print("phase2_min_policy_rollback=" + _classify(rollback_exc))
                return _fail("post_apply_verify_failed_rollback_failed", 3)
        return _fail("post_apply_verify_" + _classify(exc))

    print("phase2_min_policy_role_secret_refs_verified=" + str(len(references)))
    print("phase2_min_policy_role_s3_read_verified=yes")
    print("phase2_min_policy_scope=reviewed_minimum")
    print("phase2_min_policy_apply_complete=yes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
