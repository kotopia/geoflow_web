from __future__ import annotations

from dataclasses import replace

from control.services.tenant_provisioning_backend_readiness import (
    ReadOnlyTenantProvisioningProbe,
    TenantProvisioningBackendReadiness,
    TenantProvisioningBackendReadinessError,
    inspect_tenant_provisioning_backend_readiness,
    readiness_allows_execution_candidate,
)
from control.services.tenant_provisioning_contract import TenantProvisioningPlan


class TenantProvisioningExecutionReadinessError(RuntimeError):
    """Fail-closed execution-readiness error with a non-secret reason code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def revalidate_tenant_provisioning_readiness(
    plan: TenantProvisioningPlan,
    readiness: TenantProvisioningBackendReadiness,
    probe: ReadOnlyTenantProvisioningProbe,
) -> TenantProvisioningBackendReadiness:
    """Refresh race-sensitive read-only checks for one exact execution candidate.

    This helper is deliberately mutation-free. It first verifies that the supplied
    prior attestation is complete and bound to the exact executable candidate. If
    that check fails, no live provider reads are attempted. Otherwise it derives an
    otherwise-identical disabled plan, re-runs the reviewed read-only probe stack,
    and requires the fresh result to authorize the same execution target.

    The returned readiness remains ``execution_available=False``. A later reviewed
    integration may invoke this helper while holding the per-group provisioning
    lock immediately before the first mutation. This module does not acquire that
    lock, create resources, publish GroupDBConfig, or enable execution itself.
    """

    if not readiness_allows_execution_candidate(readiness, plan):
        raise TenantProvisioningExecutionReadinessError(
            "readiness_attestation_invalid"
        )

    disabled_plan = replace(plan, execution_available=False)
    try:
        refreshed = inspect_tenant_provisioning_backend_readiness(
            disabled_plan,
            probe,
        )
    except TenantProvisioningBackendReadinessError as exc:
        raise TenantProvisioningExecutionReadinessError(
            "readiness_revalidation_failed"
        ) from exc
    except Exception as exc:
        # Keep provider/client details outside the orchestration error surface.
        raise TenantProvisioningExecutionReadinessError(
            "readiness_revalidation_failed"
        ) from exc

    if not readiness_allows_execution_candidate(refreshed, plan):
        raise TenantProvisioningExecutionReadinessError(
            "readiness_revalidation_failed"
        )
    return refreshed
