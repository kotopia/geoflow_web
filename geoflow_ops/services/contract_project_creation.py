from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone

from geoflow_ops.models import Contract, Project


def project_create_kwargs(contract: Contract, *, now=None) -> dict[str, Any]:
    """Return the canonical Project fields derived from one Contract."""
    timestamp = now or timezone.now()
    contract_code = str(contract.code or "").strip()
    project_code = f"C{contract_code.replace('-', '')}" if contract_code else None
    return {
        "contract": contract,
        "code": project_code,
        "name": contract.name,
        "start_date": contract.start_date,
        "end_date": contract.end_date,
        "status": contract.status or "active",
        "org_unit_id": getattr(contract, "org_unit_id", None),
        "ext": {},
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def create_project_for_contract(alias: str, contract: Contract, *, now=None) -> Project:
    """Create exactly one Project for a contract; callers own any surrounding lock."""
    existing = Project.objects.using(alias).filter(contract_id=contract.id).count()
    if existing:
        raise RuntimeError("contract already has a project")
    return Project.objects.using(alias).create(**project_create_kwargs(contract, now=now))


def save_new_contract_with_project(alias: str, contract: Contract, *, now=None) -> tuple[Contract, Project]:
    """Persist a new contract and its project in one tenant-DB transaction."""
    if not contract._state.adding:
        raise ValueError("save_new_contract_with_project requires an unsaved contract")

    timestamp = now or timezone.now()
    if not contract.created_at:
        contract.created_at = timestamp
    contract.updated_at = timestamp
    if contract.ext is None:
        contract.ext = {}

    with transaction.atomic(using=alias):
        contract.save(using=alias)
        project = create_project_for_contract(alias, contract, now=timestamp)

    return contract, project
