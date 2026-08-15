from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from control.services.tenant_provisioning_contract import TenantProvisioningPlan


class TenantProvisioningBackendReadinessError(RuntimeError):
    """Fail-closed readiness error containing only a non-secret reason code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class ReadOnlyTenantProvisioningProbe(Protocol):
    """Read-only boundary for evaluating a future production-capable backend.

    Implementations may inspect metadata and connectivity, but must never create,
    update, grant, publish, migrate, rotate, or delete anything. Methods return
    booleans only so secret values, credentials, account identifiers, ARNs, and
    database metadata cannot leak through this contract.
    """

    read_only: bool

    def database_target_safe(self, plan: TenantProvisioningPlan) -> bool: ...

    def secret_target_safe(self, plan: TenantProvisioningPlan) -> bool: ...

    def runtime_exact_secret_scope_ready(self, plan: TenantProvisioningPlan) -> bool: ...

    def publication_target_still_available(self, plan: TenantProvisioningPlan) -> bool: ...


@dataclass(frozen=True)
class TenantProvisioningBackendReadinessCheck:
    code: str
    ready: bool


@dataclass(frozen=True)
class TenantProvisioningBackendReadiness:
    checks: tuple[TenantProvisioningBackendReadinessCheck, ...]
    execution_available: bool = False

    @property
    def ready(self) -> bool:
        return bool(self.checks) and all(check.ready for check in self.checks)


def _probe_check(
    *,
    code: str,
    probe_call,
) -> TenantProvisioningBackendReadinessCheck:
    try:
        ready = bool(probe_call())
    except Exception:
        ready = False
    return TenantProvisioningBackendReadinessCheck(code=code, ready=ready)


def inspect_tenant_provisioning_backend_readiness(
    plan: TenantProvisioningPlan,
    probe: ReadOnlyTenantProvisioningProbe,
) -> TenantProvisioningBackendReadiness:
    """Evaluate production-backend prerequisites without enabling execution.

    This stage deliberately keeps ``execution_available`` false. It exists to
    make the future production adapter prove its read-only safety boundaries and
    re-check stale-plan/race-sensitive targets before any mutation path is added.
    Probe failures are reduced to boolean checks; exception details are never
    propagated because they may contain connection or cloud metadata.
    """

    if bool(getattr(probe, "read_only", False)) is not True:
        raise TenantProvisioningBackendReadinessError("read_only_probe_required")

    static_checks = (
        TenantProvisioningBackendReadinessCheck(
            code="execution_contract_still_disabled",
            ready=not plan.execution_available,
        ),
        TenantProvisioningBackendReadinessCheck(
            code="execution_prerequisites_ready",
            ready=plan.execution_prerequisites_ready,
        ),
        TenantProvisioningBackendReadinessCheck(
            code="runtime_exact_secret_grant_contract_present",
            ready=plan.runtime_secret_grant_required,
        ),
    )

    # Do not inspect live infrastructure when the immutable plan is already
    # ineligible. This keeps malformed/stale plans from causing unnecessary
    # production reads and ensures readiness can never be used as an execution
    # switch.
    if not all(check.ready for check in static_checks):
        return TenantProvisioningBackendReadiness(checks=static_checks)

    live_checks = (
        _probe_check(
            code="database_target_safe",
            probe_call=lambda: probe.database_target_safe(plan),
        ),
        _probe_check(
            code="secret_target_safe",
            probe_call=lambda: probe.secret_target_safe(plan),
        ),
        _probe_check(
            code="runtime_exact_secret_scope_ready",
            probe_call=lambda: probe.runtime_exact_secret_scope_ready(plan),
        ),
        _probe_check(
            code="publication_target_still_available",
            probe_call=lambda: probe.publication_target_still_available(plan),
        ),
    )
    return TenantProvisioningBackendReadiness(checks=static_checks + live_checks)
