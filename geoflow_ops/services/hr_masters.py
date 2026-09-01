from __future__ import annotations

from django.db import connections


MASTER_FIELD_REFS = {
    "position_grade": "employee.position_grade",
    "position_title": "employee.position_title",
}


def master_table_exists(alias: str, category: str) -> bool:
    if category not in MASTER_FIELD_REFS:
        return False
    with connections[alias].cursor() as cur:
        cur.execute(
            "SELECT 1 FROM ops.settings_nodes WHERE field_ref=%s LIMIT 1",
            [MASTER_FIELD_REFS[category]],
        )
        return cur.fetchone() is not None


def list_master_options(alias: str, category: str, *, active_only: bool = True):
    field_ref = MASTER_FIELD_REFS.get(category)
    if not field_ref:
        return []
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT child.id::text, child.name, child.ord, child.active, child.locked
              FROM ops.settings_nodes category
              JOIN ops.settings_nodes child ON child.parent_id=category.id
             WHERE category.field_ref=%s AND (%s=false OR child.active=true)
             ORDER BY child.ord, child.name, child.id
            """,
            [field_ref, active_only],
        )
        rows = cur.fetchall()
    return [
        {"id": row[0], "code": "", "name": row[1] or "", "ord": row[2] or 0,
         "active": bool(row[3]), "system_default": bool(row[4])}
        for row in rows
    ]
