from __future__ import annotations

import argparse
import os


CATALOG_CAPABILITY_MAPPINGS = (
    ("WATER", "WATER", 2),
    ("SEWERAGE", "SEWER", 2),
)
LOCK_KEY_PREFIX = "geoflow:gis:catalog-capability-bindings:v1"
EXPECTED_LAYER_COUNTS = {
    "WATER": (11, 2, 9, 0),
    "SEWER": (10, 2, 0, 8),
}


def _text(value) -> str:
    return str(value or "").strip()


def _one(rows, label: str):
    rows = list(rows)
    if len(rows) != 1:
        raise RuntimeError(f"{label} must resolve exactly once; found={len(rows)}")
    return rows[0]


def _central_context(group_code: str, db_alias: str):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geoflow_project.settings")
    import django
    from django.db import connections, transaction

    django.setup()
    from control.models import GroupDBConfig

    with transaction.atomic(using="default"):
        with connections["default"].cursor() as cursor:
            cursor.execute("SET LOCAL TRANSACTION READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = '15s'")
            configs = list(
                GroupDBConfig.objects.using("default")
                .select_related("group")
                .filter(group__code=group_code, db_alias=db_alias)
            )
            catalog_rows = []
            for catalog_code, capability_code, level_no in CATALOG_CAPABILITY_MAPPINGS:
                cursor.execute(
                    """
                    SELECT id::text, code, name
                      FROM catalog.category_node
                     WHERE code=%s AND level=%s AND active
                     ORDER BY id
                    """,
                    [catalog_code, level_no],
                )
                row = _one(
                    cursor.fetchall(),
                    f"active Catalog node code={catalog_code} level={level_no}",
                )
                catalog_rows.append((*row, capability_code, level_no))

    config = _one(configs, "target tenant database configuration")
    if _text(config.group.status).lower() != "active":
        raise RuntimeError("target tenant group is not active")
    return config, catalog_rows


def _connect_tenant(config):
    import psycopg2
    from control.services.tenant_db_secret_resolver import (
        is_tenant_db_secret_reference,
        resolve_tenant_db_password,
    )

    raw_password = _text(config.db_password)
    password = (
        resolve_tenant_db_password(raw_password)
        if is_tenant_db_secret_reference(raw_password)
        else raw_password
    )
    if not password:
        raise RuntimeError("target tenant database password is empty")
    connection = psycopg2.connect(
        dbname=config.db_name,
        user=config.db_user,
        password=password,
        host=config.db_host,
        port=config.db_port,
        sslmode="require",
        connect_timeout=10,
        application_name="geoflow_gis_catalog_binding_sync",
    )
    connection.autocommit = False
    return connection


def _apply_once(connection, catalog_rows, *, group_code: str, db_alias: str, commit: bool):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '5s'")
            cursor.execute("SET LOCAL statement_timeout = '30s'")
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                [f"{LOCK_KEY_PREFIX}:{group_code}:{db_alias}"],
            )
            cursor.execute(
                """
                SELECT current_database(),
                       to_regclass('gis.scope_binding'),
                       to_regclass('gis.capability'),
                       to_regclass('gis.capability_feature'),
                       to_regclass('gis.profile'),
                       to_regclass('gis.profile_feature'),
                       to_regclass('prj.scope_item')
                """
            )
            readiness = cursor.fetchone()
            if not readiness or any(value is None for value in readiness[1:]):
                raise RuntimeError("target tenant GIS foundation is incomplete")

            cursor.execute(
                "SELECT count(*) FROM gis.profile WHERE code='GEOFLOW_BASE_V1' AND active"
            )
            if cursor.fetchone()[0] != 1:
                raise RuntimeError("active production GIS base profile must resolve exactly once")

            cursor.execute(
                """
                SELECT c.code,
                       count(DISTINCT ft.id),
                       count(DISTINCT ft.id) FILTER (WHERE ft.domain_code='COMMON'),
                       count(DISTINCT ft.id) FILTER (WHERE ft.domain_code='WTL'),
                       count(DISTINCT ft.id) FILTER (WHERE ft.domain_code='SWL')
                  FROM gis.capability c
                  JOIN gis.capability_feature cf
                    ON cf.capability_id=c.id AND cf.enabled
                  JOIN gis.profile p
                    ON p.code='GEOFLOW_BASE_V1' AND p.active
                  JOIN gis.profile_feature pf
                    ON pf.profile_id=p.id
                   AND pf.feature_type_id=cf.feature_type_id
                   AND pf.enabled
                  JOIN gis.meta_feature_type ft
                    ON ft.id=cf.feature_type_id AND ft.active
                 WHERE c.active AND c.code=ANY(%s::text[])
                 GROUP BY c.code
                 ORDER BY c.code
                """,
                [[row[3] for row in catalog_rows]],
            )
            actual_layer_counts = {
                row[0]: tuple(int(value) for value in row[1:])
                for row in cursor.fetchall()
            }
            if actual_layer_counts != EXPECTED_LAYER_COUNTS:
                raise RuntimeError(
                    "production profile capability layer counts are not the reviewed 11/10 plan"
                )

            for catalog_id, catalog_code, catalog_name, capability_code, level_no in catalog_rows:
                cursor.execute(
                    "SELECT id::text FROM gis.capability WHERE code=%s AND active ORDER BY id",
                    [capability_code],
                )
                capability_id = _one(
                    cursor.fetchall(),
                    f"active GIS capability code={capability_code}",
                )[0]
                cursor.execute(
                    """
                    INSERT INTO gis.scope_binding(
                        id, catalog_level, catalog_item_id, catalog_code_cache,
                        catalog_name_cache, capability_id, active, priority, note
                    )
                    VALUES (
                        gen_random_uuid(), %s, %s::uuid, %s, %s,
                        %s::uuid, true, 100,
                        'Synced from canonical central Catalog for automatic GIS registration.'
                    )
                    ON CONFLICT (catalog_level, catalog_item_id, capability_id)
                    DO UPDATE SET
                        catalog_code_cache=excluded.catalog_code_cache,
                        catalog_name_cache=excluded.catalog_name_cache,
                        active=true,
                        priority=excluded.priority,
                        note=excluded.note,
                        updated_at=now()
                    """,
                    [level_no, catalog_id, catalog_code, catalog_name, capability_id],
                )

            expected_ids = [row[0] for row in catalog_rows]
            cursor.execute(
                """
                SELECT count(DISTINCT b.catalog_item_id)
                  FROM gis.scope_binding b
                  JOIN gis.capability c ON c.id=b.capability_id AND c.active
                 WHERE b.active
                   AND b.catalog_level=2
                   AND b.catalog_item_id=ANY(%s::uuid[])
                   AND c.code=ANY(%s::text[])
                """,
                [expected_ids, [row[3] for row in catalog_rows]],
            )
            if cursor.fetchone()[0] != len(CATALOG_CAPABILITY_MAPPINGS):
                raise RuntimeError("Catalog capability binding validation failed")

        if commit:
            connection.commit()
        else:
            connection.rollback()
    except Exception:
        connection.rollback()
        raise


def sync(group_code: str, db_alias: str, confirmation: str) -> int:
    expected_confirmation = f"SYNC_GIS_CATALOG_BINDINGS:{group_code}:{db_alias}"
    if confirmation != expected_confirmation:
        raise RuntimeError(f"exact confirmation is required: {expected_confirmation}")
    config, catalog_rows = _central_context(group_code, db_alias)
    connection = _connect_tenant(config)
    try:
        _apply_once(
            connection,
            catalog_rows,
            group_code=group_code,
            db_alias=db_alias,
            commit=False,
        )
        _apply_once(
            connection,
            catalog_rows,
            group_code=group_code,
            db_alias=db_alias,
            commit=True,
        )
    finally:
        connection.close()

    print(f"group_code={group_code} db_alias={db_alias}")
    print("catalog_capability_bindings=WATER:WATER,SEWERAGE:SEWER")
    print("RESULT gis_catalog_capability_binding_sync=SUCCESS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Synchronize canonical Catalog L2 domains to tenant GIS capabilities."
    )
    parser.add_argument("--group-code", required=True)
    parser.add_argument("--db-alias", required=True)
    parser.add_argument("--confirm", required=True)
    args = parser.parse_args()
    return sync(_text(args.group_code), _text(args.db_alias), _text(args.confirm))


if __name__ == "__main__":
    raise SystemExit(main())
