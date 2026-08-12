"""Canonical tenant permission vocabulary used by active GeoFlow authorization surfaces.

The central ``permissions`` table can contain historical or future rows, but tenant
route guards and permission-aware templates must use only these reviewed codes.
Adding, removing, or renaming a live permission is therefore an explicit code
change rather than an unreviewed string literal drift.
"""

from __future__ import annotations


TENANT_PERMISSION_TAXONOMY = {
    "contracts": frozenset({"view", "create", "edit"}),
    "partners": frozenset({"view", "create"}),
    "projects": frozenset({"view", "edit"}),
    "directory": frozenset({"view", "edit", "roles.assign"}),
}

TENANT_PERMISSION_CODES = frozenset(
    f"{domain}.{action}"
    for domain, actions in TENANT_PERMISSION_TAXONOMY.items()
    for action in actions
)
