-- GeoFlow GIS initial physical feature tables v0.1
-- DEVELOPMENT / PILOT ONLY.
-- Intended for geoflow_dev (or another explicitly named dev/test DB) after
-- docs/architecture/gis-schema-foundation.sql has been applied.
--
-- Design rules:
--   * PostgreSQL physical identifiers are lowercase/unquoted.
--   * Public/municipal logical names remain uppercase in metadata/export.
--   * EPSG:4326 is the current GeoFlow storage/pilot SRID; delivery/profile
--     transformations remain an export/materialization concern.
--   * Core/repeated/QGIS-QField fields are physical columns.
--   * Rare/temporary/source-specific values may remain in ext_data until
--     DB테이블-- + municipal definitions are fully mapped.
--   * This is additive pilot DDL; it must never be run on a production DB.

BEGIN;

DO $$
DECLARE
    db_name text := current_database();
BEGIN
    IF db_name !~* '(dev|test)' THEN
        RAISE EXCEPTION 'Safety stop: GIS pilot DDL may run only in a dev/test database. Current DB=%', db_name;
    END IF;
    IF to_regnamespace('gis') IS NULL THEN
        RAISE EXCEPTION 'gis schema is missing. Apply gis-schema-foundation.sql first.';
    END IF;
    IF to_regclass('prj.projects') IS NULL THEN
        RAISE EXCEPTION 'prj.projects is missing. geoflow_dev tenant bootstrap is incomplete.';
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- Shared physical-column contract
-- ---------------------------------------------------------------------------
-- Every project-scoped asset table has:
--   id, gid, project_id, ftr_cde, ftr_idn,
--   hjd_cde, bjd_cde, sht_num, mng_cde, ist_ymd,
--   source_name/source_key, description, ext_data,
--   created_by/updated_by, created_at/updated_at, geom.
--
-- project_id remains nullable during legacy import/reconciliation. New GeoFlow
-- creation workflows should require it at the service/form layer.

-- ---------------------------------------------------------------------------
-- WTL / water
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS gis.wtl_etc_ps (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    gid bigint,
    project_id uuid REFERENCES prj.projects(id),
    ftr_cde varchar(20), ftr_idn varchar(50),
    hjd_cde varchar(20), bjd_cde varchar(20), sht_num varchar(50), mng_cde varchar(20),
    ist_ymd date, cst_cde varchar(20), off_cde varchar(20),
    source_name text, source_key text, description text,
    ext_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by uuid, updated_by uuid,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    geom geometry(Point,4326)
);

CREATE TABLE IF NOT EXISTS gis.wtl_fire_ps (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    gid bigint,
    project_id uuid REFERENCES prj.projects(id),
    ftr_cde varchar(20), ftr_idn varchar(50),
    hjd_cde varchar(20), bjd_cde varchar(20), sht_num varchar(50), mng_cde varchar(20),
    ist_ymd date, cst_cde varchar(20), off_cde varchar(20),
    fire_dip numeric(10,2), fire_dep numeric(10,3),
    source_name text, source_key text, description text,
    ext_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by uuid, updated_by uuid,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    geom geometry(Point,4326)
);

CREATE TABLE IF NOT EXISTS gis.wtl_flow_ps (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    gid bigint,
    project_id uuid REFERENCES prj.projects(id),
    ftr_cde varchar(20), ftr_idn varchar(50),
    hjd_cde varchar(20), bjd_cde varchar(20), sht_num varchar(50), mng_cde varchar(20),
    ist_ymd date, cst_cde varchar(20), off_cde varchar(20),
    flow_dip numeric(10,2), flow_dep numeric(10,3),
    source_name text, source_key text, description text,
    ext_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by uuid, updated_by uuid,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    geom geometry(Point,4326)
);

CREATE TABLE IF NOT EXISTS gis.wtl_manh_ps (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    gid bigint,
    project_id uuid REFERENCES prj.projects(id),
    ftr_cde varchar(20), ftr_idn varchar(50),
    hjd_cde varchar(20), bjd_cde varchar(20), sht_num varchar(50), mng_cde varchar(20),
    ist_ymd date, cst_cde varchar(20), off_cde varchar(20),
    sbc_cde varchar(50),
    sbc_size numeric(10,2), sbc_size_h numeric(10,2), sbc_size_v numeric(10,2),
    topi numeric(10,3),
    dpg_std numeric(10,2), dpg_std_h numeric(10,2), dpg_std_v numeric(10,2), dpg_dep numeric(10,3),
    sys_chk varchar(10),
    source_name text, source_key text, description text,
    ext_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by uuid, updated_by uuid,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    geom geometry(Point,4326)
);

CREATE TABLE IF NOT EXISTS gis.wtl_pipe_lm (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    gid bigint,
    project_id uuid REFERENCES prj.projects(id),
    ftr_cde varchar(20), ftr_idn varchar(50),
    hjd_cde varchar(20), bjd_cde varchar(20), sht_num varchar(50), mng_cde varchar(20),
    ist_ymd date, cst_cde varchar(20), off_cde varchar(20),
    saa_cde varchar(50), mop_cde varchar(50), iqt_cde varchar(50), jht_cde varchar(50),
    pip_dip numeric(10,2), pip_len numeric(14,3),
    sys_chk varchar(10),
    source_name text, source_key text, description text,
    ext_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by uuid, updated_by uuid,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    geom geometry(LineString,4326)
);

CREATE TABLE IF NOT EXISTS gis.wtl_pipe_ps (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    gid bigint,
    project_id uuid REFERENCES prj.projects(id),
    ftr_cde varchar(20), ftr_idn varchar(50),
    hjd_cde varchar(20), bjd_cde varchar(20), sht_num varchar(50), mng_cde varchar(20),
    ist_ymd date, cst_cde varchar(20), off_cde varchar(20),
    mop_cde varchar(50), iqt_cde varchar(50),
    pip_dip numeric(10,2), pip_dep numeric(10,3), dep_dist numeric(10,3),
    sys_chk varchar(10),
    source_name text, source_key text, description text,
    ext_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by uuid, updated_by uuid,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    geom geometry(Point,4326)
);

CREATE TABLE IF NOT EXISTS gis.wtl_plan_lm (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    gid bigint,
    project_id uuid REFERENCES prj.projects(id),
    ftr_cde varchar(20), ftr_idn varchar(50),
    hjd_cde varchar(20), bjd_cde varchar(20), sht_num varchar(50), mng_cde varchar(20),
    source_name text, source_key text, description text,
    ext_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by uuid, updated_by uuid,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    geom geometry(LineString,4326)
);

CREATE TABLE IF NOT EXISTS gis.wtl_sply_ls (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    gid bigint,
    project_id uuid REFERENCES prj.projects(id),
    ftr_cde varchar(20), ftr_idn varchar(50),
    hjd_cde varchar(20), bjd_cde varchar(20), sht_num varchar(50), mng_cde varchar(20),
    ist_ymd date, cst_cde varchar(20), off_cde varchar(20),
    saa_cde varchar(50), mop_cde varchar(50), iqt_cde varchar(50), jht_cde varchar(50),
    pip_dip numeric(10,2), pip_len numeric(14,3),
    sys_chk varchar(10),
    source_name text, source_key text, description text,
    ext_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by uuid, updated_by uuid,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    geom geometry(LineString,4326)
);

CREATE TABLE IF NOT EXISTS gis.wtl_valv_ps (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    gid bigint,
    project_id uuid REFERENCES prj.projects(id),
    ftr_cde varchar(20), ftr_idn varchar(50),
    hjd_cde varchar(20), bjd_cde varchar(20), sht_num varchar(50), mng_cde varchar(20),
    ist_ymd date,
    val_mof varchar(200), val_mop varchar(200), val_dip numeric(10,2), val_dep numeric(10,3),
    sae_cde varchar(20), tro_cnt numeric(10,2), cro_cnt numeric(10,2), mth_cde varchar(20),
    val_for varchar(20), val_std varchar(100),
    val_std_h numeric(10,2), val_std_v numeric(10,2), val_std_d numeric(10,2),
    cst_cde varchar(20), off_cde varchar(20),
    sbc_cde varchar(50), sbc_size numeric(10,2), sbc_size_h numeric(10,2), sbc_size_v numeric(10,2),
    topi numeric(10,3), dpg_std numeric(10,2), dpg_std_h numeric(10,2), dpg_std_v numeric(10,2), dpg_dep numeric(10,3),
    sys_chk varchar(10),
    source_name text, source_key text, description text,
    ext_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by uuid, updated_by uuid,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    geom geometry(Point,4326)
);

-- ---------------------------------------------------------------------------
-- SWL / sewer
-- Initial physical shells use the shared municipal/GeoFlow core fields. Exact
-- sewer-specific columns are intentionally additive in the next mapping pass.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS gis.swl_conn_ls (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), gid bigint,
    project_id uuid REFERENCES prj.projects(id),
    ftr_cde varchar(20), ftr_idn varchar(50), hjd_cde varchar(20), bjd_cde varchar(20),
    sht_num varchar(50), mng_cde varchar(20), ist_ymd date, cst_cde varchar(20), off_cde varchar(20),
    pip_dip numeric(10,2), pip_dep numeric(10,3), pip_len numeric(14,3),
    source_name text, source_key text, description text, ext_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by uuid, updated_by uuid, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    geom geometry(LineString,4326)
);

CREATE TABLE IF NOT EXISTS gis.swl_etc_ps (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), gid bigint,
    project_id uuid REFERENCES prj.projects(id),
    ftr_cde varchar(20), ftr_idn varchar(50), hjd_cde varchar(20), bjd_cde varchar(20),
    sht_num varchar(50), mng_cde varchar(20), ist_ymd date, cst_cde varchar(20), off_cde varchar(20),
    source_name text, source_key text, description text, ext_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by uuid, updated_by uuid, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    geom geometry(Point,4326)
);

CREATE TABLE IF NOT EXISTS gis.swl_manh_ps (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), gid bigint,
    project_id uuid REFERENCES prj.projects(id),
    ftr_cde varchar(20), ftr_idn varchar(50), hjd_cde varchar(20), bjd_cde varchar(20),
    sht_num varchar(50), mng_cde varchar(20), ist_ymd date, cst_cde varchar(20), off_cde varchar(20),
    man_dip numeric(10,2), man_dep numeric(10,3), topi numeric(10,3),
    source_name text, source_key text, description text, ext_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by uuid, updated_by uuid, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    geom geometry(Point,4326)
);

CREATE TABLE IF NOT EXISTS gis.swl_pipe_as (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), gid bigint,
    project_id uuid REFERENCES prj.projects(id),
    ftr_cde varchar(20), ftr_idn varchar(50), hjd_cde varchar(20), bjd_cde varchar(20),
    sht_num varchar(50), mng_cde varchar(20), ist_ymd date, cst_cde varchar(20), off_cde varchar(20),
    pip_dip numeric(10,2), pip_dep numeric(10,3), pip_len numeric(14,3),
    source_name text, source_key text, description text, ext_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by uuid, updated_by uuid, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    geom geometry(LineString,4326)
);

CREATE TABLE IF NOT EXISTS gis.swl_pipe_lm (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), gid bigint,
    project_id uuid REFERENCES prj.projects(id),
    ftr_cde varchar(20), ftr_idn varchar(50), hjd_cde varchar(20), bjd_cde varchar(20),
    sht_num varchar(50), mng_cde varchar(20), ist_ymd date, cst_cde varchar(20), off_cde varchar(20),
    saa_cde varchar(50), mop_cde varchar(50), iqt_cde varchar(50), jht_cde varchar(50),
    pip_dip numeric(10,2), pip_dep numeric(10,3), pip_len numeric(14,3),
    source_name text, source_key text, description text, ext_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by uuid, updated_by uuid, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    geom geometry(LineString,4326)
);

CREATE TABLE IF NOT EXISTS gis.swl_pipe_ps (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), gid bigint,
    project_id uuid REFERENCES prj.projects(id),
    ftr_cde varchar(20), ftr_idn varchar(50), hjd_cde varchar(20), bjd_cde varchar(20),
    sht_num varchar(50), mng_cde varchar(20), ist_ymd date, cst_cde varchar(20), off_cde varchar(20),
    mop_cde varchar(50), iqt_cde varchar(50), pip_dip numeric(10,2), pip_dep numeric(10,3), dep_dist numeric(10,3),
    source_name text, source_key text, description text, ext_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by uuid, updated_by uuid, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    geom geometry(Point,4326)
);

CREATE TABLE IF NOT EXISTS gis.swl_side_ls (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), gid bigint,
    project_id uuid REFERENCES prj.projects(id),
    ftr_cde varchar(20), ftr_idn varchar(50), hjd_cde varchar(20), bjd_cde varchar(20),
    sht_num varchar(50), mng_cde varchar(20), ist_ymd date, cst_cde varchar(20), off_cde varchar(20),
    pip_dip numeric(10,2), pip_dep numeric(10,3), pip_len numeric(14,3),
    source_name text, source_key text, description text, ext_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by uuid, updated_by uuid, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    geom geometry(LineString,4326)
);

CREATE TABLE IF NOT EXISTS gis.swl_spot_ps (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), gid bigint,
    project_id uuid REFERENCES prj.projects(id),
    ftr_cde varchar(20), ftr_idn varchar(50), hjd_cde varchar(20), bjd_cde varchar(20),
    sht_num varchar(50), mng_cde varchar(20), ist_ymd date, cst_cde varchar(20), off_cde varchar(20),
    spot_dep numeric(10,3),
    source_name text, source_key text, description text, ext_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by uuid, updated_by uuid, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    geom geometry(Point,4326)
);

-- ---------------------------------------------------------------------------
-- Standard indexes for project filtering, external ID lookup and spatial load.
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    t text;
    tables text[] := ARRAY[
        'wtl_etc_ps','wtl_fire_ps','wtl_flow_ps','wtl_manh_ps','wtl_pipe_lm','wtl_pipe_ps','wtl_plan_lm','wtl_sply_ls','wtl_valv_ps',
        'swl_conn_ls','swl_etc_ps','swl_manh_ps','swl_pipe_as','swl_pipe_lm','swl_pipe_ps','swl_side_ls','swl_spot_ps'
    ];
BEGIN
    FOREACH t IN ARRAY tables LOOP
        EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON gis.%I(project_id)', t || '_project_idx', t);
        EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON gis.%I(ftr_idn)', t || '_ftr_idn_idx', t);
        EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON gis.%I USING gist(geom)', t || '_geom_gix', t);
    END LOOP;
END
$$;

-- Register the initial 17 physical feature types. Existing rows are updated in
-- place so rerunning in geoflow_dev remains idempotent.
WITH seed(standard_name, physical_name, label, domain_code, geometry_kind, sort_order) AS (
    VALUES
    ('WTL_ETC_PS','wtl_etc_ps','WTL_ETC_PS','WTL','POINT',10),
    ('WTL_FIRE_PS','wtl_fire_ps','WTL_FIRE_PS','WTL','POINT',20),
    ('WTL_FLOW_PS','wtl_flow_ps','WTL_FLOW_PS','WTL','POINT',30),
    ('WTL_MANH_PS','wtl_manh_ps','WTL_MANH_PS','WTL','POINT',40),
    ('WTL_PIPE_LM','wtl_pipe_lm','WTL_PIPE_LM','WTL','LINE',50),
    ('WTL_PIPE_PS','wtl_pipe_ps','WTL_PIPE_PS','WTL','POINT',60),
    ('WTL_PLAN_LM','wtl_plan_lm','WTL_PLAN_LM','WTL','LINE',70),
    ('WTL_SPLY_LS','wtl_sply_ls','WTL_SPLY_LS','WTL','LINE',80),
    ('WTL_VALV_PS','wtl_valv_ps','WTL_VALV_PS','WTL','POINT',90),
    ('SWL_CONN_LS','swl_conn_ls','SWL_CONN_LS','SWL','LINE',110),
    ('SWL_ETC_PS','swl_etc_ps','SWL_ETC_PS','SWL','POINT',120),
    ('SWL_MANH_PS','swl_manh_ps','SWL_MANH_PS','SWL','POINT',130),
    ('SWL_PIPE_AS','swl_pipe_as','SWL_PIPE_AS','SWL','LINE',140),
    ('SWL_PIPE_LM','swl_pipe_lm','SWL_PIPE_LM','SWL','LINE',150),
    ('SWL_PIPE_PS','swl_pipe_ps','SWL_PIPE_PS','SWL','POINT',160),
    ('SWL_SIDE_LS','swl_side_ls','SWL_SIDE_LS','SWL','LINE',170),
    ('SWL_SPOT_PS','swl_spot_ps','SWL_SPOT_PS','SWL','POINT',180)
)
INSERT INTO gis.meta_feature_type(
    id, standard_name, physical_name, label, domain_code, geometry_kind,
    feature_role, scope_type, active, sort_order
)
SELECT gen_random_uuid(), standard_name, physical_name, label, domain_code, geometry_kind,
       'ASSET', 'PROJECT', true, sort_order
FROM seed
ON CONFLICT (standard_name) DO UPDATE SET
    physical_name = EXCLUDED.physical_name,
    label = EXCLUDED.label,
    domain_code = EXCLUDED.domain_code,
    geometry_kind = EXCLUDED.geometry_kind,
    active = true,
    sort_order = EXCLUDED.sort_order,
    updated_at = now();

COMMIT;
