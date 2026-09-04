from __future__ import annotations

import os
import sys

import psycopg2


MAPPINGS = (
    ("WATER", "WATER", 2),
    ("SEWERAGE", "SEWER", 2),
    ("ROAD", "ROAD", 2),
)


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


def one_row(cursor, sql: str, params: tuple, label: str):
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise SystemExit(f"expected exactly one {label}, found {len(rows)}")
    return rows[0]


def main() -> int:
    central_name = require_env("CENTRAL_DB_NAME")
    tenant_name = require_env("TENANT_DB_NAME")
    require_dev_name(central_name, "central DB")
    require_dev_name(tenant_name, "tenant DB")

    central = connect("CENTRAL")
    tenant = connect("TENANT")
    try:
        with central.cursor() as cur:
            cur.execute("select current_database(), to_regclass('catalog.category_node')")
            current_db, catalog_table = cur.fetchone()
            if current_db != central_name or catalog_table is None:
                raise SystemExit("central development catalog.category_node is unavailable")

        with tenant.cursor() as cur:
            cur.execute(
                "select current_database(), to_regclass('gis.scope_binding'), to_regclass('gis.capability')"
            )
            current_db, scope_binding, capability = cur.fetchone()
            if current_db != tenant_name or scope_binding is None or capability is None:
                raise SystemExit("tenant GIS scope/capability metadata is unavailable")

        resolved: list[tuple[str, str, str, int]] = []
        with central.cursor() as central_cur:
            for catalog_code, capability_code, level_no in MAPPINGS:
                row = one_row(
                    central_cur,
                    """
                    select id::text, code
                      from catalog.category_node
                     where code=%s and level=%s and active=true
                    """,
                    (catalog_code, level_no),
                    f"active catalog node code={catalog_code} level={level_no}",
                )
                resolved.append((row[0], row[1], capability_code, level_no))

        with tenant:
            with tenant.cursor() as tenant_cur:
                for catalog_id, catalog_code, capability_code, level_no in resolved:
                    capability_row = one_row(
                        tenant_cur,
                        "select id::text from gis.capability where code=%s and active=true",
                        (capability_code,),
                        f"active GIS capability code={capability_code}",
                    )
                    tenant_cur.execute(
                        """
                        insert into gis.scope_binding(
                            id, catalog_level, catalog_item_id, catalog_code_cache,
                            catalog_name_cache, capability_id, active, priority, note
                        )
                        values (
                            gen_random_uuid(), %s, %s::uuid, %s, NULL,
                            %s::uuid, true, 100,
                            'Synced from canonical central catalog code in development runtime.'
                        )
                        on conflict (catalog_level, catalog_item_id, capability_id)
                        do update set
                            catalog_code_cache=excluded.catalog_code_cache,
                            active=true,
                            priority=excluded.priority,
                            note=excluded.note,
                            updated_at=now()
                        """,
                        (level_no, catalog_id, catalog_code, capability_row[0]),
                    )

                # Synthetic matrix bindings remain available until its scope rows
                # are reconciled to real L2/L3 catalog identities. Do not disable
                # them here or the current development matrix would disappear.

        print(f"central_db={central_name} tenant_db={tenant_name}")
        for catalog_id, catalog_code, capability_code, level_no in resolved:
            print(
                f"binding level={level_no} catalog_code={catalog_code} "
                f"catalog_id={catalog_id} capability={capability_code} status=OK"
            )
        print("RESULT real_catalog_gis_scope_bindings=OK")
        return 0
    finally:
        central.close()
        tenant.close()


if __name__ == "__main__":
    sys.exit(main())
