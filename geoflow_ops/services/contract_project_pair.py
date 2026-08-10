from __future__ import annotations

from uuid import UUID

from django.utils import timezone

from geoflow_ops.models import Contract, Project


def canonical_project_values(contract: Contract, *, now=None) -> dict:
    """Return the canonical project fields derived from a newly created contract."""
    stamp = now or timezone.now()
    code = str(contract.code or "").strip()
    return {
        "contract_id": contract.pk,
        "code": f"C{code.replace('-', '')}" if code else None,
        "name": contract.name,
        "start_date": contract.start_date,
        "end_date": contract.end_date,
        "status": "active",
        "ext": {},
        "created_at": stamp,
        "updated_at": stamp,
    }


def create_project_for_new_contract(alias: str, contract: Contract, *, now=None) -> Project:
    """Create exactly one project for a contract that was just inserted.

    The caller must hold the surrounding tenant transaction. Existing project
    rows are treated as an invariant violation rather than silently reused, so
    a partially duplicated create path cannot commit unnoticed.
    """
    if not alias:
        raise ValueError("tenant database alias is required")
    if not contract.pk:
        raise ValueError("contract must be saved before project creation")

    existing = Project.objects.using(alias).filter(contract_id=contract.pk).count()
    if existing:
        raise RuntimeError("new contract already has a project")

    return Project.objects.using(alias).create(**canonical_project_values(contract, now=now))


def contract_id_from_create_response(response) -> UUID:
    """Extract the newly-created contract UUID from the canonical detail redirect."""
    if not (300 <= int(getattr(response, "status_code", 0)) < 400):
        raise ValueError("contract create response is not a redirect")
    path = str(getattr(response, "url", "") or "").split("?", 1)[0].rstrip("/")
    token = path.rsplit("/", 1)[-1] if path else ""
    try:
        return UUID(token)
    except (TypeError, ValueError, AttributeError) as exc:
        raise RuntimeError("contract create redirect did not contain a UUID") from exc
