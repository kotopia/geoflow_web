\encoding UTF8
-- GeoFlow GIS synthetic development seed
-- DEVELOPMENT / TEST ONLY.
-- Purpose: verify UUID identity, project scoping, physical layer counts, and
-- basic common/WTL/SWL geometry flow without copying production business data.

BEGIN;

DO $$
BEGIN
    IF current_database() !~* '(dev|test)' THEN
        RAISE EXCEPTION 'Safety stop: synthetic GIS seed may run only in a dev/test database. Current DB=%', current_database();
    END IF;
    IF to_regclass('prj.projects') IS NULL OR to_regclass('gis.survey') IS NULL THEN
        RAISE EXCEPTION 'GeoFlow dev tenant/GIS foundation is incomplete.';
    END IF;
    IF to_regclass('gis.wtl_pipe_lm') IS NULL OR to_regclass('gis.swl_pipe_lm') IS NULL THEN
        RAISE EXCEPTION 'Initial WTL/SWL physical feature tables are missing.';
    END IF;
END
$$;

-- Fixed UUIDs make the seed idempotent and easy to reference in UI/API tests.
-- This is synthetic development data only.
INSERT INTO prj.projects (
    id, code, name, start_date, end_date, status, description, ext, created_at, updated_at
)
VALUES (
    '00000000-0000-4000-8000-000000000101'::uuid,
    'GIS-DEV-001',
    'GeoFlow GIS 개발 테스트 프로젝트',
    DATE '2026-09-01',
    DATE '2026-12-31',
    'in_progress',
    'Synthetic project for GeoFlow GIS development. No production data.',
    '{"synthetic": true, "purpose": "gis-development"}'::jsonb,
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

INSERT INTO gis.doro (
    id, project_id, source_type, etctxt, geom
)
VALUES (
    '00000000-0000-4000-8000-000000001001'::uuid,
    '00000000-0000-4000-8000-000000000101'::uuid,
    'synthetic',
    'GIS 개발용 가상 도로 기준선',
    ST_GeomFromText('LINESTRING(127.0000 36.7800,127.0020 36.7805)', 4326)
)
ON CONFLICT (id) DO UPDATE SET
    project_id = EXCLUDED.project_id,
    source_type = EXCLUDED.source_type,
    etctxt = EXCLUDED.etctxt,
    geom = EXCLUDED.geom,
    updated_at = now();

INSERT INTO gis.survey (
    id, project_id, name, code, survey_code, survey_date, surveyed_at,
    latitude, longitude, solution_info, pdop, antenna_height,
    raw_data, raw_geom, geom, description
)
VALUES (
    '00000000-0000-4000-8000-000000002001'::uuid,
    '00000000-0000-4000-8000-000000000101'::uuid,
    'GIS 개발 측점 1',
    'DEV-SV-001',
    'DEV-SV-001',
    DATE '2026-09-04',
    TIMESTAMPTZ '2026-09-04 15:00:00+09',
    36.78020,
    127.00070,
    'SYNTHETIC',
    1.0,
    2.000,
    '{"synthetic": true}'::jsonb,
    ST_SetSRID(ST_MakePoint(127.00070, 36.78020), 4326),
    ST_SetSRID(ST_MakePoint(127.00070, 36.78020), 4326),
    'Synthetic survey observation for development only.'
)
ON CONFLICT (id) DO UPDATE SET
    project_id = EXCLUDED.project_id,
    name = EXCLUDED.name,
    survey_date = EXCLUDED.survey_date,
    surveyed_at = EXCLUDED.surveyed_at,
    latitude = EXCLUDED.latitude,
    longitude = EXCLUDED.longitude,
    raw_data = EXCLUDED.raw_data,
    raw_geom = EXCLUDED.raw_geom,
    geom = EXCLUDED.geom,
    description = EXCLUDED.description,
    updated_at = now();

-- ftr_idn/ftr_cde are deliberately NULL. UUID id is the GeoFlow identity.
INSERT INTO gis.wtl_pipe_lm (
    id, project_id, ftr_cde, ftr_idn, source_name, source_key, description, ext_data, geom
)
VALUES (
    '00000000-0000-4000-8000-000000003001'::uuid,
    '00000000-0000-4000-8000-000000000101'::uuid,
    NULL, NULL,
    'synthetic', 'WTL-PIPE-001',
    'Synthetic water pipe for GeoFlow GIS development.',
    '{"synthetic": true}'::jsonb,
    ST_GeomFromText('LINESTRING(127.0002 36.7801,127.0012 36.78035)', 4326)
), (
    '00000000-0000-4000-8000-000000003002'::uuid,
    '00000000-0000-4000-8000-000000000101'::uuid,
    NULL, NULL,
    'synthetic', 'WTL-PIPE-002',
    'Synthetic water pipe for GeoFlow GIS development.',
    '{"synthetic": true}'::jsonb,
    ST_GeomFromText('LINESTRING(127.0012 36.78035,127.0019 36.78050)', 4326)
)
ON CONFLICT (id) DO UPDATE SET
    project_id = EXCLUDED.project_id,
    source_name = EXCLUDED.source_name,
    source_key = EXCLUDED.source_key,
    description = EXCLUDED.description,
    ext_data = EXCLUDED.ext_data,
    geom = EXCLUDED.geom,
    updated_at = now();

INSERT INTO gis.wtl_valv_ps (
    id, project_id, ftr_cde, ftr_idn, source_name, source_key, description, ext_data, geom
)
VALUES (
    '00000000-0000-4000-8000-000000004001'::uuid,
    '00000000-0000-4000-8000-000000000101'::uuid,
    NULL, NULL,
    'synthetic', 'WTL-VALV-001',
    'Synthetic water valve for GeoFlow GIS development.',
    '{"synthetic": true}'::jsonb,
    ST_SetSRID(ST_MakePoint(127.0012, 36.78035), 4326)
)
ON CONFLICT (id) DO UPDATE SET
    project_id = EXCLUDED.project_id,
    source_name = EXCLUDED.source_name,
    source_key = EXCLUDED.source_key,
    description = EXCLUDED.description,
    ext_data = EXCLUDED.ext_data,
    geom = EXCLUDED.geom,
    updated_at = now();

INSERT INTO gis.swl_pipe_lm (
    id, project_id, ftr_cde, ftr_idn, source_name, source_key, description, ext_data, geom
)
VALUES (
    '00000000-0000-4000-8000-000000005001'::uuid,
    '00000000-0000-4000-8000-000000000101'::uuid,
    NULL, NULL,
    'synthetic', 'SWL-PIPE-001',
    'Synthetic sewer pipe for GeoFlow GIS development.',
    '{"synthetic": true}'::jsonb,
    ST_GeomFromText('LINESTRING(127.0003 36.7797,127.0017 36.7799)', 4326)
)
ON CONFLICT (id) DO UPDATE SET
    project_id = EXCLUDED.project_id,
    source_name = EXCLUDED.source_name,
    source_key = EXCLUDED.source_key,
    description = EXCLUDED.description,
    ext_data = EXCLUDED.ext_data,
    geom = EXCLUDED.geom,
    updated_at = now();

-- Durable survey lineage example: survey -> WTL_PIPE_LM object.
INSERT INTO gis.survey_link (
    id, survey_id, feature_type_id, target_id, match_method,
    match_distance, match_confidence, confirmed_at
)
SELECT
    '00000000-0000-4000-8000-000000006001'::uuid,
    '00000000-0000-4000-8000-000000002001'::uuid,
    ft.id,
    '00000000-0000-4000-8000-000000003001'::uuid,
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
