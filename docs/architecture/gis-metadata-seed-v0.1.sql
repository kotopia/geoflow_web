-- GeoFlow GIS metadata/profile seed v0.1
-- DEVELOPMENT / PILOT ONLY.
-- Run only after gis-schema-foundation.sql and gis-initial-feature-tables-v0.1.sql.

BEGIN;

DO $$
DECLARE
    db_name text := current_database();
BEGIN
    IF db_name !~* '(dev|test)' THEN
        RAISE EXCEPTION 'Safety stop: GIS metadata seed may run only in a dev/test database. Current DB=%', db_name;
    END IF;
    IF to_regclass('gis.meta_feature_type') IS NULL OR to_regclass('gis.meta_field_def') IS NULL THEN
        RAISE EXCEPTION 'GIS metadata foundation tables are missing.';
    END IF;
END
$$;

-- Common layers are physical GIS layers too, so register them alongside WTL/SWL.
WITH seed(standard_name, physical_name, label, domain_code, geometry_kind, feature_role, scope_type, sort_order) AS (
    VALUES
      ('DORO','doro','도로 기준','COMMON','LINE','SURVEY_REFERENCE','PROJECT',1),
      ('SURVEY','survey','공통 측량','COMMON','POINT','SURVEY_OBSERVATION','PROJECT',2)
)
INSERT INTO gis.meta_feature_type(
    id, standard_name, physical_name, label, domain_code, geometry_kind,
    feature_role, scope_type, active, sort_order
)
SELECT gen_random_uuid(), standard_name, physical_name, label, domain_code, geometry_kind,
       feature_role, scope_type, true, sort_order
FROM seed
ON CONFLICT (standard_name) DO UPDATE SET
    physical_name = EXCLUDED.physical_name,
    label = EXCLUDED.label,
    domain_code = EXCLUDED.domain_code,
    geometry_kind = EXCLUDED.geometry_kind,
    feature_role = EXCLUDED.feature_role,
    scope_type = EXCLUDED.scope_type,
    active = true,
    sort_order = EXCLUDED.sort_order,
    updated_at = now();

-- GeoFlow internal identity is UUID id. ftr_idn is retained only as an optional
-- external/legacy/authority identifier for import/export reconciliation.
-- It is intentionally not an internal PK/FK and is not indexed by default.
DO $$
DECLARE
    t text;
    tables text[] := ARRAY[
        'wtl_etc_ps','wtl_fire_ps','wtl_flow_ps','wtl_manh_ps','wtl_pipe_lm','wtl_pipe_ps','wtl_plan_lm','wtl_sply_ls','wtl_valv_ps',
        'swl_conn_ls','swl_etc_ps','swl_manh_ps','swl_pipe_as','swl_pipe_lm','swl_pipe_ps','swl_side_ls','swl_spot_ps'
    ];
BEGIN
    FOREACH t IN ARRAY tables LOOP
        EXECUTE format('DROP INDEX IF EXISTS gis.%I', t || '_ftr_idn_idx');
    END LOOP;
END
$$;

-- Seed field metadata from the physical database itself. This makes the DB
-- schema the concrete source for physical columns and prevents hand-maintained
-- metadata from drifting away from the actual table shape.
WITH physical_fields AS (
    SELECT
        ft.id AS feature_type_id,
        ft.standard_name AS feature_standard_name,
        ft.physical_name AS table_name,
        a.attname AS physical_name,
        upper(a.attname) AS standard_name,
        a.attnum AS sort_order,
        a.attnotnull AS required_default,
        pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type
    FROM gis.meta_feature_type ft
    JOIN pg_namespace ns ON ns.nspname = 'gis'
    JOIN pg_class c ON c.relnamespace = ns.oid AND c.relname = ft.physical_name AND c.relkind IN ('r','p')
    JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
    WHERE ft.active
      AND ft.domain_code IN ('COMMON','WTL','SWL')
)
INSERT INTO gis.meta_field_def(
    id, feature_type_id, standard_name, physical_name, label, data_type,
    unit, code_group_key, widget_type, required_default, core_field,
    sort_order, description
)
SELECT
    gen_random_uuid(),
    pf.feature_type_id,
    pf.standard_name,
    pf.physical_name,
    CASE pf.physical_name
        WHEN 'id' THEN 'GeoFlow UUID'
        WHEN 'project_id' THEN '프로젝트'
        WHEN 'ftr_cde' THEN '시설물 코드'
        WHEN 'ftr_idn' THEN '외부 시설물 ID'
        WHEN 'geom' THEN '공간정보'
        WHEN 'created_at' THEN '작성일시'
        WHEN 'updated_at' THEN '수정일시'
        WHEN 'created_by' THEN '작성자'
        WHEN 'updated_by' THEN '수정자'
        WHEN 'description' THEN '비고'
        ELSE upper(pf.physical_name)
    END,
    pf.data_type,
    NULL,
    NULL,
    CASE
        WHEN pf.physical_name = 'geom' THEN 'map'
        WHEN pf.data_type = 'date' THEN 'date'
        WHEN pf.data_type LIKE 'timestamp%' THEN 'datetime'
        WHEN pf.data_type IN ('integer','bigint','smallint','real','double precision') OR pf.data_type LIKE 'numeric%' THEN 'number'
        WHEN pf.data_type = 'jsonb' THEN 'json'
        ELSE 'text'
    END,
    pf.required_default,
    (pf.physical_name IN ('id','project_id','ftr_cde','geom','created_at','updated_at')),
    pf.sort_order,
    CASE pf.physical_name
        WHEN 'id' THEN 'GeoFlow authoritative internal object identifier. UUID; use for internal relations.'
        WHEN 'project_id' THEN 'GeoFlow project UUID reference.'
        WHEN 'ftr_idn' THEN 'Optional external/legacy/authority identifier. Do not use as GeoFlow internal PK/FK.'
        WHEN 'geom' THEN 'PostGIS authoritative geometry.'
        WHEN 'ext_data' THEN 'Limited sparse/source-specific extension values; promote repeated values to physical columns.'
        ELSE NULL
    END
FROM physical_fields pf
ON CONFLICT (feature_type_id, physical_name) DO UPDATE SET
    standard_name = EXCLUDED.standard_name,
    label = EXCLUDED.label,
    data_type = EXCLUDED.data_type,
    widget_type = EXCLUDED.widget_type,
    required_default = EXCLUDED.required_default,
    core_field = EXCLUDED.core_field,
    sort_order = EXCLUDED.sort_order,
    description = EXCLUDED.description;

-- Base development profile. This is a neutral GeoFlow pilot profile, not a
-- municipality delivery profile. Municipal profiles are added separately.
INSERT INTO gis.profile(id, code, name, municipality, version, active, description)
VALUES (
    gen_random_uuid(), 'GEOFLOW_DEV_BASE', 'GeoFlow GIS 개발 기본', NULL, '0.1', true,
    'Development profile containing common + initial WTL/SWL feature types. Not a municipal delivery profile.'
)
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    version = EXCLUDED.version,
    active = true,
    description = EXCLUDED.description,
    updated_at = now();

INSERT INTO gis.profile_feature(id, profile_id, feature_type_id, enabled, required, sort_order)
SELECT gen_random_uuid(), p.id, ft.id, true, false, ft.sort_order
FROM gis.profile p
JOIN gis.meta_feature_type ft ON ft.active AND ft.domain_code IN ('COMMON','WTL','SWL')
WHERE p.code = 'GEOFLOW_DEV_BASE'
ON CONFLICT (profile_id, feature_type_id) DO UPDATE SET
    enabled = true,
    sort_order = EXCLUDED.sort_order;

INSERT INTO gis.profile_field(id, profile_id, field_def_id, enabled, required, editable, visible, sort_order)
SELECT
    gen_random_uuid(), p.id, fd.id, true,
    CASE WHEN fd.physical_name IN ('id','created_at','updated_at') THEN false ELSE fd.required_default END,
    CASE WHEN fd.physical_name IN ('id','created_at','updated_at') THEN false ELSE true END,
    true,
    fd.sort_order
FROM gis.profile p
JOIN gis.meta_feature_type ft ON ft.active AND ft.domain_code IN ('COMMON','WTL','SWL')
JOIN gis.meta_field_def fd ON fd.feature_type_id = ft.id
WHERE p.code = 'GEOFLOW_DEV_BASE'
ON CONFLICT (profile_id, field_def_id) DO UPDATE SET
    enabled = true,
    required = EXCLUDED.required,
    editable = EXCLUDED.editable,
    visible = true,
    sort_order = EXCLUDED.sort_order;

COMMIT;
