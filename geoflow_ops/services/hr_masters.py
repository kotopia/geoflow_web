from __future__ import annotations

from django.db import connections


MASTER_TABLES = {
    "position_grade": "hr.job_grades",
    "position_title": "hr.job_positions",
}


def master_table_exists(alias: str, category: str) -> bool:
    relation = MASTER_TABLES.get(category)
    if not relation:
        return False
    with connections[alias].cursor() as cur:
        cur.execute("SELECT to_regclass(%s) IS NOT NULL", [relation])
        row = cur.fetchone()
    return bool(row and row[0])


def list_master_options(alias: str, category: str, *, active_only: bool = True):
    relation = MASTER_TABLES.get(category)
    if not relation:
        return []
    where = "WHERE active = true" if active_only else ""
    with connections[alias].cursor() as cur:
        cur.execute(
            f"""
            SELECT id::text, code, name, ord, active, system_default
              FROM {relation}
              {where}
             ORDER BY ord, name, code
            """
        )
        rows = cur.fetchall()
    return [
        {
            "id": row[0],
            "code": row[1] or "",
            "name": row[2] or "",
            "ord": row[3] or 0,
            "active": bool(row[4]),
            "system_default": bool(row[5]),
        }
        for row in rows
    ]
