from __future__ import annotations

import os
from inspect import unwrap
from unittest.mock import patch
from uuid import UUID

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geoflow_project.ci_migration_settings")

import django

django.setup()

from django.db import connections
from django.test import RequestFactory

from control.views_user_assignment import users_assign_group_admin


USER_ID = UUID("00000000-0000-0000-0000-000000000031")
GROUP_ID = UUID("00000000-0000-0000-0000-000000000041")
ROLE_A_ID = UUID("00000000-0000-0000-0000-000000000051")
ROLE_B_ID = UUID("00000000-0000-0000-0000-000000000052")


def seed() -> None:
    with connections["default"].cursor() as cur:
        cur.execute(
            """
            INSERT INTO users(id, email, password_hash, is_active, email_verified)
            VALUES (%s, %s, %s, TRUE, TRUE)
            """,
            [str(USER_ID), "role-assignment-ci@example.invalid", "pbkdf2_sha256$1$salt$hash"],
        )
        cur.execute(
            "INSERT INTO groups(id, code, name, status) VALUES (%s, %s, %s, 'active')",
            [str(GROUP_ID), "ci-group", "CI Group"],
        )
        cur.execute(
            "INSERT INTO roles(id, code, name) VALUES (%s, %s, %s)",
            [str(ROLE_A_ID), "ci-role-a", "CI Role A"],
        )
        cur.execute(
            "INSERT INTO roles(id, code, name) VALUES (%s, %s, %s)",
            [str(ROLE_B_ID), "ci-role-b", "CI Role B"],
        )


def assign(role_id: UUID) -> None:
    request = RequestFactory().post(
        "/control/mgmt/users/assign/",
        {"group_id": str(GROUP_ID), "role_id": str(role_id)},
    )
    with patch("control.views_user_assignment.messages.success") as success, patch(
        "control.views_user_assignment.messages.error"
    ) as error:
        response = unwrap(users_assign_group_admin)(request, USER_ID)
    if response.status_code != 302:
        raise AssertionError("assignment did not redirect")
    if success.call_count != 1 or error.call_count != 0:
        raise AssertionError("assignment did not report success")


def membership_state() -> tuple[int, str, str]:
    with connections["default"].cursor() as cur:
        cur.execute(
            """
            SELECT count(*), min(role_id::text), min(status)
              FROM user_group_map
             WHERE user_id=%s AND group_id=%s
            """,
            [str(USER_ID), str(GROUP_ID)],
        )
        count, role_id, status = cur.fetchone()
    return int(count), str(role_id or ""), str(status or "")


def main() -> None:
    seed()

    # First assignment proves the parameterized LIKE predicates execute through
    # Psycopg and the insert path does not require ON CONFLICT or a unique index.
    assign(ROLE_A_ID)
    count, role_id, status = membership_state()
    if (count, role_id, status) != (1, str(ROLE_A_ID), "active"):
        raise AssertionError("first assignment state mismatch")
    print("role_assignment_postgres_first_insert=yes")
    print("role_assignment_postgres_membership_count_after_insert=1")

    # Second assignment must update the existing membership instead of inserting
    # a duplicate even though the schema deliberately has no unique constraint.
    assign(ROLE_B_ID)
    count, role_id, status = membership_state()
    if (count, role_id, status) != (1, str(ROLE_B_ID), "active"):
        raise AssertionError("role update state mismatch")
    print("role_assignment_postgres_update_existing=yes")
    print("role_assignment_postgres_membership_count_after_update=1")
    print("role_assignment_postgres_integration_complete=yes")


if __name__ == "__main__":
    main()
