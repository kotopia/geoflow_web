from __future__ import annotations

import os
import sys
import uuid

import psycopg2


SCOPE_NAMESPACE = uuid.UUID("9e4a4659-3c7f-4f4a-95a0-12d64de2dcec")
PROJECT_MATRIX = (
    ("GIS-DEV-001", "WATER", "PROC_SURVEY"),
    ("GIS-DEV-001", "SEWERAGE", "PROC_STRUCT"),
    ("GIS-DEV-002", "WATER", "PROC_EXPLORE"),
    ("GIS-DEV-003", "SEWERAGE", "PROC_FIX"),
    ("GIS-DEV-005", "ROAD", "PROC_SURVEY"),
    ("GIS-DEV-006", "WATER", "PROC_SURVEY"),
    ("GIS-DEV-006", "WATER", "PROC_STRUCT"),
    ("GIS-DEV-006", "WATER", "PROC_DRAW"),
)
DOMAIN_CAPABILITY = {
    "WATER": "WATER",
    "SEWERAGE": "SEWER",
    "ROAD": "ROAD",
}
OLD_SYNTHETIC_SCOPE_IDS = tuple(
    f"71000000-0000-4000-8000-{index:012d}" for index in range(1, 8)
)
OLD_SYNTHETIC_BINDING_CODES = (
    "GIS_DEV_SCOPE_WATER",
    "GIS_DEV_SCOPE_SEWER",
    "GIS_DEV_SCOPE_ROAD",
    "GIS_DEV_SCOPE_SURVEY",
)
MARKER = "Synthetic REAL-CATALOG GIS scope:"


def require_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not str(value).strip():
        raise SystemExit(f"missing required environment variable: {name}")
    return str(value).strip()


def require_dev_name(value: str, label: str) -> None:
    lowered = value.lower()
    if "dev" not in lowered and "test" not in lowered:
        raise SystemExit(f"safety stop: {label} must be a dev/test DB: {value}")


def connect(prefix: str):
    return psycopg2.connect(
        dbname=require_env(f"{prefix}_DB_NAME"),
        user=require_env(f"{prefix}_DB_USER"),
        password=require_env(f"{prefix}_DB_PASSWORD"),
        host=require_env(f"{prefix}_DB_HOST"),
        port=require_env(f"{prefix}_DB_PORT"),
        sslmode="require",
    )


def exactly_one(cursor, sql: str, params: tuple, label: str):
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise SystemExit(f"expected exactly one {label}, found {len(rows)}")
    return rows[0]


def resolve_catalog(central) -> tuple[dict[str, dict], dict[tuple[str, str], dict]]:
    domains: dict[str, dict] = {}
    options: dict[tuple[str, str], dict] = {}
    with central.cursor() as cur:
        for domain_code in DOMAIN_CAPABILITY:
            row = exactly_one(
                cur,
                """
                select id::text, code, name
                  from catalog.category_node
                 where code=%s and level=2 and active=true
                """,
                (domain_code,),
                f"active L2 catalog node code={domain_code}",
            )
            domains[domain_code] = {"id": row[0], "code": row[1], "name": row[2]}

        for _project_code, domain_code, option_code in PROJECT_MATRIX:
            key = (domain_code, option_code)
            if key in options:
                continue
            domain = domains[domain_code]
            row = exactly_one(
                cur,
                """
                select o.id::text, o.code, o.name, coalesce(o.default_unit, 'NONE')
                  from catalog.category_option_set s
                  join catalog.category_facet_option o on o.facet_id=s.facet_id
                 where s.l2_id=%s::uuid
                   and s.level_no=3
                   and o.code=%s
                   and o.active=true
                """,
                (domain["id"], option_code),
                f"active L3 option domain={domain_code} code={option_code}",
            )
            options[key] = {
                "id": row[0],
                "code": row[1],
                "name": row[2],
                "unit": row[3] or "NONE",
            }
    return domains, options


def verify_tenant_foundation(tenant) -> None:
    with tenant.cursor() as cur:
        cur.execute(
            """
            select current_database(),
                   to_regclass('prj.projects'),
                   to_regclass('prj.scope_item'),
                   to_regclass('gis.scope_binding'),
                   to_regclass('gis.capability'),
                   to_regclass('gis.project_profile')
            """
        )
        row = cur.fetchone()
        if not row or any(value is None for value in row[1:]):
            raise SystemExit("tenant project/GIS scope foundation is incomplete")


def sync_bindings(tenant, domains: dict[str, dict]) -> None:
    with tenant.cursor() as cur:
        for catalog_code, capability_code in DOMAIN_CAPABILITY.items():
            domain = domains[catalog_code]
            capability = exactly_one(
                cur,
                "select id::text from gis.capability where code=%s and active=true",
                (capability_code,),
                f"active GIS capability code={capability_code}",
            )
            cur.execute(
                """
                insert into gis.scope_binding(
                    id, catalog_level, catalog_item_id, catalog_code_cache,
                    catalog_name_cache, capability_id, active, priority, note
                )
                values (
                    gen_random_uuid(), 2, %s::uuid, %s, %s,
                    %s::uuid, true, 100,
                    'Synced from canonical central catalog code for GeoFlow GIS domain.'
                )
                on conflict (catalog_level, catalog_item_id, capability_id)
                do update set
                    catalog_code_cache=excluded.catalog_code_cache,
                    catalog_name_cache=excluded.catalog_name_cache,
                    active=true,
                    priority=excluded.priority,
                    note=excluded.note,
                    updated_at=now()
                """,
                (domain["id"], domain["code"], domain["name"], capability[0]),
            )


def reconcile_scope_rows(tenant, domains: dict[str, dict], options: dict[tuple[str, str], dict]) -> None:
    with tenant.cursor() as cur:
        cur.execute(
            "delete from gis.scope_binding where catalog_code_cache = any(%s)",
            (list(OLD_SYNTHETIC_BINDING_CODES),),
        )
        cur.execute(
            "delete from prj.scope_item where id::text = any(%s) or remark like %s",
            (list(OLD_SYNTHETIC_SCOPE_IDS), f"{MARKER}%"),
        )

        project_ids: dict[str, str] = {}
        for project_code in {row[0] for row in PROJECT_MATRIX} | {"GIS-DEV-004"}:
            row = exactly_one(
                cur,
                "select id::text from prj.projects where code=%s",
                (project_code,),
                f"development project code={project_code}",
            )
            project_ids[project_code] = row[0]

        cur.execute(
            """
            update prj.projects
               set name='상수도 다공정 GIS 프로젝트',
                   description='Synthetic WATER project with multiple real catalog L3 process scopes.',
                   updated_at=now()
             where code='GIS-DEV-006'
            """
        )

        for project_code, domain_code, option_code in PROJECT_MATRIX:
            domain = domains[domain_code]
            option = options[(domain_code, option_code)]
            scope_id = uuid.uuid5(
                SCOPE_NAMESPACE,
                f"{project_code}|{domain_code}|{option_code}",
            )
            cur.execute(
                """
                insert into prj.scope_item(
                    id, project_id, lv2_id, lv3_id, lv4_id,
                    unit, design_qty, completed_qty, remark, created_at, updated_at
                )
                values (
                    %s::uuid, %s::uuid, %s::uuid, %s::uuid, NULL,
                    %s, 1.000, NULL, %s, now(), now()
                )
                on conflict (id) do update set
                    project_id=excluded.project_id,
                    lv2_id=excluded.lv2_id,
                    lv3_id=excluded.lv3_id,
                    lv4_id=NULL,
                    unit=excluded.unit,
                    design_qty=excluded.design_qty,
                    remark=excluded.remark,
                    updated_at=now()
                """,
                (
                    str(scope_id),
                    project_ids[project_code],
                    domain["id"],
                    option["id"],
                    option["unit"],
                    f"{MARKER} {domain_code}/{option_code}",
                ),
            )

        profile = exactly_one(
            cur,
            "select id::text from gis.profile where code='GEOFLOW_DEV_BASE' and active=true",
            (),
            "active GEOFLOW_DEV_BASE profile",
        )
        for project_code in (
            "GIS-DEV-001",
            "GIS-DEV-002",
            "GIS-DEV-003",
            "GIS-DEV-004",
            "GIS-DEV-005",
            "GIS-DEV-006",
        ):
            cur.execute(
                """
                insert into gis.project_profile(project_id, profile_id, status, auto_assigned)
                values (%s::uuid, %s::uuid, 'active', true)
                on conflict (project_id) do update set
                    profile_id=excluded.profile_id,
                    status='active',
                    auto_assigned=true,
                    updated_at=now()
                """,
                (project_ids[project_code], profile[0]),
            )


def print_verification(tenant) -> None:
    with tenant.cursor() as cur:
        cur.execute(
            """
            with caps as (
                select distinct s.project_id, c.code
                  from prj.scope_item s
                  join gis.scope_binding b
                    on b.active
                   and b.catalog_level=2
                   and b.catalog_item_id=s.lv2_id
                  join gis.capability c on c.id=b.capability_id and c.active
            ), procs as (
                select s.project_id, count(*) as process_count
                  from prj.scope_item s
                 where s.remark like %s
                 group by s.project_id
            )
            select p.code,
                   coalesce(string_agg(distinct caps.code, ',' order by caps.code), 'NO_GIS') as capabilities,
                   coalesce(procs.process_count, 0) as process_count
              from prj.projects p
              left join caps on caps.project_id=p.id
              left join procs on procs.project_id=p.id
             where p.code in ('GIS-DEV-001','GIS-DEV-002','GIS-DEV-003','GIS-DEV-004','GIS-DEV-005','GIS-DEV-006')
             group by p.code, procs.process_count
             order by p.code
            """,
            (f"{MARKER}%",),
        )
        rows = cur.fetchall()
    for project_code, capabilities, process_count in rows:
        print(
            f"project={project_code} capabilities={capabilities} "
            f"real_catalog_process_scopes={process_count}"
        )

    expected = {
        "GIS-DEV-001": "SEWER,WATER",
        "GIS-DEV-002": "WATER",
        "GIS-DEV-003": "SEWER",
        "GIS-DEV-004": "NO_GIS",
        "GIS-DEV-005": "ROAD",
        "GIS-DEV-006": "WATER",
    }
    actual = {row[0]: row[1] for row in rows}
    if actual != expected:
        raise SystemExit(f"unexpected GIS capability matrix: {actual}")
    if dict((row[0], row[2]) for row in rows).get("GIS-DEV-006") != 3:
        raise SystemExit("GIS-DEV-006 must contain three WATER process scopes")
    print("RESULT real_catalog_scope_matrix=OK")


def main() -> int:
    central_name = require_env("CENTRAL_DB_NAME")
    tenant_name = require_env("TENANT_DB_NAME")
    require_dev_name(central_name, "central DB")
    require_dev_name(tenant_name, "tenant DB")

    central = connect("CENTRAL")
    tenant = connect("TENANT")
    try:
        domains, options = resolve_catalog(central)
        verify_tenant_foundation(tenant)
        with tenant:
            sync_bindings(tenant, domains)
            reconcile_scope_rows(tenant, domains, options)
        print(f"central_db={central_name} tenant_db={tenant_name}")
        for code, domain in domains.items():
            print(f"catalog_domain code={code} id={domain['id']}")
        print_verification(tenant)
        return 0
    finally:
        central.close()
        tenant.close()


if __name__ == "__main__":
    sys.exit(main())
