"""Read-only GeoFlow development runtime verifier.

This script never migrates or writes data. It validates that the Django runtime
is bound only to the reviewed development central/tenant databases and that the
synthetic GIS/login fixtures required for browser smoke testing are present.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys


# When this file is executed directly, Python puts scripts/dev at sys.path[0]
# rather than the repository root. Resolve and pin the repository root so
# geoflow_project and sibling Django packages are importable on Windows/Linux.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-alias", default="cheonan_db")
    parser.add_argument("--expected-central-db", default="geoflow_control_dev")
    parser.add_argument("--expected-tenant-db", default="geoflow_dev")
    parser.add_argument(
        "--mode",
        choices=("routing", "gis", "all"),
        default="all",
    )
    return parser.parse_args()


def require_dev_name(value: str, label: str) -> None:
    lowered = value.lower()
    if "dev" not in lowered and "test" not in lowered:
        raise SystemExit(f"safety stop: {label} must be a dev/test database: {value}")


def configure_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geoflow_project.settings")
    import django

    django.setup()


def verify_routing(args: argparse.Namespace) -> None:
    from django.db import connections

    central = connections["default"]
    tenant = connections[args.tenant_alias]

    with central.cursor() as cursor:
        cursor.execute("select current_database()")
        central_db = cursor.fetchone()[0]

    with tenant.cursor() as cursor:
        cursor.execute("select current_database(), PostGIS_Version()")
        tenant_db, postgis = cursor.fetchone()

    print(f"central_db={central_db}")
    print(f"tenant_alias={args.tenant_alias} tenant_db={tenant_db}")
    print(f"postgis={postgis}")

    if central_db != args.expected_central_db:
        raise SystemExit(
            f"central DB mismatch: expected={args.expected_central_db} actual={central_db}"
        )
    if tenant_db != args.expected_tenant_db:
        raise SystemExit(
            f"tenant DB mismatch: expected={args.expected_tenant_db} actual={tenant_db}"
        )


def verify_central_login_path(args: argparse.Namespace) -> None:
    from django.db import connections

    with connections["default"].cursor() as cursor:
        cursor.execute(
            """
            select
                u.email,
                u.is_active,
                u.email_verified,
                g.code,
                g.status,
                r.code,
                c.db_alias,
                c.db_name
            from users u
            join user_group_map ug on ug.user_id = u.id
            join groups g on g.id = ug.group_id
            join roles r on r.id = ug.role_id
            join group_db_config c on c.group_id = g.id
            where lower(u.email) = lower(%s)
            limit 1
            """,
            ["gis-dev-admin@geoflow.invalid"],
        )
        row = cursor.fetchone()
        if not row:
            raise SystemExit("synthetic central GIS login account/membership not found")

        email, is_active, email_verified, group_code, group_status, role_code, db_alias, db_name = row
        cursor.execute(
            """
            select exists (
                select 1
                from roles r
                join role_permissions rp on rp.role_id = r.id
                join permissions p on p.id = rp.permission_id
                where r.code = %s and p.code = %s
            )
            """,
            [role_code, "maps.view"],
        )
        has_maps_view = cursor.fetchone()[0]

    print(
        "central_login="
        f"{email} active={is_active} verified={email_verified} "
        f"group={group_code}/{group_status} role={role_code} "
        f"maps.view={has_maps_view} route={db_alias}->{db_name}"
    )

    if not is_active or not email_verified:
        raise SystemExit("synthetic central GIS login account is not active+verified")
    if group_status != "active":
        raise SystemExit("synthetic GIS development group is not active")
    if not has_maps_view:
        raise SystemExit(f"role {role_code} does not provide maps.view")
    if db_alias != args.tenant_alias:
        raise SystemExit(
            f"tenant alias mismatch in central route: expected={args.tenant_alias} actual={db_alias}"
        )
    if db_name != args.expected_tenant_db:
        raise SystemExit(
            f"tenant DB name mismatch in central route: expected={args.expected_tenant_db} actual={db_name}"
        )


def verify_gis(args: argparse.Namespace) -> None:
    from django.db import connections

    conn = connections[args.tenant_alias]
    initial_tables = (
        "doro",
        "survey",
        "wtl_etc_ps",
        "wtl_fire_ps",
        "wtl_flow_ps",
        "wtl_manh_ps",
        "wtl_pipe_lm",
        "wtl_pipe_ps",
        "wtl_plan_lm",
        "wtl_sply_ls",
        "wtl_valv_ps",
        "swl_conn_ls",
        "swl_etc_ps",
        "swl_manh_ps",
        "swl_pipe_as",
        "swl_pipe_lm",
        "swl_pipe_ps",
        "swl_side_ls",
        "swl_spot_ps",
    )

    with conn.cursor() as cursor:
        cursor.execute("select count(*) from gis.meta_feature_type where active")
        feature_types = cursor.fetchone()[0]
        cursor.execute("select count(*) from gis.meta_field_def")
        field_defs = cursor.fetchone()[0]

        cursor.execute(
            "select id::text, code, name from prj.projects "
            "where code=%s order by updated_at desc nulls last limit 1",
            ["GIS-DEV-001"],
        )
        project = cursor.fetchone()
        if not project:
            raise SystemExit("synthetic GIS project not found")
        project_id = project[0]

        missing_tables: list[str] = []
        for table in initial_tables:
            cursor.execute("select to_regclass(%s)", [f"gis.{table}"])
            if cursor.fetchone()[0] is None:
                missing_tables.append(table)

        layer_counts: dict[str, int] = {}
        for table in (
            "survey",
            "doro",
            "wtl_pipe_lm",
            "wtl_valv_ps",
            "wtl_manh_ps",
            "swl_pipe_lm",
            "swl_manh_ps",
        ):
            cursor.execute(
                f'SELECT count(*) FROM gis."{table}" WHERE project_id=%s',
                [project_id],
            )
            layer_counts[table] = cursor.fetchone()[0]

        cursor.execute(
            "select count(*) from gis.wtl_pipe_lm "
            "where project_id=%s and (ftr_cde is not null or ftr_idn is not null)",
            [project_id],
        )
        legacy_identity_values = cursor.fetchone()[0]

        cursor.execute(
            """
            select count(*)
            from gis.survey_link sl
            join gis.meta_feature_type ft on ft.id = sl.feature_type_id
            where ft.standard_name='WTL_PIPE_LM'
              and sl.target_id in (
                  select id from gis.wtl_pipe_lm where project_id=%s
              )
            """,
            [project_id],
        )
        survey_links = cursor.fetchone()[0]

    print(f"feature_types={feature_types} field_defs={field_defs}")
    print(f"physical_tables_ready={len(initial_tables) - len(missing_tables)}/{len(initial_tables)}")
    print(f"project_id={project_id} code={project[1]} name={project[2]}")
    print("counts " + " ".join(f"{key}={value}" for key, value in layer_counts.items()))
    print(f"wtl_pipe_legacy_identity_values={legacy_identity_values}")
    print(f"survey_links_to_wtl_pipe_uuid={survey_links}")

    if feature_types != 19:
        raise SystemExit(f"expected 19 feature types, got {feature_types}")
    if field_defs <= 0:
        raise SystemExit("field metadata is empty")
    if missing_tables:
        raise SystemExit("missing GIS physical tables: " + ", ".join(missing_tables))
    if layer_counts["survey"] < 1 or layer_counts["wtl_pipe_lm"] < 2:
        raise SystemExit("synthetic GIS object seed is incomplete")
    if legacy_identity_values != 0:
        raise SystemExit("synthetic WTL pipe objects unexpectedly use ftr_cde/ftr_idn")
    if survey_links < 1:
        raise SystemExit("UUID survey_link lineage was not found")


def main() -> int:
    args = parse_args()
    require_dev_name(args.expected_central_db, "expected central DB")
    require_dev_name(args.expected_tenant_db, "expected tenant DB")
    configure_django()

    if args.mode in ("routing", "all"):
        verify_routing(args)
        verify_central_login_path(args)
    if args.mode in ("gis", "all"):
        verify_gis(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
