from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Protocol

from control.services.tenant_provisioning_contract import TenantProvisioningPlan


_PLAN_BINDING_VERSION = 1
_EXECUTION_TARGET_BINDING_VERSION = 1


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
    plan_binding: str
    execution_target_binding: str = ""
    execution_available: bool = False

    @property
    def ready(self) -> bool:
        return bool(self.checks) and all(check.ready for check in self.checks)


def _plan_binding_payload(
    plan: TenantProvisioningPlan,
    *,
    version: int,
    include_execution_available: bool,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "version": version,
        "group_id": plan.group_id,
        "group_code": plan.group_code,
        "db_alias": plan.db_alias,
        "db_name": plan.db_name,
        "db_user": plan.db_user,
        "db_host": plan.db_host,
        "db_port": int(plan.db_port),
        "secret_id": plan.secret_id,
        "secret_reference": plan.secret_reference,
        "provisioning_enabled": bool(plan.provisioning_enabled),
        "provisioner_ready": bool(plan.provisioner_ready),
        "secret_reference_runtime_required": bool(
            plan.secret_reference_runtime_required
        ),
        "runtime_secret_grant_required": bool(plan.runtime_secret_grant_required),
    }
    if include_execution_available:
        payload["execution_available"] = bool(plan.execution_available)
    return payload


def _digest_binding(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def tenant_provisioning_plan_binding(plan: TenantProvisioningPlan) -> str:
    """Return a non-reversible binding for every execution-relevant plan field.

    This strict binding includes ``execution_available``. It therefore continues
    to prove that a readiness result belongs to one exact immutable plan and must
    not match after any plan field changes, including a later execution-state
    transition.
    """

    return _digest_binding(
        _plan_binding_payload(
            plan,
            version=_PLAN_BINDING_VERSION,
            include_execution_available=True,
        )
    )


def tenant_provisioning_execution_target_binding(
    plan: TenantProvisioningPlan,
) -> str:
    """Bind readiness to the exact resource target of a future execution plan.

    Read-only readiness is deliberately collected while execution is disabled.
    A future dedicated executor will need to turn only ``execution_available``
    on after a separate reviewed gate. This second binding excludes exactly that
    one switch while retaining tenant identity, database target, secret reference,
    and every execution prerequisite. It cannot itself enable execution.
    """

    return _digest_binding(
        _plan_binding_payload(
            plan,
            version=_EXECUTION_TARGET_BINDING_VERSION,
            include_execution_available=False,
        )
    )


def readiness_matches_plan(
    readiness: TenantProvisioningBackendReadiness,
    plan: TenantProvisioningPlan,
) -> bool:
    """Verify that readiness belongs to the exact supplied immutable plan."""

    expected = tenant_provisioning_plan_binding(plan)
    return bool(readiness.plan_binding) and hmac.compare_digest(
        readiness.plan_binding,
        expected,
    )


def readiness_allows_execution_candidate(
    readiness: TenantProvisioningBackendReadiness,
    plan: TenantProvisioningPlan,
) -> bool:
    """Check a narrow future disabled->enabled execution transition.

    Passing read-only readiness must itself never enable execution. This helper is
    only an attestation check for a later dedicated executor: readiness must have
    passed while disabled, the supplied candidate must explicitly be executable,
    and every execution-relevant field except that single switch must still match.
    No backend or provider operation is performed here.
    """

    if not readiness.ready:
        return False
    if readiness.execution_available:
        return False
    if not plan.execution_available:
        return False
    expected = tenant_provisioning_execution_target_binding(plan)
    return bool(readiness.execution_target_binding) and hmac.compare_digest(
        readiness.execution_target_binding,
        expected,
    )


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

    plan_binding = tenant_provisioning_plan_binding(plan)
    execution_target_binding = tenant_provisioning_execution_target_binding(plan)
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
        return TenantProvisioningBackendReadiness(
            checks=static_checks,
            plan_binding=plan_binding,
            execution_target_binding=execution_target_binding,
        )

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
    return TenantProvisioningBackendReadiness(
        checks=static_checks + live_checks,
        plan_binding=plan_binding,
        execution_target_binding=execution_target_binding,
    )
