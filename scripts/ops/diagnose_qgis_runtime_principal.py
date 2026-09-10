#!/usr/bin/env python3
from __future__ import annotations

import os


KNOWN_USERS = {
    "geoflow-webgis-s3-user": "geoflow-webgis-s3-user",
    "webgis-admin": "webgis-admin",
}
SAFE_CREDENTIAL_METHODS = {
    "env",
    "iam-role",
    "container-role",
    "shared-credentials-file",
    "config-file",
}


def fail(reason: str) -> None:
    raise SystemExit(f"qgis_runtime_principal_blocker={reason}")


def principal_label(arn: str) -> str:
    marker = ":user/"
    if marker in arn:
        username = arn.split(marker, 1)[1].rsplit("/", 1)[-1]
        return KNOWN_USERS.get(username, "other-user")
    if ":assumed-role/" in arn:
        return "assumed-role"
    return "other"


def credential_method_label(method: str) -> str:
    value = str(method or "").strip()
    return value if value in SAFE_CREDENTIAL_METHODS else "other"


def main() -> int:
    import boto3
    import django
    from botocore.exceptions import ClientError, NoCredentialsError

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geoflow_project.settings")
    django.setup()
    session = boto3.Session(region_name=os.environ.get("AWS_REGION", "ap-northeast-2"))
    credentials = session.get_credentials()
    if credentials is None:
        fail("credentials_missing")
    try:
        identity = session.client("sts").get_caller_identity()
    except NoCredentialsError:
        fail("credentials_missing")
    except ClientError:
        fail("sts_access_failed")
    except Exception:
        fail("sts_unavailable")

    label = principal_label(str(identity.get("Arn") or ""))
    print("qgis_runtime_credential_method=" + credential_method_label(credentials.method))
    print("qgis_runtime_principal=" + label)
    print("RESULT qgis_runtime_principal_diagnostic=SUCCESS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
