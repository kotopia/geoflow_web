from __future__ import annotations

import os
import sys
import uuid


repo = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, repo)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geoflow_project.settings")

import django

django.setup()

from control.services.disposable_postgres_tenant_backend import (  # noqa: E402
    DisposablePostgresConfig,
    DisposablePostgresTenantBackend,
)
from control.services.tenant_provisioning_contract import (  # noqa: E402
    TenantProvisioningSnapshot,
    build_tenant_provisioning_plan,
)


def required(name: str) -> str:
    value = str(os.environ.get(name) or "").strip()
    if not value:
        raise RuntimeError(f"missing_{name.lower()}")
    return value


def main() -> int:
    group_id = str(uuid.uuid4())
    snapshot = TenantProvisioningSnapshot(
        group_id=group_id,
        group_code="ci-disposable-tenant",
        group_status="active",
        existing_config_present=False,
        identifier_conflict=False,
    )
    plan = build_tenant_provisioning_plan(
        snapshot,
        db_host=required("CI_PROVISIONER_DB_HOST"),
        db_port=required("CI_PROVISIONER_DB_PORT"),
        provisioning_enabled=True,
        provisioner_ready=True,
        secret_reference_runtime_required=True,
    )
    config = DisposablePostgresConfig(
        host=required("CI_PROVISIONER_DB_HOST"),
        port=int(required("CI_PROVISIONER_DB_PORT")),
        admin_database=required("CI_PROVISIONER_ADMIN_DATABASE"),
        admin_user=required("CI_PROVISIONER_DB_USER"),
        admin_password=required("CI_PROVISIONER_DB_PASSWORD"),
        sslmode="disable",
    )
    backend = DisposablePostgresTenantBackend(config)

    role_created = False
    database_created = False
    try:
        with backend.lock(plan):
            role_created = backend.ensure_database_role(plan)
            database_created = backend.ensure_database(plan)
            backend.enable_postgis(plan)
            backend.apply_tenant_schema(plan)
            backend.verify_database_schema(plan)
            print("tenant_provisioning_ci_role_created=yes")
            print("tenant_provisioning_ci_database_created=yes")
            print("tenant_provisioning_ci_postgis_ready=yes")
            print("tenant_provisioning_ci_schema_migrated=yes")
            print("tenant_provisioning_ci_app_connectivity=yes")
            print("tenant_provisioning_ci_external_secret=not_performed")
            print("tenant_provisioning_ci_iam_change=not_performed")
            print("tenant_provisioning_ci_central_publish=not_performed")
            if database_created:
                backend.drop_database(plan)
                database_created = False
            if role_created:
                backend.drop_database_role(plan)
                role_created = False
            print("tenant_provisioning_ci_cleanup=yes")
    finally:
        if database_created or role_created:
            # Reacquire the same per-group lock for guarded cleanup after failures.
            try:
                with backend.lock(plan):
                    if database_created:
                        backend.drop_database(plan)
                    if role_created:
                        backend.drop_database_role(plan)
            except Exception:
                print("tenant_provisioning_ci_cleanup=failed")
                return 3

    print("tenant_provisioning_ci_complete=yes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
