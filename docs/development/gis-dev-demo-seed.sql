-- GeoFlow GIS synthetic development seed
-- DEVELOPMENT / TEST ONLY. No production or real customer data.

BEGIN;

DO $$
BEGIN
    IF current_database() !~* '(dev|test)' THEN
        RAISE EXCEPTION 'Safety stop: synthetic GIS seed may run only in dev/test DB. Current DB=%', current_database();
    END IF;
    IF to_regclass('prj.projects') IS NULL OR to_regclass('gis.wtl_pipe_lm') IS NULL THEN
        RAISE EXCEPTION 'GeoFlow dev/GIS physical schema is incomplete.';
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
    status = EXCLUDED.status,
    description = EXCLUDED.description,
    ext = EXCLUDED.ext,
    updated_at = now();

-- Common survey/reference data. Coordinates are synthetic test coordinates.
INSERT INTO gis.survey(
    id, project_id, worker_id, name, survey_code, survey_date,
    raw_x, raw_y, raw_z, x, y, z, latitude, longitude,
    raw_data, raw_geom, geom, description
)
VALUES (
    '21111111-1111-4111-8111-111111111111'::uuid,
    '11111111-1111-4111-8111-111111111111'::uuid,
    NULL,
    'DEV-SURVEY-01',
    'DEV-001',
    DATE '2026-09-04',
    127.1500, 36.8150, 25.100,
    127.1500, 36.8150, 25.100,
    36.8150, 127.1500,
    '{"synthetic": true}'::jsonb,
    ST_SetSRID(ST_MakePoint(127.1500,36.8150),4326),
    ST_SetSRID(ST_MakePoint(127.1500,36.8150),4326),
    'Synthetic survey point'
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO gis.doro(id, project_id, source_type, etctxt, geom)
VALUES (
    '31111111-1111-4111-8111-111111111111'::uuid,
    '11111111-1111-4111-8111-111111111111'::uuid,
    'SYNTHETIC',
    'Synthetic road reference',
    ST_GeomFromText('LINESTRING(127.1495 36.8147,127.1510 36.8154)',4326)
)
ON CONFLICT (id) DO NOTHING;

-- WTL: ftr_idn is intentionally NULL. GeoFlow UUID id is authoritative.
INSERT INTO gis.wtl_pipe_lm(
    id, project_id, ftr_cde, ftr_idn, saa_cde, mop_cde, pip_dip, pip_len,
    source_name, description, ext_data, geom
)
VALUES (
    '41111111-1111-4111-8111-111111111111'::uuid,
    '11111111-1111-4111-8111-111111111111'::uuid,
    'DEV_PIPE', NULL, 'DEV', 'DCIP', 300, 120.0,
    'synthetic', 'Synthetic water pipe', '{"synthetic": true}'::jsonb,
    ST_GeomFromText('LINESTRING(127.1498 36.8149,127.1508 36.8153)',4326)
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO gis.wtl_valv_ps(
    id, project_id, ftr_cde, ftr_idn, val_mof, val_mop, val_dip,
    source_name, description, ext_data, geom
)
VALUES (
    '42111111-1111-4111-8111-111111111111'::uuid,
    '11111111-1111-4111-8111-111111111111'::uuid,
    'DEV_VALV', NULL, 'DEV', 'DCIP', 300,
    'synthetic', 'Synthetic water valve', '{"synthetic": true}'::jsonb,
    ST_SetSRID(ST_MakePoint(127.1503,36.8151),4326)
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO gis.wtl_manh_ps(
    id, project_id, ftr_cde, ftr_idn, source_name, description, ext_data, geom
)
VALUES (
    '43111111-1111-4111-8111-111111111111'::uuid,
    '11111111-1111-4111-8111-111111111111'::uuid,
    'DEV_MANH', NULL, 'synthetic', 'Synthetic water manhole', '{"synthetic": true}'::jsonb,
    ST_SetSRID(ST_MakePoint(127.1507,36.81525),4326)
)
ON CONFLICT (id) DO NOTHING;

-- SWL representative objects.
INSERT INTO gis.swl_pipe_lm(
    id, project_id, ftr_cde, ftr_idn, pip_dip, pip_dep, pip_len,
    source_name, description, ext_data, geom
)
VALUES (
    '51111111-1111-4111-8111-111111111111'::uuid,
    '11111111-1111-4111-8111-111111111111'::uuid,
    'DEV_SPIPE', NULL, 450, 1.8, 90.0,
    'synthetic', 'Synthetic sewer pipe', '{"synthetic": true}'::jsonb,
    ST_GeomFromText('LINESTRING(127.1497 36.8146,127.1509 36.8149)',4326)
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO gis.swl_manh_ps(
    id, project_id, ftr_cde, ftr_idn, man_dip, man_dep,
    source_name, description, ext_data, geom
)
VALUES (
    '52111111-1111-4111-8111-111111111111'::uuid,
    '11111111-1111-4111-8111-111111111111'::uuid,
    'DEV_SMANH', NULL, 900, 2.1,
    'synthetic', 'Synthetic sewer manhole', '{"synthetic": true}'::jsonb,
    ST_SetSRID(ST_MakePoint(127.1501,36.81475),4326)
)
ON CONFLICT (id) DO NOTHING;

COMMIT;
