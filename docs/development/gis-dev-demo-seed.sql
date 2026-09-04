\encoding UTF8
-- GeoFlow GIS synthetic development seed
-- DEVELOPMENT / TEST ONLY. No production or real customer data.
-- Purpose: verify UUID identity, project scoping, common survey lineage, and
-- physical layer counts without inventing municipal code values.

BEGIN;

DO $$
BEGIN
    IF current_database() !~* '(dev|test)' THEN
        RAISE EXCEPTION 'Safety stop: synthetic GIS seed may run only in dev/test DB. Current DB=%', current_database();
    END IF;
    IF to_regclass('prj.projects') IS NULL OR to_regclass('gis.survey') IS NULL THEN
        RAISE EXCEPTION 'GeoFlow dev/GIS foundation is incomplete.';
    END IF;
    IF to_regclass('gis.wtl_pipe_lm') IS NULL OR to_regclass('gis.swl_pipe_lm') IS NULL THEN
        RAISE EXCEPTION 'Initial WTL/SWL physical feature tables are missing.';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM gis.meta_feature_type WHERE standard_name='WTL_PIPE_LM') THEN
        RAISE EXCEPTION 'GIS metadata/profile seed is missing. Apply gis-metadata-seed-v0.1.sql first.';
    END IF;
END
$$;

-- One deterministic project is enough to exercise project-scoped GIS screens.
-- contract_id is intentionally NULL: GIS development must not require fake contract data.
INSERT INTO prj.projects(
    id, contract_id, code, name, start_date, end_date, status, description, ext, created_at, updated_at
)
VALUES (
    '11111111-1111-4111-8111-111111111111'::uuid,
    NULL,
    'GIS-DEV-001',
    'GIS 개발 테스트 프로젝트',
    DATE '2026-09-01',
    DATE '2026-12-31',
    'in_progress',
    'Synthetic project for geoflow_dev GIS integration tests only.',
    '{"synthetic": true, "purpose": "gis_dev"}'::jsonb,
    now(), now()
)
ON CONFLICT (id) DO UPDATE SET
    code = EXCLUDED.code,
    name = EXCLUDED.name,
    start_date = EXCLUDED.start_date,
    end_date = EXCLUDED.end_date,
    status = EXCLUDED.status,
    description = EXCLUDED.description,
    ext = EXCLUDED.ext,
    updated_at = now();

-- Common survey/reference data. Coordinates are synthetic test coordinates.
INSERT INTO gis.survey(
    id, project_id, worker_id, name, code, survey_code, survey_date, surveyed_at,
    latitude, longitude, solution_info, pdop, antenna_height,
    raw_data, raw_geom, geom, description
)
VALUES (
    '21111111-1111-4111-8111-111111111111'::uuid,
    '11111111-1111-4111-8111-111111111111'::uuid,
    NULL,
    'GIS 개발 측점 1',
    'DEV-SV-001',
    'DEV-SV-001',
    DATE '2026-09-04',
    TIMESTAMPTZ '2026-09-04 15:00:00+09',
    36.8150,
    127.1500,
    'SYNTHETIC',
    1.0,
    2.000,
    '{"synthetic": true}'::jsonb,
    ST_SetSRID(ST_MakePoint(127.1500,36.8150),4326),
    ST_SetSRID(ST_MakePoint(127.1500,36.8150),4326),
    'Synthetic survey observation for development only.'
)
ON CONFLICT (id) DO UPDATE SET
    project_id = EXCLUDED.project_id,
    name = EXCLUDED.name,
    code = EXCLUDED.code,
    survey_code = EXCLUDED.survey_code,
    survey_date = EXCLUDED.survey_date,
    surveyed_at = EXCLUDED.surveyed_at,
    latitude = EXCLUDED.latitude,
    longitude = EXCLUDED.longitude,
    solution_info = EXCLUDED.solution_info,
    pdop = EXCLUDED.pdop,
    antenna_height = EXCLUDED.antenna_height,
    raw_data = EXCLUDED.raw_data,
    raw_geom = EXCLUDED.raw_geom,
    geom = EXCLUDED.geom,
    description = EXCLUDED.description,
    updated_at = now();

INSERT INTO gis.doro(id, project_id, source_type, etctxt, geom)
VALUES (
    '31111111-1111-4111-8111-111111111111'::uuid,
    '11111111-1111-4111-8111-111111111111'::uuid,
    'SYNTHETIC',
    'GIS 개발용 가상 도로 기준선',
    ST_GeomFromText('LINESTRING(127.1495 36.8147,127.1510 36.8154)',4326)
)
ON CONFLICT (id) DO UPDATE SET
    project_id = EXCLUDED.project_id,
    source_type = EXCLUDED.source_type,
    etctxt = EXCLUDED.etctxt,
    geom = EXCLUDED.geom,
    updated_at = now();

-- WTL: ftr_cde/ftr_idn intentionally NULL. UUID id is authoritative.
INSERT INTO gis.wtl_pipe_lm(
    id, project_id, ftr_cde, ftr_idn, source_name, source_key, description, ext_data, geom
)
VALUES (
    '41111111-1111-4111-8111-111111111111'::uuid,
    '11111111-1111-4111-8111-111111111111'::uuid,
    NULL, NULL,
    'synthetic', 'WTL-PIPE-001',
    'Synthetic water pipe for GeoFlow GIS development.',
    '{"synthetic": true}'::jsonb,
    ST_GeomFromText('LINESTRING(127.1498 36.8149,127.1508 36.8153)',4326)
), (
    '41111111-1111-4111-8111-111111111112'::uuid,
    '11111111-1111-4111-8111-111111111111'::uuid,
    NULL, NULL,
    'synthetic', 'WTL-PIPE-002',
    'Synthetic water pipe for GeoFlow GIS development.',
    '{"synthetic": true}'::jsonb,
    ST_GeomFromText('LINESTRING(127.1508 36.8153,127.1512 36.81545)',4326)
)
ON CONFLICT (id) DO UPDATE SET
    project_id = EXCLUDED.project_id,
    ftr_cde = NULL,
    ftr_idn = NULL,
    source_name = EXCLUDED.source_name,
    source_key = EXCLUDED.source_key,
    description = EXCLUDED.description,
    ext_data = EXCLUDED.ext_data,
    geom = EXCLUDED.geom,
    updated_at = now();

INSERT INTO gis.wtl_valv_ps(
    id, project_id, ftr_cde, ftr_idn, source_name, source_key, description, ext_data, geom
)
VALUES (
    '42111111-1111-4111-8111-111111111111'::uuid,
    '11111111-1111-4111-8111-111111111111'::uuid,
    NULL, NULL,
    'synthetic', 'WTL-VALV-001',
    'Synthetic water valve for GeoFlow GIS development.',
    '{"synthetic": true}'::jsonb,
    ST_SetSRID(ST_MakePoint(127.1503,36.8151),4326)
)
ON CONFLICT (id) DO UPDATE SET
    project_id = EXCLUDED.project_id,
    ftr_cde = NULL,
    ftr_idn = NULL,
    source_name = EXCLUDED.source_name,
    source_key = EXCLUDED.source_key,
    description = EXCLUDED.description,
    ext_data = EXCLUDED.ext_data,
    geom = EXCLUDED.geom,
    updated_at = now();

INSERT INTO gis.wtl_manh_ps(
    id, project_id, ftr_cde, ftr_idn, source_name, source_key, description, ext_data, geom
)
VALUES (
    '43111111-1111-4111-8111-111111111111'::uuid,
    '11111111-1111-4111-8111-111111111111'::uuid,
    NULL, NULL,
    'synthetic', 'WTL-MANH-001',
    'Synthetic water manhole for GeoFlow GIS development.',
    '{"synthetic": true}'::jsonb,
    ST_SetSRID(ST_MakePoint(127.1507,36.81525),4326)
)
ON CONFLICT (id) DO UPDATE SET
    project_id = EXCLUDED.project_id,
    ftr_cde = NULL,
    ftr_idn = NULL,
    source_name = EXCLUDED.source_name,
    source_key = EXCLUDED.source_key,
    description = EXCLUDED.description,
    ext_data = EXCLUDED.ext_data,
    geom = EXCLUDED.geom,
    updated_at = now();

-- SWL representative objects; municipal codes remain NULL until real mapping.
INSERT INTO gis.swl_pipe_lm(
    id, project_id, ftr_cde, ftr_idn, source_name, source_key, description, ext_data, geom
)
VALUES (
    '51111111-1111-4111-8111-111111111111'::uuid,
    '11111111-1111-4111-8111-111111111111'::uuid,
    NULL, NULL,
    'synthetic', 'SWL-PIPE-001',
    'Synthetic sewer pipe for GeoFlow GIS development.',
    '{"synthetic": true}'::jsonb,
    ST_GeomFromText('LINESTRING(127.1497 36.8146,127.1509 36.8149)',4326)
)
ON CONFLICT (id) DO UPDATE SET
    project_id = EXCLUDED.project_id,
    ftr_cde = NULL,
    ftr_idn = NULL,
    source_name = EXCLUDED.source_name,
    source_key = EXCLUDED.source_key,
    description = EXCLUDED.description,
    ext_data = EXCLUDED.ext_data,
    geom = EXCLUDED.geom,
    updated_at = now();

INSERT INTO gis.swl_manh_ps(
    id, project_id, ftr_cde, ftr_idn, source_name, source_key, description, ext_data, geom
)
VALUES (
    '52111111-1111-4111-8111-111111111111'::uuid,
    '11111111-1111-4111-8111-111111111111'::uuid,
    NULL, NULL,
    'synthetic', 'SWL-MANH-001',
    'Synthetic sewer manhole for GeoFlow GIS development.',
    '{"synthetic": true}'::jsonb,
    ST_SetSRID(ST_MakePoint(127.1501,36.81475),4326)
)
ON CONFLICT (id) DO UPDATE SET
    project_id = EXCLUDED.project_id,
    ftr_cde = NULL,
    ftr_idn = NULL,
    source_name = EXCLUDED.source_name,
    source_key = EXCLUDED.source_key,
    description = EXCLUDED.description,
    ext_data = EXCLUDED.ext_data,
    geom = EXCLUDED.geom,
    updated_at = now();

-- Durable lineage example: one survey observation is confirmed against a
-- concrete WTL_PIPE_LM object UUID. target_id is never ftr_idn.
INSERT INTO gis.survey_link(
    id, survey_id, feature_type_id, target_id, match_method,
    match_distance, match_confidence, confirmed_at
)
SELECT
    '61111111-1111-4111-8111-111111111111'::uuid,
    '21111111-1111-4111-8111-111111111111'::uuid,
    ft.id,
    '41111111-1111-4111-8111-111111111111'::uuid,
    'SYNTHETIC',
    0.0,
    1.0,
    now()
FROM gis.meta_feature_type ft
WHERE ft.standard_name = 'WTL_PIPE_LM'
ON CONFLICT (survey_id, feature_type_id, target_id) DO UPDATE SET
    match_method = EXCLUDED.match_method,
    match_distance = EXCLUDED.match_distance,
    match_confidence = EXCLUDED.match_confidence,
    confirmed_at = EXCLUDED.confirmed_at;

COMMIT;
