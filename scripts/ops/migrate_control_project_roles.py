#!/usr/bin/env python3
"""Safely rename GeoFlow central/control role codes.

Dry-run is the default. This script changes only ``roles.code`` and ``roles.name``;
role IDs, user assignments, and role-permission mappings remain intact.
"""
from __future__ import annotations

import argparse
import os
import sys

import psycopg2


ROLE_CHANGES = (
    ("project_manager", "project_admin", "프로젝트 관리자"),
    ("project_leader", "project_coordinator", "프로젝트 코디네이터"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.environ.get("CONTROL_DATABASE_URL"))
    parser.add_argument(
        "--apply",
        action="store_true",
        help="commit the role rename; without this flag the transaction is rolled back",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.database_url:
        print("CONTROL_DATABASE_URL or --database-url is required", file=sys.stderr)
        return 2

    with psycopg2.connect(args.database_url) as connection:
        connection.autocommit = False
        with connection.cursor() as cursor:
            cursor.execute("LOCK TABLE roles IN SHARE ROW EXCLUSIVE MODE")
            codes = tuple(code for pair in ROLE_CHANGES for code in pair[:2])
            cursor.execute(
                "SELECT code, name FROM roles WHERE code = ANY(%s) ORDER BY code FOR UPDATE",
                (list(codes),),
            )
            found = {code: name for code, name in cursor.fetchall()}

            for old_code, new_code, new_name in ROLE_CHANGES:
                if new_code in found:
                    raise RuntimeError(
                        f"refusing ambiguous migration: target role {new_code!r} already exists"
                    )
                if old_code not in found:
                    raise RuntimeError(f"expected source role {old_code!r} does not exist")

                cursor.execute(
                    "UPDATE roles SET code=%s, name=%s WHERE code=%s",
                    (new_code, new_name, old_code),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError(f"expected exactly one {old_code!r} role row")

            cursor.execute(
                """
                SELECT r.code, r.name,
                       COUNT(DISTINCT ugm.id) AS assignments,
                       COUNT(DISTINCT rp.permission_id) AS permissions
                  FROM roles r
                  LEFT JOIN user_group_map ugm ON ugm.role_id=r.id
                  LEFT JOIN role_permissions rp ON rp.role_id=r.id
                 WHERE r.code = ANY(%s)
                 GROUP BY r.id, r.code, r.name
                 ORDER BY r.code
                """,
                ([change[1] for change in ROLE_CHANGES],),
            )
            for code, name, assignments, permissions in cursor.fetchall():
                print(f"{code}: {name}; assignments={assignments}; permissions={permissions}")

        if args.apply:
            connection.commit()
            print("control role migration committed")
        else:
            connection.rollback()
            print("dry-run complete; transaction rolled back")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
