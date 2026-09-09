from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path


PROJECT_ID = "98d5b8f2-3940-49f7-801d-83c7dbeff99b"
PROJECT_CODE = "C26059"
GROUP_CODE = "cheonan"
DB_ALIAS = "cheonan_db"
PROFILE_CODE = "GEOFLOW_BASE_V1"
PROFILE_NAME = "GeoFlow GIS 공통 기본 v1"
CONFIRMATION = "ACTIVATE_C26059_GIS"
LOCK_KEY = "geoflow:gis:c26059:foundation:v1"

SOURCE_HASHES = {
    "gis-schema-foundation.sql": "d96f9602c4a231620de82d3bd105a9f86d0db250b747b5e48aeafd61be5b3494",
    "gis-initial-feature-tables-v0.1.sql": "e219fc34e233222e796def0eeb64d8a954acf2540aa2e29048cec1689955f62f",
    "gis-metadata-seed-v0.1.sql": "ffe987699a7fced99136581b35d2d9d1e6fea060f84e8cc03ce5ff308957e11c",
    "gis-scope-capability-v0.1.sql": "5511fe9947c2193a45bb0b28c6343e727a6bbac803a1f4cf1ff987854a7c4849",
    "gis-sync-revision-v1.sql": "f1e05fdee033505d3a0382720c0fde3c11dfb0726e05301a8716a1374b7a4765",
}

FEATURE_TABLES = (
    "wtl_etc_ps", "wtl_fire_ps", "wtl_flow_ps", "wtl_manh_ps",
    "wtl_pipe_lm", "wtl_pipe_ps", "wtl_plan_lm", "wtl_sply_ls",
    "wtl_valv_ps", "swl_conn_ls", "swl_etc_ps", "swl_manh_ps",
    "swl_pipe_as", "swl_pipe_lm", "swl_pipe_ps", "swl_side_ls",
    "swl_spot_ps",
)
GIS_RELATIONS = (
    "meta_feature_type", "meta_field_def", "ref_code_group", "ref_code_value",
    "profile", "profile_feature", "profile_field", "survey", "survey_link",
    "doro", "import_batch", "capability", "capability_feature",
    "scope_binding", "project_profile", *FEATURE_TABLES, "project_sync_state",
    "changeset_receipt", "feature_change_log",
)


def _text(value) -> str:
    return str(value or "").strip()


def _scalar(cursor, statement: str, params=None):
    cursor.execute(statement, params or [])
    row = cursor.fetchone()
    return row[0] if row else None


def _load_sources(source_dir: Path) -> dict[str, str]:
    sources = {}
    for name, expected_hash in SOURCE_HASHES.items():
        path = source_dir / name
        raw = path.read_bytes()
        actual_hash = hashlib.sha256(raw).hexdigest()
        if actual_hash != expected_hash:
            raise RuntimeError(f"reviewed GIS SQL hash mismatch: {name}")
        sources[name] = raw.decode("utf-8")
    return sources


def _production_body(source: str) -> str:
    """Remove only the reviewed file's outer transaction and first dev guard."""
    lines = source.replace("\r\n", "\n").splitlines()
    lines = [line for line in lines if line.strip() not in {"BEGIN;", "COMMIT;", "\\encoding UTF8"}]
    start = next((i for i, line in enumerate(lines) if line.strip() == "DO $$"), None)
    if start is None:
        raise RuntimeError("reviewed GIS SQL guard was not found")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].strip() == "$$;"), None)
    if end is None:
        raise RuntimeError("reviewed GIS SQL guard terminator was not found")
    return "\n".join(lines[:start] + lines[end + 1 :]).strip() + "\n"


def _prepared_sources(source_dir: Path) -> list[str]:
    sources = _load_sources(source_dir)
    prepared = []
    for name in SOURCE_HASHES:
        body = _production_body(sources[name])
        if name == "gis-initial-feature-tables-v0.1.sql":
            body = body.replace(
                "        EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON gis.%I(ftr_idn)', t || '_ftr_idn_idx', t);\n",
                "",
            )
        if name == "gis-metadata-seed-v0.1.sql":
            body = body.replace("GEOFLOW_DEV_BASE", PROFILE_CODE)
            body = body.replace("GeoFlow GIS 개발 기본", PROFILE_NAME)
            body = body.replace("Base development profile", "Base production profile")
            body = body.replace(
                "Development profile containing common + initial WTL/SWL feature types. Not a municipal delivery profile.",
                "Production-neutral profile containing common + initial WTL/SWL feature types; project capability limits visible layers.",
            )
            drop_start = body.find("DO $$\nDECLARE\n    t text;")
            drop_end = body.find("$$;", drop_start)
            if drop_start < 0 or drop_end < 0 or "DROP INDEX IF EXISTS" not in body[drop_start:drop_end]:
                raise RuntimeError("reviewed legacy-index cleanup shape changed")
            body = body[:drop_start] + "-- No legacy ftr_idn indexes are created in this activation.\n" + body[drop_end + 3 :]
        if name == "gis-sync-revision-v1.sql":
            seed = """-- Seed state rows for existing projects without advancing revisions.
INSERT INTO gis.project_sync_state(project_id, current_revision, snapshot_revision)
SELECT p.id, 0, 0
FROM prj.projects p
ON CONFLICT (project_id) DO NOTHING;"""
            if body.count(seed) != 1:
                raise RuntimeError("reviewed sync-state seed shape changed")
            body = body.replace(seed, "-- Project-specific sync state is seeded by the activation script.")
        prepared.append(body)
    return prepared


def _central_context():
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
                .select_related("group")
                .filter(group__code=GROUP_CODE, db_alias=DB_ALIAS)
            )
            cursor.execute(
                """SELECT id::text, name
                     FROM catalog.category_node
                    WHERE code='WATER' AND level=2 AND active
                    ORDER BY id"""
            )
            water_rows = cursor.fetchall()
    if len(rows) != 1:
        raise RuntimeError("target tenant configuration must resolve exactly once")
    row = rows[0]
    if _text(row.group.status).lower() != "active":
        raise RuntimeError("target tenant group is not active")
    if len(water_rows) != 1:
        raise RuntimeError("active level-2 WATER catalog entry must resolve exactly once")
    return row, water_rows[0]


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
        raise RuntimeError("target tenant database password is empty")
    connection = psycopg2.connect(
        dbname=row.db_name,
        user=row.db_user,
        password=password,
        host=row.db_host,
        port=row.db_port,
        sslmode="require",
        connect_timeout=10,
        application_name="geoflow_gis_c26059_activation",
    )
    connection.autocommit = False
    return connection


def _assert_preconditions(cursor, water_catalog_id: str) -> tuple[int, int]:
    cursor.execute("SET LOCAL lock_timeout = '5s'")
    cursor.execute("SET LOCAL statement_timeout = '120s'")
    cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [LOCK_KEY])
    if not _scalar(cursor, "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='postgis')"):
        raise RuntimeError("PostGIS extension is not installed; extension creation was not authorized")
    for relation in ("prj.projects", "prj.scope_item", "ctr.contracts", "hr.employee_profile", "ops.settings_nodes"):
        if not _scalar(cursor, "SELECT to_regclass(%s) IS NOT NULL", [relation]):
            raise RuntimeError(f"tenant foundation relation is missing: {relation}")
    cursor.execute(
        "SELECT code, status FROM prj.projects WHERE id=%s::uuid",
        [PROJECT_ID],
    )
    rows = cursor.fetchall()
    if rows != [(PROJECT_CODE, "active")]:
        raise RuntimeError("target project identity/status does not match the approved project")
    if _scalar(cursor, "SELECT count(*) FROM prj.scope_item WHERE project_id=%s::uuid AND lv2_id=%s::uuid", [PROJECT_ID, water_catalog_id]) < 1:
        raise RuntimeError("target project does not contain the approved WATER business scope")
    if _scalar(cursor, "SELECT to_regnamespace('gis') IS NOT NULL"):
        raise RuntimeError("gis schema already exists; one-time empty-tenant activation stopped")
    project_count = _scalar(cursor, "SELECT count(*) FROM prj.projects")
    scope_count = _scalar(cursor, "SELECT count(*) FROM prj.scope_item")
    return int(project_count), int(scope_count)


def _seed_project_activation(cursor, water_catalog_id: str, water_catalog_name: str) -> None:
    cursor.execute(
        """INSERT INTO gis.scope_binding(
                 id, catalog_level, catalog_item_id, catalog_code_cache,
                 catalog_name_cache, capability_id, active, priority, note)
             SELECT gen_random_uuid(), 2, %s::uuid, 'WATER', %s, c.id, true, 100,
                    'C26059 approved production GIS activation'
               FROM gis.capability c
              WHERE c.code='WATER' AND c.active""",
        [water_catalog_id, water_catalog_name],
    )
    if cursor.rowcount != 1:
        raise RuntimeError("WATER scope binding was not created exactly once")
    cursor.execute(
        """INSERT INTO gis.project_profile(project_id, profile_id, status, auto_assigned)
             SELECT %s::uuid, p.id, 'active', false
               FROM gis.profile p
              WHERE p.code=%s AND p.active""",
        [PROJECT_ID, PROFILE_CODE],
    )
    if cursor.rowcount != 1:
        raise RuntimeError("project profile was not assigned exactly once")
    cursor.execute(
        """INSERT INTO gis.project_sync_state(project_id, current_revision, snapshot_revision)
             VALUES (%s::uuid, 0, 0)""",
        [PROJECT_ID],
    )


def _validate(cursor, water_catalog_id: str, before_counts: tuple[int, int]) -> None:
    relation_count = sum(
        bool(_scalar(cursor, "SELECT to_regclass(%s) IS NOT NULL", [f"gis.{name}"]))
        for name in GIS_RELATIONS
    )
    if relation_count != len(GIS_RELATIONS):
        raise RuntimeError(f"GIS relation validation failed: {relation_count}/{len(GIS_RELATIONS)}")
    if _scalar(cursor, "SELECT count(*) FROM gis.meta_feature_type WHERE active") != 19:
        raise RuntimeError("expected exactly 19 active feature types")
    if _scalar(cursor, "SELECT count(*) FROM gis.profile WHERE code=%s AND active", [PROFILE_CODE]) != 1:
        raise RuntimeError("production-neutral profile validation failed")
    if _scalar(cursor, """SELECT count(*) FROM gis.profile_feature pf JOIN gis.profile p ON p.id=pf.profile_id
                             WHERE p.code=%s AND pf.enabled""", [PROFILE_CODE]) != 19:
        raise RuntimeError("profile feature count is not 19")
    if _scalar(cursor, "SELECT count(*) FROM gis.meta_field_def") < 19:
        raise RuntimeError("field metadata was not populated")
    cursor.execute(
        """SELECT count(DISTINCT c.id), min(c.code)
             FROM prj.scope_item s
             JOIN gis.scope_binding b ON b.active AND b.catalog_level=2 AND b.catalog_item_id=s.lv2_id
             JOIN gis.capability c ON c.id=b.capability_id AND c.active
            WHERE s.project_id=%s::uuid""",
        [PROJECT_ID],
    )
    if cursor.fetchone() != (1, "WATER"):
        raise RuntimeError("project capability must resolve to WATER only")
    cursor.execute(
        """SELECT count(DISTINCT ft.id),
                  count(DISTINCT ft.id) FILTER (WHERE ft.domain_code='COMMON'),
                  count(DISTINCT ft.id) FILTER (WHERE ft.domain_code='WTL'),
                  count(DISTINCT ft.id) FILTER (WHERE ft.domain_code='SWL')
             FROM prj.scope_item s
             JOIN gis.scope_binding b ON b.active AND b.catalog_level=2 AND b.catalog_item_id=s.lv2_id
             JOIN gis.capability c ON c.id=b.capability_id AND c.active
             JOIN gis.capability_feature cf ON cf.capability_id=c.id AND cf.enabled
             JOIN gis.project_profile pp ON pp.project_id=s.project_id AND pp.status='active'
             JOIN gis.profile p ON p.id=pp.profile_id AND p.active
             JOIN gis.profile_feature pf ON pf.profile_id=p.id AND pf.enabled AND pf.feature_type_id=cf.feature_type_id
             JOIN gis.meta_feature_type ft ON ft.id=cf.feature_type_id AND ft.active
            WHERE s.project_id=%s::uuid""",
        [PROJECT_ID],
    )
    if cursor.fetchone() != (11, 2, 9, 0):
        raise RuntimeError("approved project layer plan must be 11 layers: COMMON=2, WTL=9, SWL=0")
    if _scalar(cursor, "SELECT count(*) FROM gis.scope_binding WHERE catalog_level=2 AND catalog_item_id=%s::uuid AND active", [water_catalog_id]) != 1:
        raise RuntimeError("WATER scope binding validation failed")
    after_counts = (
        int(_scalar(cursor, "SELECT count(*) FROM prj.projects")),
        int(_scalar(cursor, "SELECT count(*) FROM prj.scope_item")),
    )
    if after_counts != before_counts:
        raise RuntimeError("business project/scope row counts changed")


def _run_once(connection, statements: list[str], water_catalog: tuple[str, str], *, commit: bool) -> None:
    try:
        with connection.cursor() as cursor:
            before_counts = _assert_preconditions(cursor, water_catalog[0])
            for statement in statements:
                cursor.execute(statement)
            _seed_project_activation(cursor, water_catalog[0], water_catalog[1])
            _validate(cursor, water_catalog[0], before_counts)
        if commit:
            connection.commit()
            print("gis_c26059_activation_commit=complete")
        else:
            connection.rollback()
            print("gis_c26059_activation_rehearsal=rolled_back")
    except Exception:
        connection.rollback()
        raise


def activate(source_dir: Path, confirmation: str) -> int:
    if confirmation != CONFIRMATION:
        raise RuntimeError("exact activation confirmation is required")
    statements = _prepared_sources(source_dir)
    row, water_catalog = _central_context()
    connection = _connect_tenant(row)
    try:
        _run_once(connection, statements, water_catalog, commit=False)
        _run_once(connection, statements, water_catalog, commit=True)
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL TRANSACTION READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = '30s'")
            _validate(cursor, water_catalog[0], (
                int(_scalar(cursor, "SELECT count(*) FROM prj.projects")),
                int(_scalar(cursor, "SELECT count(*) FROM prj.scope_item")),
            ))
        connection.rollback()
        print("gis_c26059_activation_group=cheonan")
        print("gis_c26059_activation_db_alias=cheonan_db")
        print("gis_c26059_activation_project=C26059")
        print("gis_c26059_activation_layers=11")
        print("gis_c26059_activation_domains=COMMON:2,WTL:9,SWL:0")
        print("RESULT gis_c26059_activation=SUCCESS")
        return 0
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--confirm", required=True)
    args = parser.parse_args()
    return activate(args.source_dir, args.confirm)


if __name__ == "__main__":
    raise SystemExit(main())
