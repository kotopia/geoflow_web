"""Read-only diagnostic for the synthetic GeoFlow development login path.

This script executes the same central-account lookup, password verifier, tenant
candidate construction, and tenant-selection filters used by the live login flow.
It never writes to the database and never prints the supplied password or hash.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", default="gis-dev-admin@geoflow.invalid")
    parser.add_argument("--tenant-alias", default="cheonan_db")
    parser.add_argument("--expected-central-db", default="geoflow_control_dev")
    parser.add_argument("--expected-tenant-db", default="geoflow_dev")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    password = os.environ.get("GEOFLOW_DEV_DIAGNOSTIC_PASSWORD", "")
    if not password:
        raise SystemExit("diagnostic password environment is missing")

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geoflow_project.settings")
    import django

    django.setup()

    from django.conf import settings
    from django.db import connections
    from control.services.central_login_authentication import verify_central_login_password
    from control.services import central_repo as C
    from control.services.tenant_selection import (
        configured_static_tenant_aliases,
        selectable_tenant_candidates,
        static_tenant_database_config_is_ready,
    )

    central_alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")
    central = connections[central_alias]

    with central.cursor() as cur:
        cur.execute("select current_database()")
        central_db = cur.fetchone()[0]
        cur.execute(
            """
            select id::text, email, password_hash, is_active, email_verified
              from users
             where lower(email)=lower(%s)
            """,
            [args.email],
        )
        user_rows = cur.fetchall()

    print(f"central_db={central_db}")
    print(f"user_rows_for_email={len(user_rows)}")
    if central_db != args.expected_central_db:
        print("RESULT central_db=FAIL")
        return 20
    if len(user_rows) != 1:
        print("RESULT central_user_lookup=FAIL")
        return 21

    user_id, email, password_hash, is_active, email_verified = user_rows[0]
    algorithm = "unknown"
    if password_hash:
        algorithm = str(password_hash).split("$", 1)[0]
    print(
        f"central_user id={user_id} email={email} active={is_active} "
        f"verified={email_verified} algorithm={algorithm}"
    )

    password_result = verify_central_login_password(password, password_hash)
    print(
        "password_verifier="
        + ("OK" if password_result.valid else "FAIL")
        + f" needs_rehash={password_result.needs_rehash}"
    )
    if not is_active or not email_verified:
        print("RESULT central_account_state=FAIL")
        return 22
    if not password_result.valid:
        print("RESULT password=FAIL")
        return 23

    with central.cursor() as cur:
        cur.execute(
            """
            select
                ug.status,
                g.id::text,
                g.code,
                g.name,
                g.status,
                r.code,
                c.db_alias,
                c.db_name,
                c.db_host,
                c.db_port,
                c.db_user,
                case when coalesce(c.db_password, '') <> '' then true else false end
            from user_group_map ug
            join groups g on g.id=ug.group_id
            join roles r on r.id=ug.role_id
            left join group_db_config c on c.group_id=g.id
            where ug.user_id=%s
            order by g.code
            """,
            [user_id],
        )
        memberships = cur.fetchall()

    print(f"memberships={len(memberships)}")
    for row in memberships:
        (
            membership_status,
            group_id,
            group_code,
            group_name,
            group_status,
            role_code,
            db_alias,
            db_name,
            _db_host,
            _db_port,
            _db_user,
            has_db_password,
        ) = row
        print(
            "membership "
            f"group={group_code}({group_id}) membership_status={membership_status} "
            f"group_status={group_status} role={role_code} "
            f"route={db_alias}->{db_name} config_password_present={has_db_password}"
        )

    candidates = C.list_tenants_for_user(user_id)
    print(f"raw_tenant_candidates={candidates}")
    selectable = selectable_tenant_candidates(user_id, candidates)
    print(f"selectable_tenant_candidates={selectable}")

    static_aliases = sorted(configured_static_tenant_aliases())
    static_ready = static_tenant_database_config_is_ready(args.tenant_alias)
    tenant_database = settings.DATABASES.get(args.tenant_alias, {})
    print(f"static_tenant_aliases={static_aliases}")
    print(
        f"static_tenant_ready={static_ready} configured_physical_db="
        f"{tenant_database.get('NAME')}"
    )

    approval_ok = any(
        row[0] == "active"
        and row[4] == "active"
        and row[6] == args.tenant_alias
        and row[7] == args.expected_tenant_db
        for row in memberships
    )
    selectable_ok = any(
        str(candidate.get("db_alias")) == args.tenant_alias
        for candidate in selectable
    )
    physical_ok = tenant_database.get("NAME") == args.expected_tenant_db

    print("approval_final_state=" + ("OK" if approval_ok else "FAIL"))
    print("tenant_candidate_selectable=" + ("OK" if selectable_ok else "FAIL"))
    print("tenant_physical_mapping=" + ("OK" if physical_ok else "FAIL"))

    if not approval_ok:
        print("RESULT approval=FAIL")
        return 24
    if not selectable_ok:
        print("RESULT tenant_selection=FAIL")
        return 25
    if not static_ready or not physical_ok:
        print("RESULT tenant_runtime_mapping=FAIL")
        return 26

    print("RESULT exact_login_prerequisites=OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
