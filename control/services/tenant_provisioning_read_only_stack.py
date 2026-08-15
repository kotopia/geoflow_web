from __future__ import annotations

from control.models import GroupDBConfig
from control.services.tenant_provisioning_aws_readers import (
    AwsSecretsManagerReadOnlyCatalog,
)
from control.services.tenant_provisioning_postgres_readers import (
    PostgresReadOnlyDatabaseCatalog,
)
from control.services.tenant_provisioning_production_probe import (
    ProductionShapeReadOnlyTenantProvisioningProbe,
)
from control.services.tenant_provisioning_publication_readers import (
    DjangoGroupDBConfigReadOnlyCatalog,
)


def build_production_shape_read_only_tenant_provisioning_probe(
    *,
    postgres_connector,
    secrets_manager_client,
    runtime_secret_scope,
    central_database_alias: str,
    publication_model=GroupDBConfig,
) -> ProductionShapeReadOnlyTenantProvisioningProbe:
    """Compose the proven read-only adapters without constructing live clients.

    Every external dependency is supplied by the caller. This function creates no
    boto3 session, PostgreSQL connection factory, credentials, IAM client, or
    execution backend. The publication adapter is pinned to an explicitly chosen
    central database alias. A non-read-only dependency is rejected at composition
    time before any metadata read can occur.

    The resulting probe remains a readiness-only object. It cannot provision a
    database, create or read a secret value, change IAM, publish GroupDBConfig, run
    migrations, or enable ``TenantProvisioningPlan.execution_available``.
    """

    probe = ProductionShapeReadOnlyTenantProvisioningProbe(
        database_catalog=PostgresReadOnlyDatabaseCatalog(postgres_connector),
        secret_catalog=AwsSecretsManagerReadOnlyCatalog(secrets_manager_client),
        runtime_secret_scope=runtime_secret_scope,
        publication_catalog=DjangoGroupDBConfigReadOnlyCatalog(
            using=central_database_alias,
            model=publication_model,
        ),
    )
    if not probe.read_only:
        raise RuntimeError("read_only_dependency_required")
    return probe
