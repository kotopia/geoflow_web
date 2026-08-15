from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from django.conf import settings
from django.db.models import Q

from control.models import Group, GroupDBConfig
from control.services.tenant_db_secret_resolver import SECRET_REFERENCE_PREFIX


_POSTGRES_IDENTIFIER_MAX = 63
_SAFE_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{1,62}$")


class TenantProvisioningContractError(RuntimeError):
    """Fail-closed provisioning preflight error with a non-secret reason code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class TenantProvisioningPlan:
    """Immutable plan for a new tenant. This class performs no mutations."""

    group_id: str
    group_code: str
    db_alias: str
    db_name: str
    db_user: str
    db_host: str
    db_port: int
    secret_id: str
    secret_reference: str
    provisioning_enabled: bool
    provisioner_ready: bool
    secret_reference_runtime_required: bool
    runtime_secret_grant_required: bool
    execution_available: bool = False

    @property
    def execution_prerequisites_ready(self) -> bool:
        return (
            self.provisioning_enabled
            and self.provisioner_ready
            and self.secret_reference_runtime_required
        )


@dataclass(frozen=True)
class TenantProvisioningSnapshot:
    group_id: str
    group_code: str
    group_status: str
    existing_config_present: bool
    identifier_conflict: bool


def _text(value) -> str:
    return str(value or "").strip()


def _enabled(value) -> bool:
    if isinstance(value, bool):
        return value
    return _text(value).lower() in {"1", "true", "yes", "y", "on"}


def _normalized_group_code(value: object) -> str:
    raw = _text(value).lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    if not normalized:
        raise TenantProvisioningContractError("group_code_not_identifier_safe")
    if not normalized[0].isalpha():
        normalized = "g_" + normalized
    return normalized


def _short_uuid(value: object) -> str:
    try:
        return uuid.UUID(_text(value)).hex[:8]
    except (ValueError, TypeError, AttributeError):
        raise TenantProvisioningContractError("group_id_invalid") from None


def _bounded_identifier(prefix: str, suffix: str) -> str:
    suffix_text = "_" + suffix
    max_prefix = _POSTGRES_IDENTIFIER_MAX - len(suffix_text)
    candidate = prefix[:max_prefix].rstrip("_") + suffix_text
    if not _SAFE_IDENTIFIER.fullmatch(candidate):
        raise TenantProvisioningContractError("generated_identifier_invalid")
    return candidate


def derive_tenant_identifiers(group_id: object, group_code: object) -> tuple[str, str, str]:
    """Generate deterministic, collision-resistant identifiers for a new tenant."""

    normalized = _normalized_group_code(group_code)
    token = _short_uuid(group_id)
    base = f"{normalized}_{token}"
    db_alias = _bounded_identifier(base, "db")
    db_name = db_alias
    db_user = _bounded_identifier(base, "app")
    return db_alias, db_name, db_user


def build_tenant_secret_reference(group_id: object) -> tuple[str, str]:
    """Return the approved Secrets Manager id/reference shape; never a secret value."""

    canonical_group_id = str(uuid.UUID(_text(group_id)))
    secret_id = f"geoflow/tenant-db/{canonical_group_id}/password"
    reference = f"{SECRET_REFERENCE_PREFIX}{secret_id}#password"
    return secret_id, reference


def build_tenant_provisioning_plan(
    snapshot: TenantProvisioningSnapshot,
    *,
    db_host: object,
    db_port: object,
    provisioning_enabled: object,
    provisioner_ready: object,
    secret_reference_runtime_required: object,
) -> TenantProvisioningPlan:
    """Build a plan only for an active group that has never been provisioned.

    Existing GroupDBConfig rows are a hard stop. Provisioning execution is
    deliberately unavailable in this contract stage so merging this code cannot
    create a database, role, secret, IAM grant, schema, or central DB config.
    """

    if _text(snapshot.group_status).lower() != "active":
        raise TenantProvisioningContractError("group_not_active")
    if snapshot.existing_config_present:
        raise TenantProvisioningContractError("existing_tenant_protected")
    if snapshot.identifier_conflict:
        raise TenantProvisioningContractError("tenant_identifier_conflict")

    db_alias, db_name, db_user = derive_tenant_identifiers(
        snapshot.group_id,
        snapshot.group_code,
    )
    secret_id, secret_reference = build_tenant_secret_reference(snapshot.group_id)

    port_text = _text(db_port)
    try:
        port = int(port_text)
    except (TypeError, ValueError):
        port = 0
    if port < 1 or port > 65535:
        port = 0

    return TenantProvisioningPlan(
        group_id=_text(snapshot.group_id),
        group_code=_text(snapshot.group_code),
        db_alias=db_alias,
        db_name=db_name,
        db_user=db_user,
        db_host=_text(db_host),
        db_port=port,
        secret_id=secret_id,
        secret_reference=secret_reference,
        provisioning_enabled=_enabled(provisioning_enabled),
        provisioner_ready=_enabled(provisioner_ready) and bool(_text(db_host)) and port > 0,
        secret_reference_runtime_required=_enabled(secret_reference_runtime_required),
        runtime_secret_grant_required=True,
        execution_available=False,
    )


def inspect_tenant_provisioning_plan(group_id: object) -> TenantProvisioningPlan:
    """Read central metadata and return a mutation-free provisioning plan."""

    central_alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")
    group = (
        Group.objects.using(central_alias)
        .filter(id=group_id)
        .only("id", "code", "status")
        .first()
    )
    if group is None:
        raise TenantProvisioningContractError("group_not_found")

    existing = GroupDBConfig.objects.using(central_alias).filter(group_id=group.id).exists()
    db_alias, db_name, db_user = derive_tenant_identifiers(group.id, group.code)
    conflict = (
        GroupDBConfig.objects.using(central_alias)
        .filter(Q(db_alias=db_alias) | Q(db_name=db_name) | Q(db_user=db_user))
        .exclude(group_id=group.id)
        .exists()
    )

    snapshot = TenantProvisioningSnapshot(
        group_id=str(group.id),
        group_code=_text(group.code),
        group_status=_text(group.status),
        existing_config_present=existing,
        identifier_conflict=conflict,
    )
    return build_tenant_provisioning_plan(
        snapshot,
        db_host=getattr(settings, "PROVISIONER_DB_HOST", ""),
        db_port=getattr(settings, "PROVISIONER_DB_PORT", ""),
        provisioning_enabled=getattr(settings, "ENABLE_TENANT_PROVISIONING", False),
        provisioner_ready=getattr(settings, "PROVISIONING_READY", False),
        secret_reference_runtime_required=getattr(
            settings,
            "TENANT_DB_REQUIRE_SECRET_REFERENCES",
            False,
        ),
    )


PROVISIONING_EXECUTION_SEQUENCE = (
    "validate_bound_read_only_readiness_attestation",
    "lock_new_group_provisioning",
    "create_database_role",
    "create_database",
    "enable_postgis",
    "open_explicit_dynamic_tenant_migration_context",
    "apply_tenant_schema",
    "create_external_secret",
    "grant_runtime_role_exact_secret_read",
    "verify_runtime_exact_secret_grant_readback",
    "verify_runtime_secret_resolution_and_db_connectivity",
    "publish_group_db_config_last",
)

PROVISIONING_ROLLBACK_SEQUENCE = (
    "remove_unpublished_runtime_secret_grant",
    "delete_unpublished_external_secret",
    "drop_new_database_only_if_created_by_attempt",
    "drop_new_database_role_only_if_created_by_attempt",
)
