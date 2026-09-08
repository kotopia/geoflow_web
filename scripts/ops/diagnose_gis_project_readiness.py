from __future__ import annotations

import argparse
import os
import uuid


TENANT_MARKERS = ("ctr.contracts", "prj.projects", "hr.employee_profile", "ops.settings_nodes")
GIS_RELATIONS = (
    "gis.meta_feature_type", "gis.meta_field_def", "gis.profile",
    "gis.profile_feature", "gis.profile_field", "gis.capability",
    "gis.capability_feature", "gis.scope_binding", "gis.project_profile",
    "gis.survey", "gis.survey_link", "gis.doro",
)
FEATURE_TABLES = tuple(
    f"gis.{name}"
    for name in (
        "wtl_etc_ps", "wtl_fire_ps", "wtl_flow_ps", "wtl_manh_ps",
        "wtl_pipe_lm", "wtl_pipe_ps", "wtl_plan_lm", "wtl_sply_ls",
        "wtl_valv_ps", "swl_conn_ls", "swl_etc_ps", "swl_manh_ps",
        "swl_pipe_as", "swl_pipe_lm", "swl_pipe_ps", "swl_side_ls",
        "swl_spot_ps",
    )
)


def _text(value) -> str:
    return str(value or "").strip()


def _relation_state(cursor, relations: tuple[str, ...]) -> dict[str, bool]:
    cursor.execute(
        "SELECT " + ", ".join(["to_regclass(%s) IS NOT NULL"] * len(relations)),
        list(relations),
    )
    return dict(zip(relations, map(bool, cursor.fetchone()), strict=True))


def _column_exists(cursor, schema: str, table: str, column: str) -> bool:
    cursor.execute(
        """SELECT EXISTS (
               SELECT 1
                 FROM information_schema.columns
                WHERE table_schema=%s AND table_name=%s AND column_name=%s
           )""",
        [schema, table, column],
    )
    return bool(cursor.fetchone()[0])


def _connect_tenant(row):
    import psycopg2
    from control.services.tenant_db_secret_resolver import (
        is_tenant_db_secret_reference,
        resolve_tenant_db_password,
    )

    raw_password = _text(row.db_password)
    password = (
        resolve_tenant_db_password(raw_password)
        if is_tenant_db_secret_reference(raw_password)
        else raw_password
    )
    if not password:
        raise RuntimeError("empty tenant database password")
    connection = psycopg2.connect(
        dbname=row.db_name, user=row.db_user, password=password,
        host=row.db_host, port=row.db_port, sslmode="require", connect_timeout=10,
    )
    connection.set_session(readonly=True, autocommit=False)
    return connection


def _catalog_values(connection, scope_rows: list[tuple]) -> dict[str, tuple[str, str]]:
    ids = {str(value) for row in scope_rows for value in row[1:4] if value is not None}
    if not ids:
        return {}
    values: dict[str, tuple[str, str]] = {}
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL TRANSACTION READ ONLY")
        cursor.execute("SET LOCAL statement_timeout = '15s'")
        for table in ("catalog.category_node", "catalog.category_facet_option"):
            cursor.execute(
                f"SELECT id::text, code, name FROM {table} WHERE id::text = ANY(%s)",
                [list(ids)],
            )
            values.update({key: (code, name) for key, code, name in cursor.fetchall()})
    return values


def inspect(project_id: uuid.UUID) -> int:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geoflow_project.settings")
    import django
    from django.db import connections, transaction

    django.setup()
    from control.models import GroupDBConfig

    with transaction.atomic(using="default"):
        with connections["default"].cursor() as cursor:
            cursor.execute("SET LOCAL TRANSACTION READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = '15s'")
            rows = list(
                GroupDBConfig.objects.using("default")
                .select_related("group").order_by("group_id")
            )

    active_rows = [row for row in rows if _text(row.group.status).lower() == "active"]
    matches: list[tuple] = []
    for row in active_rows:
        tenant = _connect_tenant(row)
        keep_open = False
        try:
            with tenant.cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = '15s'")
                markers = _relation_state(cursor, TENANT_MARKERS)
                if not any(markers.values()):
                    continue
                if not all(markers.values()):
                    raise RuntimeError(f"partial tenant schema for group={row.group.code}: {markers}")
                cursor.execute(
                    "SELECT id::text, code, name, status FROM prj.projects WHERE id=%s",
                    [str(project_id)],
                )
                projects = cursor.fetchall()
                if not projects:
                    continue
                scope_has_active = _column_exists(cursor, "prj", "scope_item", "active")
                scope_has_ord = _column_exists(cursor, "prj", "scope_item", "ord")
                active_select = "active" if scope_has_active else "TRUE AS active"
                order_clause = "ord, id" if scope_has_ord else "id"
                cursor.execute(
                    f"""SELECT id::text, lv2_id, lv3_id, lv4_id, {active_select}
                          FROM prj.scope_item
                         WHERE project_id=%s
                         ORDER BY {order_clause}""",
                    [str(project_id)],
                )
                matches.append(
                    (
                        row,
                        tenant,
                        projects[0],
                        cursor.fetchall(),
                        _relation_state(cursor, GIS_RELATIONS),
                        scope_has_active,
                    )
                )
                keep_open = True
        finally:
            if not keep_open:
                tenant.rollback()
                tenant.close()

    if len(matches) != 1:
        for _row, connection, _project, _scope, _gis, _scope_has_active in matches:
            connection.close()
        print(f"gis_project_readiness_match_count={len(matches)}")
        raise RuntimeError("project must resolve to exactly one active tenant database")

    row, tenant, project, scope_rows, gis_state, scope_has_active = matches[0]
    try:
        with transaction.atomic(using="default"):
            catalog = _catalog_values(connections["default"], scope_rows)

        print("gis_project_readiness_match_count=1")
        print(
            "gis_project "
            f"group_code={row.group.code} group_name={row.group.name} db_alias={row.db_alias} "
            f"project_code={project[1]} project_name={project[2]} status={project[3]}"
        )
        print(f"gis_project_scope_count={len(scope_rows)}")
        print(f"gis_project_scope_active_column={scope_has_active}")
        for _scope_id, lv2_id, lv3_id, lv4_id, active in scope_rows:
            parts = []
            for level, value in ((2, lv2_id), (3, lv3_id), (4, lv4_id)):
                if value is not None:
                    code, name = catalog.get(str(value), ("UNRESOLVED", "UNRESOLVED"))
                    parts.append(f"lv{level}={code}|{name}")
            print(f"gis_project_scope active={bool(active)} " + " ".join(parts))

        missing_relations = [name for name, exists in gis_state.items() if not exists]
        print(f"gis_project_missing_relations={','.join(missing_relations) or 'NONE'}")
        with tenant.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = '15s'")
            feature_state = _relation_state(cursor, FEATURE_TABLES)
            print(
                f"gis_project_feature_tables present={sum(feature_state.values())} "
                f"expected={len(FEATURE_TABLES)}"
            )
            if not missing_relations:
                active_filter = " AND s.active" if scope_has_active else ""
                cursor.execute(
                    f"""SELECT count(DISTINCT c.id),
                              COALESCE(string_agg(DISTINCT c.code, ',' ORDER BY c.code), '')
                         FROM prj.scope_item s
                         JOIN gis.scope_binding b ON b.active AND
                              ((b.catalog_level=2 AND b.catalog_item_id=s.lv2_id) OR
                               (b.catalog_level=3 AND b.catalog_item_id=s.lv3_id) OR
                               (b.catalog_level=4 AND b.catalog_item_id=s.lv4_id))
                         JOIN gis.capability c ON c.id=b.capability_id AND c.active
                        WHERE s.project_id=%s{active_filter}""",
                    [str(project_id)],
                )
                capability_count, capability_codes = cursor.fetchone()
                cursor.execute(
                    """SELECT count(*), COALESCE(string_agg(p.code, ',' ORDER BY p.code), '')
                         FROM gis.project_profile pp
                         JOIN gis.profile p ON p.id=pp.profile_id AND p.active
                        WHERE pp.project_id=%s AND pp.status='active'""",
                    [str(project_id)],
                )
                profile_count, profile_codes = cursor.fetchone()
                cursor.execute(
                    f"""SELECT count(DISTINCT ft.id)
                         FROM prj.scope_item s
                         JOIN gis.scope_binding b ON b.active AND
                              ((b.catalog_level=2 AND b.catalog_item_id=s.lv2_id) OR
                               (b.catalog_level=3 AND b.catalog_item_id=s.lv3_id) OR
                               (b.catalog_level=4 AND b.catalog_item_id=s.lv4_id))
                         JOIN gis.capability c ON c.id=b.capability_id AND c.active
                         JOIN gis.capability_feature cf ON cf.capability_id=c.id AND cf.enabled
                         JOIN gis.project_profile pp ON pp.project_id=s.project_id AND pp.status='active'
                         JOIN gis.profile p ON p.id=pp.profile_id AND p.active
                         JOIN gis.profile_feature pf ON pf.profile_id=p.id AND pf.enabled
                                                   AND pf.feature_type_id=cf.feature_type_id
                         JOIN gis.meta_feature_type ft ON ft.id=cf.feature_type_id AND ft.active
                        WHERE s.project_id=%s{active_filter}""",
                    [str(project_id)],
                )
                print(
                    f"gis_project_capabilities count={capability_count} "
                    f"codes={capability_codes or 'NONE'}"
                )
                print(
                    f"gis_project_profiles count={profile_count} codes={profile_codes or 'NONE'}"
                )
                print(f"gis_project_layer_plan_count={cursor.fetchone()[0]}")
        tenant.rollback()
        print("RESULT gis_project_readiness=READ_ONLY_COMPLETE")
        return 0
    finally:
        tenant.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", required=True, type=uuid.UUID)
    return inspect(parser.parse_args().project_id)


if __name__ == "__main__":
    raise SystemExit(main())
