-- GeoFlow GIS schema foundation draft v0.2
-- DEVELOPMENT / REPOSITORY FOUNDATION.
-- Do not run against a production tenant DB without separate explicit approval.
-- PostgreSQL physical identifiers are lowercase; public/municipal standard names remain metadata/UI/export names.
-- WTL/SWL geometry subtype/SRID and their full field DDL are intentionally deferred until
-- DB테이블-- + municipal profile/code mapping is finalized and rehearsed in geoflow_dev.

BEGIN;

-- This foundation is intended for the tenant-shaped geoflow_dev development database.
-- ctr/hr/prj/ops are cloned from a stable tenant schema definition before this file runs.
-- Fail before making changes when the target is not clearly a dev/test DB or prj.projects is missing.
DO $$
BEGIN
    IF current_database() NOT ILIKE '%dev%' AND current_database() NOT ILIKE '%test%' THEN
        RAISE EXCEPTION 'Safety stop: GIS foundation may run only in a dev/test database. Current DB: %', current_database();
    END IF;
    IF to_regclass('prj.projects') IS NULL THEN
        RAISE EXCEPTION 'GeoFlow tenant base schema is missing: prj.projects not found. Run schema-only tenant bootstrap first.';
    END IF;
END
$$;

CREATE SCHEMA IF NOT EXISTS gis;

CREATE TABLE IF NOT EXISTS gis.meta_feature_type (
    id uuid PRIMARY KEY,
    standard_name text NOT NULL UNIQUE,
    physical_name text NOT NULL UNIQUE,
    label text NOT NULL,
    domain_code text NOT NULL,
    geometry_kind text,
    feature_role text NOT NULL DEFAULT 'ASSET',
    scope_type text NOT NULL DEFAULT 'PROJECT',
    active boolean NOT NULL DEFAULT true,
    sort_order integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS gis.meta_field_def (
    id uuid PRIMARY KEY,
    feature_type_id uuid NOT NULL REFERENCES gis.meta_feature_type(id) ON DELETE CASCADE,
    standard_name text NOT NULL,
    physical_name text NOT NULL,
    label text NOT NULL,
    data_type text NOT NULL,
    unit text,
    code_group_key text,
    widget_type text,
    required_default boolean NOT NULL DEFAULT false,
    core_field boolean NOT NULL DEFAULT false,
    sort_order integer NOT NULL DEFAULT 0,
    description text,
    UNIQUE(feature_type_id, physical_name)
);

CREATE TABLE IF NOT EXISTS gis.ref_code_group (
    id uuid PRIMARY KEY,
    group_key text NOT NULL UNIQUE,
    name text NOT NULL,
    source text,
    source_version text,
    active boolean NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS gis.ref_code_value (
    id uuid PRIMARY KEY,
    group_id uuid NOT NULL REFERENCES gis.ref_code_group(id) ON DELETE CASCADE,
    code text NOT NULL,
    label text NOT NULL,
    sort_order integer NOT NULL DEFAULT 0,
    active boolean NOT NULL DEFAULT true,
    valid_from date,
    valid_to date,
    UNIQUE(group_id, code)
);

CREATE TABLE IF NOT EXISTS gis.profile (
    id uuid PRIMARY KEY,
    code text NOT NULL UNIQUE,
    name text NOT NULL,
    municipality text,
    version text,
    active boolean NOT NULL DEFAULT true,
    description text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS gis.profile_feature (
    id uuid PRIMARY KEY,
    profile_id uuid NOT NULL REFERENCES gis.profile(id) ON DELETE CASCADE,
    feature_type_id uuid NOT NULL REFERENCES gis.meta_feature_type(id) ON DELETE CASCADE,
    enabled boolean NOT NULL DEFAULT true,
    required boolean NOT NULL DEFAULT false,
    sort_order integer NOT NULL DEFAULT 0,
    UNIQUE(profile_id, feature_type_id)
);

CREATE TABLE IF NOT EXISTS gis.profile_field (
    id uuid PRIMARY KEY,
    profile_id uuid NOT NULL REFERENCES gis.profile(id) ON DELETE CASCADE,
    field_def_id uuid NOT NULL REFERENCES gis.meta_field_def(id) ON DELETE CASCADE,
    enabled boolean NOT NULL DEFAULT true,
    required boolean,
    editable boolean NOT NULL DEFAULT true,
    visible boolean NOT NULL DEFAULT true,
    sort_order integer NOT NULL DEFAULT 0,
    UNIQUE(profile_id, field_def_id)
);

CREATE TABLE IF NOT EXISTS gis.survey (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES prj.projects(id),
    worker_id uuid,
    name varchar(30),
    code varchar(30),
    survey_code varchar(30),
    survey_date date,
    surveyed_at timestamptz,
    raw_x numeric(20,3),
    raw_y numeric(20,3),
    raw_z numeric(10,3),
    x numeric(20,3),
    y numeric(20,3),
    z numeric(10,3),
    latitude double precision,
    longitude double precision,
    solution_info varchar(200),
    pdop double precision,
    antenna_height numeric(8,3),
    filter varchar(20),
    type varchar(20),
    raw_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    raw_geom geometry(Point, 4326),
    geom geometry(Point, 4326),
    description text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS survey_project_idx ON gis.survey(project_id);
CREATE INDEX IF NOT EXISTS survey_geom_gix ON gis.survey USING gist(geom);

CREATE TABLE IF NOT EXISTS gis.survey_link (
    id uuid PRIMARY KEY,
    survey_id uuid NOT NULL REFERENCES gis.survey(id) ON DELETE CASCADE,
    feature_type_id uuid NOT NULL REFERENCES gis.meta_feature_type(id),
    target_id uuid NOT NULL,
    match_method varchar(30) NOT NULL,
    match_distance numeric(12,3),
    match_confidence numeric(5,4),
    confirmed_by uuid,
    confirmed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(survey_id, feature_type_id, target_id)
);
CREATE INDEX IF NOT EXISTS survey_link_target_idx ON gis.survey_link(feature_type_id, target_id);

CREATE TABLE IF NOT EXISTS gis.doro (
    id uuid PRIMARY KEY,
    gid bigint,
    project_id uuid REFERENCES prj.projects(id),
    pipedb smallint,
    len numeric(10,2),
    source_type varchar(30),
    road_link_id uuid,
    etctxt varchar(255),
    geom geometry(LineString, 4326),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS doro_project_idx ON gis.doro(project_id);
CREATE INDEX IF NOT EXISTS doro_geom_gix ON gis.doro USING gist(geom);

CREATE TABLE IF NOT EXISTS gis.import_batch (
    id uuid PRIMARY KEY,
    project_id uuid REFERENCES prj.projects(id),
    profile_id uuid REFERENCES gis.profile(id),
    source_type varchar(30),
    source_name text,
    source_storage_key text,
    total_count integer NOT NULL DEFAULT 0,
    success_count integer NOT NULL DEFAULT 0,
    warning_count integer NOT NULL DEFAULT 0,
    error_count integer NOT NULL DEFAULT 0,
    imported_by uuid,
    imported_at timestamptz NOT NULL DEFAULT now(),
    note text
);

-- Initial physical feature names registered by architecture:
-- WTL_ETC_PS, WTL_FIRE_PS, WTL_FLOW_PS, WTL_MANH_PS, WTL_PIPE_LM,
-- WTL_PIPE_PS, WTL_PLAN_LM, WTL_SPLY_LS, WTL_VALV_PS,
-- SWL_CONN_LS, SWL_ETC_PS, SWL_MANH_PS, SWL_PIPE_AS, SWL_PIPE_LM,
-- SWL_PIPE_PS, SWL_SIDE_LS, SWL_SPOT_PS.
-- Their final field DDL is intentionally not frozen in this foundation file.
-- It will be generated after DB테이블-- + municipal table/code mapping is approved.

COMMIT;
