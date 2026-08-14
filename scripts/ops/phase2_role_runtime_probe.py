from __future__ import annotations

import os
import sys
from pathlib import Path


STATIC_OR_PROFILE_AWS_SOURCES = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_PROFILE",
    "AWS_DEFAULT_PROFILE",
    "AWS_SHARED_CREDENTIALS_FILE",
    "AWS_CONFIG_FILE",
)

TRUTHY = {"1", "true", "yes", "y", "on"}


def _fail(code: str) -> None:
    print(f"phase2_role_probe_blocker={code}")
    raise SystemExit(2)


def _role_only_guard_enabled() -> bool:
    return str(os.environ.get("AWS_REQUIRE_ROLE_CREDENTIALS") or "").strip().lower() in TRUTHY


def _drop_process_static_sources() -> None:
    for name in STATIC_OR_PROFILE_AWS_SOURCES:
        os.environ.pop(name, None)
    os.environ.pop("AWS_EC2_METADATA_DISABLED", None)


def _configure_tenant_connection(config, password: str, base_config: dict) -> dict:
    db_config = dict(base_config)
    db_config.update(
        {
            "ENGINE": "django.contrib.gis.db.backends.postgis",
            "NAME": config.db_name,
            "USER": config.db_user,
            "PASSWORD": password,
            "HOST": config.db_host,
            "PORT": config.db_port,
            "OPTIONS": dict(base_config.get("OPTIONS", {})),
            "ATOMIC_REQUESTS": False,
            "CONN_MAX_AGE": 0,
            "CONN_HEALTH_CHECKS": False,
            "AUTOCOMMIT": True,
        }
    )
    return db_config


def main() -> int:
    if len(sys.argv) != 3:
        _fail("invalid_arguments")

    repo = Path(sys.argv[1]).resolve()
    mode = sys.argv[2]
    if mode not in {"precutover", "postcutover"}:
        _fail("invalid_mode")
    if not (repo / "manage.py").is_file():
        _fail("runtime_repo_invalid")

    sys.path.insert(0, str(repo))
    os.chdir(repo)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geoflow_project.settings")

    import django

    django.setup()

    if mode == "postcutover":
        configured_sources = sum(
            bool(str(os.environ.get(name) or "").strip())
            for name in STATIC_OR_PROFILE_AWS_SOURCES
        )
        print(f"phase2_role_probe_configured_static_sources={configured_sources}")
        print(
            "phase2_role_probe_guard_enabled="
            + ("yes" if _role_only_guard_enabled() else "no")
        )
        if configured_sources:
            _fail("static_or_profile_source_present")
        if not _role_only_guard_enabled():
            _fail("role_only_guard_disabled")

    # In precutover mode, settings may have loaded legacy AWS variables from the
    # production configuration. Remove them only inside this probe process so
    # boto3 must prove that an instance/container role is independently usable.
    _drop_process_static_sources()

    import boto3
    from django.conf import settings
    from django.db import connections

    from control.models import GroupDBConfig
    from control.services.tenant_db_secret_resolver import (
        TenantDBCredentialError,
        is_tenant_db_secret_reference,
        resolve_tenant_db_password,
    )

    region = str(os.environ.get("AWS_REGION") or "ap-northeast-2").strip()
    session = boto3.Session(region_name=region)
    credentials = session.get_credentials()
    if credentials is None:
        print("phase2_role_probe_role_credentials=no")
        _fail("no_role_credentials")

    method = str(getattr(credentials, "method", "") or "")
    role_method = method in {"iam-role", "container-role"}
    print("phase2_role_probe_role_credentials=" + ("yes" if role_method else "no"))
    if not role_method:
        _fail("credential_source_not_role")

    configs = list(
        GroupDBConfig.objects.filter(group__status="active").only(
            "db_alias",
            "db_name",
            "db_host",
            "db_port",
            "db_user",
            "db_password",
        )
    )
    print(f"phase2_role_probe_active_tenant_configs={len(configs)}")
    if not configs:
        _fail("no_active_tenant_configs")

    sm = session.client("secretsmanager", region_name=region)
    central_alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")
    base_config = dict(connections.settings.get(central_alias) or {})
    if not base_config:
        _fail("central_database_config_missing")

    secret_ok = 0
    db_ok = 0
    non_reference = 0
    secret_fail = 0
    db_fail = 0

    for index, config in enumerate(configs):
        stored = str(config.db_password or "").strip()
        if not is_tenant_db_secret_reference(stored):
            non_reference += 1
            continue
        try:
            password = resolve_tenant_db_password(
                stored,
                environ=os.environ,
                client=sm,
            )
        except TenantDBCredentialError:
            secret_fail += 1
            continue
        if not password:
            secret_fail += 1
            continue
        secret_ok += 1

        alias = f"phase2_role_probe_{index}"
        db_config = _configure_tenant_connection(config, password, base_config)
        connections.settings[alias] = db_config
        if settings.DATABASES is not connections.settings:
            settings.DATABASES[alias] = db_config
        try:
            with connections[alias].cursor() as cursor:
                cursor.execute("SELECT 1")
                row = cursor.fetchone()
            if row and row[0] == 1:
                db_ok += 1
            else:
                db_fail += 1
        except Exception:
            db_fail += 1
        finally:
            try:
                connections[alias].close()
            except Exception:
                pass
            connections.settings.pop(alias, None)
            if settings.DATABASES is not connections.settings:
                settings.DATABASES.pop(alias, None)
            try:
                del connections[alias]
            except Exception:
                pass

    print(f"phase2_role_probe_secret_resolve_ok={secret_ok}")
    print(f"phase2_role_probe_tenant_db_connect_ok={db_ok}")
    print(f"phase2_role_probe_non_reference_configs={non_reference}")
    print(f"phase2_role_probe_secret_failures={secret_fail}")
    print(f"phase2_role_probe_tenant_db_failures={db_fail}")

    expected = len(configs)
    if non_reference or secret_fail or secret_ok != expected:
        _fail("tenant_secret_readiness_failed")
    if db_fail or db_ok != expected:
        _fail("tenant_database_connectivity_failed")

    bucket = str(os.environ.get("AWS_S3_BUCKET") or "").strip()
    if not bucket:
        print("phase2_role_probe_s3_configured=no")
        _fail("s3_not_configured")

    s3 = session.client("s3", region_name=region)
    try:
        # Match the reviewed least-privilege readiness contract exactly. The
        # ListBucket grant is constrained to tenants/*, so HeadBucket has no
        # prefix context and may correctly be denied even when runtime access is
        # ready. Prove the actual required read path instead: prefix list + Get.
        listed = s3.list_objects_v2(Bucket=bucket, Prefix="tenants/", MaxKeys=1)
        contents = listed.get("Contents") or []
        read_probe = "not_tested_no_object"
        if contents:
            key = str(contents[0].get("Key") or "")
            if key:
                response = s3.get_object(Bucket=bucket, Key=key, Range="bytes=0-0")
                body = response.get("Body")
                if body is not None:
                    body.read(1)
                    body.close()
                read_probe = "ok"
        print("phase2_role_probe_s3_head=not_required")
        print("phase2_role_probe_s3_list=yes")
        print(f"phase2_role_probe_s3_read={read_probe}")
    except Exception:
        print("phase2_role_probe_s3_readiness=no")
        _fail("s3_readiness_failed")

    print("phase2_role_probe_complete=yes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
