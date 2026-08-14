from __future__ import annotations

import os
import sys
from collections import Counter


SAFE_ERROR_KINDS = (
    "access_denied",
    "not_found",
    "kms_or_decryption",
    "region_or_endpoint",
    "no_credentials",
    "transport",
    "resolver_validation",
    "other",
)


def classify_aws_error(exc: BaseException | None) -> str:
    """Return a bounded, identifier-safe failure category."""

    if exc is None:
        return "other"

    from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

    if isinstance(exc, NoCredentialsError):
        return "no_credentials"
    if isinstance(exc, ClientError):
        code = str((exc.response.get("Error") or {}).get("Code") or "").strip()
        if code in {
            "AccessDenied",
            "AccessDeniedException",
            "UnauthorizedOperation",
            "Forbidden",
            "AllAccessDisabled",
            "403",
        }:
            return "access_denied"
        if code in {
            "ResourceNotFoundException",
            "NoSuchBucket",
            "NoSuchKey",
            "NotFound",
            "404",
        }:
            return "not_found"
        if code in {
            "DecryptionFailure",
            "KMSInternalException",
            "InvalidCiphertextException",
            "DisabledException",
        }:
            return "kms_or_decryption"
        if code in {
            "PermanentRedirect",
            "AuthorizationHeaderMalformed",
            "IncorrectEndpoint",
            "IllegalLocationConstraintException",
        }:
            return "region_or_endpoint"
        return "other"
    if isinstance(exc, BotoCoreError):
        return "transport"
    return "other"


def classify_resolver_error(exc: BaseException) -> str:
    cause = getattr(exc, "__cause__", None)
    if cause is None:
        return "resolver_validation"
    return classify_aws_error(cause)


def s3_minimum_policy_ready(list_state: str, read_state: str) -> bool:
    """Match the reviewed minimum policy: prefix ListBucket + GetObject.

    HeadBucket is deliberately not required because the reviewed ListBucket grant
    is constrained by s3:prefix=tenants/*; HeadBucket carries no prefix and may
    therefore be denied by a correctly least-privileged policy.
    """

    return list_state == "ok" and read_state in {"ok", "not_tested_no_object"}


def inventory_role_policies(static_session, role_name: str) -> tuple[str, int | None, int | None, str]:
    """Return only bounded policy inventory metadata; never policy names/documents."""

    if static_session is None:
        return "no_static_fallback", None, None, "unknown"
    if not role_name:
        return "role_name_unavailable", None, None, "unknown"

    try:
        iam = static_session.client("iam")
        inline = iam.list_role_policies(RoleName=role_name, MaxItems=1000)
        attached = iam.list_attached_role_policies(RoleName=role_name, MaxItems=1000)
    except Exception as exc:
        return classify_aws_error(exc), None, None, "unknown"

    inline_names = inline.get("PolicyNames") or []
    attached_items = attached.get("AttachedPolicies") or []
    truncated = bool(inline.get("IsTruncated") or attached.get("IsTruncated"))
    return "ok", len(inline_names), len(attached_items), "yes" if truncated else "no"


def main() -> int:
    if len(sys.argv) != 2:
        print("phase2_role_diag_blocker=invalid_probe_arguments")
        return 2

    repo = sys.argv[1]
    sys.path.insert(0, repo)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geoflow_project.settings")

    import django

    django.setup()

    # Preserve only an in-memory reference to the existing fallback credentials
    # for a bounded IAM *read-only* policy inventory. Values are never printed,
    # written, or used for runtime readiness. The actual Secrets/S3 readiness
    # below still removes all static/profile sources and must use the EC2 role.
    fallback_access_key = str(os.environ.get("AWS_ACCESS_KEY_ID") or "").strip()
    fallback_secret_key = str(os.environ.get("AWS_SECRET_ACCESS_KEY") or "").strip()
    fallback_session_token = str(os.environ.get("AWS_SESSION_TOKEN") or "").strip()
    fallback_present = bool(fallback_access_key and fallback_secret_key)

    # settings.py may have loaded the production .env already. Remove every
    # static/profile source only in this probe process so boto3 must use the
    # instance/container role. No runtime file or service environment is changed.
    for name in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_PROFILE",
        "AWS_DEFAULT_PROFILE",
        "AWS_SHARED_CREDENTIALS_FILE",
        "AWS_CONFIG_FILE",
    ):
        os.environ.pop(name, None)
    os.environ.pop("AWS_EC2_METADATA_DISABLED", None)

    import boto3

    from control.models import GroupDBConfig
    from control.services.tenant_db_secret_resolver import (
        TenantDBCredentialError,
        is_tenant_db_secret_reference,
        resolve_tenant_db_password,
    )

    region = str(os.environ.get("AWS_REGION") or "ap-northeast-2").strip()
    static_session = None
    if fallback_present:
        static_session = boto3.Session(
            aws_access_key_id=fallback_access_key,
            aws_secret_access_key=fallback_secret_key,
            aws_session_token=fallback_session_token or None,
            region_name=region,
        )

    session = boto3.Session(region_name=region)
    credentials = session.get_credentials()
    if credentials is None:
        print("phase2_role_credentials_available=no")
        print("phase2_role_ready=no")
        print("phase2_role_diag_blocker=no_role_credentials")
        return 2

    method = str(getattr(credentials, "method", "") or "unknown")
    if method == "iam-role":
        method_class = "instance-role"
    elif method == "container-role":
        method_class = "container-role"
    else:
        method_class = "other"
    print("phase2_role_credentials_available=yes")
    print(f"phase2_role_credential_method={method_class}")

    assumed_role = "unknown"
    sts_error = "none"
    role_name = ""
    try:
        identity = session.client("sts", region_name=region).get_caller_identity()
        arn = str(identity.get("Arn") or "")
        assumed_role = "yes" if ":assumed-role/" in arn else "no"
        if assumed_role == "yes":
            role_name = arn.split(":assumed-role/", 1)[1].split("/", 1)[0]
    except Exception as exc:  # identifier-safe classification only
        sts_error = classify_aws_error(exc)
    print(f"phase2_role_principal_is_assumed_role={assumed_role}")
    print(f"phase2_role_sts_error={sts_error}")

    inventory_state, inline_count, attached_count, inventory_truncated = inventory_role_policies(
        static_session,
        role_name,
    )
    print(f"phase2_role_static_fallback_present={'yes' if fallback_present else 'no'}")
    print(f"phase2_role_policy_inventory={inventory_state}")
    print(
        "phase2_role_inline_policy_count="
        + (str(inline_count) if inline_count is not None else "unknown")
    )
    print(
        "phase2_role_attached_policy_count="
        + (str(attached_count) if attached_count is not None else "unknown")
    )
    print(f"phase2_role_policy_inventory_truncated={inventory_truncated}")
    if inventory_state == "ok" and inline_count == 0 and attached_count == 0:
        print("phase2_role_policy_inventory_blocker=no_role_policies")
    else:
        print("phase2_role_policy_inventory_blocker=none")

    # Drop the in-memory static values as soon as the bounded inventory is done.
    fallback_access_key = ""
    fallback_secret_key = ""
    fallback_session_token = ""
    static_session = None

    sm = session.client("secretsmanager", region_name=region)
    active_configs = list(
        GroupDBConfig.objects.select_related("group")
        .filter(group__status="active")
        .only("db_password")
    )
    active_refs = 0
    secret_resolve_ok = 0
    secret_failures: Counter[str] = Counter()
    for config in active_configs:
        stored = str(config.db_password or "").strip()
        if not is_tenant_db_secret_reference(stored):
            continue
        active_refs += 1
        try:
            resolved = resolve_tenant_db_password(
                stored,
                environ=os.environ,
                client=sm,
            )
            if resolved:
                secret_resolve_ok += 1
            else:
                secret_failures["resolver_validation"] += 1
        except TenantDBCredentialError as exc:
            secret_failures[classify_resolver_error(exc)] += 1

    secret_resolve_fail = sum(secret_failures.values())
    print(f"phase2_role_active_secret_refs={active_refs}")
    print(f"phase2_role_secret_resolve_ok={secret_resolve_ok}")
    print(f"phase2_role_secret_resolve_fail={secret_resolve_fail}")
    for kind in SAFE_ERROR_KINDS:
        print(f"phase2_role_secret_fail_{kind}={secret_failures[kind]}")

    bucket = str(os.environ.get("AWS_S3_BUCKET") or "").strip()
    s3_head_bucket = "not_configured"
    s3_head_error = "none"
    s3_list = "not_tested"
    s3_list_error = "none"
    s3_read = "not_tested_no_object"
    s3_read_error = "none"
    if bucket:
        s3 = session.client("s3", region_name=region)
        try:
            s3.head_bucket(Bucket=bucket)
            s3_head_bucket = "ok"
        except Exception as exc:  # HeadBucket is observational, not readiness-critical.
            s3_head_bucket = "failed"
            s3_head_error = classify_aws_error(exc)

        try:
            listed = s3.list_objects_v2(Bucket=bucket, Prefix="tenants/", MaxKeys=1)
            s3_list = "ok"
            contents = listed.get("Contents") or []
            if contents:
                key = str(contents[0].get("Key") or "")
                if key:
                    try:
                        response = s3.get_object(Bucket=bucket, Key=key, Range="bytes=0-0")
                        body = response.get("Body")
                        if body is not None:
                            body.read(1)
                            body.close()
                        s3_read = "ok"
                    except Exception as exc:
                        s3_read = "failed"
                        s3_read_error = classify_aws_error(exc)
        except Exception as exc:
            s3_list = "failed"
            s3_list_error = classify_aws_error(exc)

    print(f"phase2_role_s3_head_bucket={s3_head_bucket}")
    print(f"phase2_role_s3_head_bucket_error={s3_head_error}")
    print("phase2_role_s3_head_bucket_required=no")
    print(f"phase2_role_s3_list={s3_list}")
    print(f"phase2_role_s3_list_error={s3_list_error}")
    print(f"phase2_role_s3_read_probe={s3_read}")
    print(f"phase2_role_s3_read_error={s3_read_error}")
    print("phase2_role_s3_put_live_probe=not_performed_read_only")

    role_method_ok = method_class in {"instance-role", "container-role"}
    secrets_ok = (
        active_refs > 0
        and secret_resolve_fail == 0
        and secret_resolve_ok == active_refs
    )
    s3_readiness_ok = bool(bucket) and s3_minimum_policy_ready(s3_list, s3_read)
    ready = role_method_ok and secrets_ok and s3_readiness_ok
    print(f"phase2_role_ready={'yes' if ready else 'no'}")
    print("phase2_aws_role_readiness_diagnostic_complete=yes")
    return 0 if ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
