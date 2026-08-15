from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol

from django.conf import settings

from control.services.tenant_provisioning_backend_readiness import (
    TenantProvisioningBackendReadiness,
    readiness_allows_execution_candidate,
)
from control.services.tenant_provisioning_contract import TenantProvisioningPlan


PROVISIONING_CONFIRMATION = "NEW_TENANT_PROVISIONING"


class TenantProvisioningOrchestratorError(RuntimeError):
    """Fail-closed orchestration error with a non-secret reason code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ProvisioningAttemptResources:
    role_created: bool = False
    database_created: bool = False
    secret_created: bool = False
    runtime_grant_created: bool = False


@dataclass(frozen=True)
class TenantProvisioningResult:
    completed: bool
    config_published: bool


class TenantProvisioningBackend(Protocol):
    """Mutation interface supplied only by a dedicated provisioning executor.

    Implementations own all secret material internally. The orchestrator never
    receives or logs database passwords, secret values, AWS account identifiers,
    or credential material.
    """

    def lock(self, plan: TenantProvisioningPlan) -> AbstractContextManager[None]: ...

    def ensure_database_role(self, plan: TenantProvisioningPlan) -> bool: ...

    def ensure_database(self, plan: TenantProvisioningPlan) -> bool: ...

    def enable_postgis(self, plan: TenantProvisioningPlan) -> None: ...

    def apply_tenant_schema(self, plan: TenantProvisioningPlan) -> None: ...

    def ensure_external_secret(self, plan: TenantProvisioningPlan) -> bool: ...

    def grant_runtime_exact_secret_read(self, plan: TenantProvisioningPlan) -> bool: ...

    def verify_runtime_exact_secret_grant(self, plan: TenantProvisioningPlan) -> None: ...

    def verify_runtime_resolution_and_connectivity(
        self,
        plan: TenantProvisioningPlan,
    ) -> None: ...

    def publish_group_db_config(self, plan: TenantProvisioningPlan) -> None: ...

    def group_db_config_matches_plan(self, plan: TenantProvisioningPlan) -> bool: ...

    def remove_runtime_secret_grant(self, plan: TenantProvisioningPlan) -> None: ...

    def delete_external_secret(self, plan: TenantProvisioningPlan) -> None: ...

    def drop_database(self, plan: TenantProvisioningPlan) -> None: ...

    def drop_database_role(self, plan: TenantProvisioningPlan) -> None: ...


def _validate_execution(plan: TenantProvisioningPlan, confirmation: object) -> None:
    if str(confirmation or "").strip() != PROVISIONING_CONFIRMATION:
        raise TenantProvisioningOrchestratorError("confirmation_mismatch")
    if not plan.execution_available:
        raise TenantProvisioningOrchestratorError("execution_not_available")
    if not plan.execution_prerequisites_ready:
        raise TenantProvisioningOrchestratorError("execution_prerequisites_not_ready")
    if not plan.runtime_secret_grant_required:
        raise TenantProvisioningOrchestratorError("runtime_secret_grant_contract_missing")

    # Re-check the live execution settings rather than trusting a previously built
    # plan. A stale plan cannot turn provisioning on after an operator disables it.
    if not bool(getattr(settings, "ENABLE_TENANT_PROVISIONING", False)):
        raise TenantProvisioningOrchestratorError("runtime_feature_disabled")
    if not bool(getattr(settings, "PROVISIONING_READY", False)):
        raise TenantProvisioningOrchestratorError("runtime_provisioner_not_ready")
    if not bool(getattr(settings, "TENANT_DB_REQUIRE_SECRET_REFERENCES", False)):
        raise TenantProvisioningOrchestratorError(
            "runtime_secret_reference_mode_required"
        )
    # The public Django runtime deliberately has no executor-mode setting. Even if
    # its feature flag is accidentally enabled, orchestration must still fail
    # before the backend lock or any mutation method can run. A future dedicated
    # provisioning command/executor must opt into this setting explicitly.
    if not bool(getattr(settings, "TENANT_PROVISIONING_EXECUTOR_MODE", False)):
        raise TenantProvisioningOrchestratorError("dedicated_executor_mode_required")


def _validate_readiness_attestation(
    plan: TenantProvisioningPlan,
    readiness: TenantProvisioningBackendReadiness | None,
) -> None:
    """Require a matching read-only attestation before the backend lock is entered."""

    if readiness is None:
        raise TenantProvisioningOrchestratorError("readiness_attestation_required")
    if not readiness_allows_execution_candidate(readiness, plan):
        raise TenantProvisioningOrchestratorError("readiness_attestation_mismatch")


def _rollback_attempt(
    backend: TenantProvisioningBackend,
    plan: TenantProvisioningPlan,
    resources: ProvisioningAttemptResources,
) -> None:
    """Best-effort compensation limited to resources created by this attempt."""

    rollback_failures = []
    actions = (
        (
            resources.runtime_grant_created,
            "runtime_grant",
            backend.remove_runtime_secret_grant,
        ),
        (resources.secret_created, "external_secret", backend.delete_external_secret),
        (resources.database_created, "database", backend.drop_database),
        (resources.role_created, "database_role", backend.drop_database_role),
    )
    for should_run, label, action in actions:
        if not should_run:
            continue
        try:
            action(plan)
        except Exception:
            rollback_failures.append(label)

    if rollback_failures:
        raise TenantProvisioningOrchestratorError("rollback_incomplete")


def provision_new_tenant(
    plan: TenantProvisioningPlan,
    backend: TenantProvisioningBackend,
    *,
    confirmation: object,
    readiness: TenantProvisioningBackendReadiness | None = None,
) -> TenantProvisioningResult:
    """Execute the reviewed new-tenant sequence through an injected backend.

    The GroupDBConfig publication is deliberately the final mutating operation.
    If an operation before publication fails, compensation only removes resources
    that the current attempt reports as newly created. Pre-existing/reconciled
    resources are never deleted by this orchestrator.

    A read-only readiness attestation is mandatory before the backend lock or any
    mutation method can be reached. The attestation must have been collected while
    execution was disabled, contain the complete reviewed check set, and remain
    bound to the exact future execution target. A missing, stale, incomplete, or
    already-executable attestation fails closed before backend access.

    The runtime secret grant has its own mandatory post-grant verification gate.
    Backends must read the resulting grant through their read-only verification
    boundary and prove it is exact before runtime credential resolution or tenant
    connectivity may be attempted. A grant that cannot be verified never reaches
    GroupDBConfig publication.

    Publication has one additional fail-closed rule: if the publish call raises,
    the backend must perform a read-only exact-plan reconciliation before any
    destructive compensation is allowed. A confirmed commit is treated as
    success; a confirmed non-commit may be rolled back; an unknown publication
    outcome is never rolled back automatically because that could delete resources
    referenced by an already-committed GroupDBConfig.

    Compensation runs while the backend's per-group provisioning lock is still
    held. Concrete DB backends can therefore safely require that same lock for
    marker-guarded drop operations, and a failed attempt cannot race a second
    attempt between failure and cleanup.
    """

    _validate_execution(plan, confirmation)
    _validate_readiness_attestation(plan, readiness)
    resources = ProvisioningAttemptResources()
    published = False
    publication_outcome_known = True

    try:
        with backend.lock(plan):
            try:
                role_created = bool(backend.ensure_database_role(plan))
                resources = ProvisioningAttemptResources(role_created=role_created)

                database_created = bool(backend.ensure_database(plan))
                resources = ProvisioningAttemptResources(
                    role_created=resources.role_created,
                    database_created=database_created,
                )

                backend.enable_postgis(plan)
                backend.apply_tenant_schema(plan)

                secret_created = bool(backend.ensure_external_secret(plan))
                resources = ProvisioningAttemptResources(
                    role_created=resources.role_created,
                    database_created=resources.database_created,
                    secret_created=secret_created,
                )

                runtime_grant_created = bool(
                    backend.grant_runtime_exact_secret_read(plan)
                )
                resources = ProvisioningAttemptResources(
                    role_created=resources.role_created,
                    database_created=resources.database_created,
                    secret_created=resources.secret_created,
                    runtime_grant_created=runtime_grant_created,
                )

                backend.verify_runtime_exact_secret_grant(plan)
                backend.verify_runtime_resolution_and_connectivity(plan)

                # Central metadata is the final mutation. If the call reports an
                # error after the DB commit became durable, reconcile read-only
                # before deciding whether rollback is safe.
                try:
                    backend.publish_group_db_config(plan)
                    published = True
                except Exception as publish_exc:
                    try:
                        published = bool(backend.group_db_config_matches_plan(plan))
                    except Exception as reconcile_exc:
                        publication_outcome_known = False
                        raise TenantProvisioningOrchestratorError(
                            "publication_outcome_unknown"
                        ) from reconcile_exc
                    if not published:
                        raise publish_exc
            except TenantProvisioningOrchestratorError:
                if not published and publication_outcome_known:
                    _rollback_attempt(backend, plan, resources)
                raise
            except Exception as exc:
                if not published and publication_outcome_known:
                    try:
                        _rollback_attempt(backend, plan, resources)
                    except TenantProvisioningOrchestratorError as rollback_exc:
                        raise rollback_exc from exc
                raise TenantProvisioningOrchestratorError(
                    "provisioning_step_failed"
                ) from exc
    except TenantProvisioningOrchestratorError:
        raise
    except Exception as exc:
        # Lock acquisition/release failures occur outside the inner step handler.
        # Before publication there are no owned resources if acquisition failed;
        # after publication the contract forbids compensating a published tenant.
        raise TenantProvisioningOrchestratorError("provisioning_step_failed") from exc

    return TenantProvisioningResult(completed=True, config_published=True)
