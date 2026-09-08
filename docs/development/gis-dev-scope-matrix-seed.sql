\encoding UTF8
-- GeoFlow multi-project GIS business-scope development matrix
-- DEVELOPMENT / TEST ONLY. No production/customer data.

BEGIN;

DO $$
BEGIN
    IF current_database() !~* '(dev|test)' THEN
        RAISE EXCEPTION 'Safety stop: scope matrix seed may run only in dev/test DB. Current DB=%', current_database();
    END IF;
    IF to_regclass('gis.scope_binding') IS NULL OR to_regclass('gis.project_profile') IS NULL THEN
        RAISE EXCEPTION 'Apply gis-scope-capability-v0.1.sql first.';
    END IF;
    IF to_regclass('prj.scope_item') IS NULL THEN
        RAISE EXCEPTION 'prj.scope_item is missing.';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM ops.my_org_units WHERE id='11111111-1111-4111-8111-111111111101'::uuid)
       OR NOT EXISTS (SELECT 1 FROM ctr.partners WHERE id='11111111-1111-4111-8111-111111111201'::uuid) THEN
        RAISE EXCEPTION 'Run the original GIS development demo seed first.';
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- Development-only business-scope identities. These UUIDs deliberately do not
-- modify central catalog. Later, bind the real central catalog UUIDs through
-- the same gis.scope_binding table.
-- ---------------------------------------------------------------------------
WITH seed(level_no,item_id,item_code,item_name,capability_code) AS (
    VALUES
      (3,'70000000-0000-4000-8000-000000000201'::uuid,'GIS_DEV_SCOPE_WATER','지하시설물 / 상수','WATER'),
      (3,'70000000-0000-4000-8000-000000000202'::uuid,'GIS_DEV_SCOPE_SEWER','지하시설물 / 하수','SEWER'),
      (3,'70000000-0000-4000-8000-000000000203'::uuid,'GIS_DEV_SCOPE_ROAD','지하시설물 / 도로','ROAD'),
      (3,'70000000-0000-4000-8000-000000000204'::uuid,'GIS_DEV_SCOPE_SURVEY','지하시설물 / 측량','SURVEY')
)
INSERT INTO gis.scope_binding(
    id,catalog_level,catalog_item_id,catalog_code_cache,catalog_name_cache,
    capability_id,active,priority,note
)
SELECT gen_random_uuid(),s.level_no,s.item_id,s.item_code,s.item_name,c.id,true,10,
       'Synthetic development binding; replace with real central catalog UUID binding after catalog mapping review.'
FROM seed s
JOIN gis.capability c ON c.code=s.capability_code
ON CONFLICT (catalog_level,catalog_item_id,capability_id) DO UPDATE SET
    catalog_code_cache=EXCLUDED.catalog_code_cache,
    catalog_name_cache=EXCLUDED.catalog_name_cache,
    active=true,
    priority=EXCLUDED.priority,
    note=EXCLUDED.note,
    updated_at=now();

-- ---------------------------------------------------------------------------
-- Three contracts / six projects. Contract 001 already exists from the base GIS
-- demo and gains a second project, proving contract 1:N project structure.
-- ---------------------------------------------------------------------------
INSERT INTO prj.projects(
    id,contract_id,code,name,start_date,end_date,status,description,org_unit_id,ext,created_at,updated_at
)
VALUES (
    '11111111-1111-4111-8111-111111111402'::uuid,
    '11111111-1111-4111-8111-111111111301'::uuid,
    'GIS-DEV-002','상수도 전용 GIS 프로젝트',DATE '2026-09-01',DATE '2026-12-31','in_progress',
    'Synthetic WATER-only project.','11111111-1111-4111-8111-111111111101'::uuid,
    '{"synthetic":true,"purpose":"gis_scope_matrix"}'::jsonb,now(),now()
)
ON CONFLICT (id) DO UPDATE SET code=EXCLUDED.code,name=EXCLUDED.name,status=EXCLUDED.status,
    description=EXCLUDED.description,ext=EXCLUDED.ext,updated_at=now();

INSERT INTO ctr.contracts(
    id,code,name,start_date,end_date,amount,status,kind,division,
    client_id,sub_client_id,org_unit_id,ext,description,created_at,updated_at
)
VALUES
('11111111-1111-4111-8111-111111111302'::uuid,'GIS-DEV-CONTRACT-002','GIS 개발 테스트 계약 2',DATE '2026-09-01',DATE '2026-12-31',0,'in_progress','development','GIS','11111111-1111-4111-8111-111111111201'::uuid,NULL,'11111111-1111-4111-8111-111111111101'::uuid,'{"synthetic":true}'::jsonb,'SEWER + non-GIS scope test contract.',now(),now()),
('11111111-1111-4111-8111-111111111303'::uuid,'GIS-DEV-CONTRACT-003','GIS 개발 테스트 계약 3',DATE '2026-09-01',DATE '2026-12-31',0,'in_progress','development','GIS','11111111-1111-4111-8111-111111111201'::uuid,NULL,'11111111-1111-4111-8111-111111111101'::uuid,'{"synthetic":true}'::jsonb,'ROAD + SURVEY scope test contract.',now(),now())
ON CONFLICT (id) DO UPDATE SET code=EXCLUDED.code,name=EXCLUDED.name,status=EXCLUDED.status,
    description=EXCLUDED.description,ext=EXCLUDED.ext,updated_at=now();

-- Ensure each new contract has a first project even when the tenant trigger is absent.
INSERT INTO prj.projects(id,contract_id,code,name,start_date,end_date,status,description,org_unit_id,ext,created_at,updated_at)
SELECT '11111111-1111-4111-8111-111111111403'::uuid,c.id,'GIS-DEV-003','하수도 전용 GIS 프로젝트',DATE '2026-09-01',DATE '2026-12-31','in_progress','Synthetic SEWER-only project.',c.org_unit_id,'{"synthetic":true,"purpose":"gis_scope_matrix"}'::jsonb,now(),now()
FROM ctr.contracts c WHERE c.id='11111111-1111-4111-8111-111111111302'::uuid
AND NOT EXISTS (SELECT 1 FROM prj.projects p WHERE p.contract_id=c.id)
ON CONFLICT (id) DO NOTHING;

UPDATE prj.projects p SET code='GIS-DEV-003',name='하수도 전용 GIS 프로젝트',description='Synthetic SEWER-only project.',ext='{"synthetic":true,"purpose":"gis_scope_matrix"}'::jsonb,updated_at=now()
WHERE p.id=(SELECT id FROM prj.projects WHERE contract_id='11111111-1111-4111-8111-111111111302'::uuid ORDER BY created_at NULLS LAST,id LIMIT 1);

INSERT INTO prj.projects(id,contract_id,code,name,start_date,end_date,status,description,org_unit_id,ext,created_at,updated_at)
VALUES ('11111111-1111-4111-8111-111111111404'::uuid,'11111111-1111-4111-8111-111111111302'::uuid,'GIS-DEV-004','GIS 비대상 업무 프로젝트',DATE '2026-09-01',DATE '2026-12-31','in_progress','Synthetic project with no GIS capability binding.','11111111-1111-4111-8111-111111111101'::uuid,'{"synthetic":true,"purpose":"gis_scope_matrix"}'::jsonb,now(),now())
ON CONFLICT (id) DO UPDATE SET code=EXCLUDED.code,name=EXCLUDED.name,status=EXCLUDED.status,description=EXCLUDED.description,ext=EXCLUDED.ext,updated_at=now();

INSERT INTO prj.projects(id,contract_id,code,name,start_date,end_date,status,description,org_unit_id,ext,created_at,updated_at)
SELECT '11111111-1111-4111-8111-111111111405'::uuid,c.id,'GIS-DEV-005','도로 GIS 프로젝트',DATE '2026-09-01',DATE '2026-12-31','in_progress','Synthetic ROAD project.',c.org_unit_id,'{"synthetic":true,"purpose":"gis_scope_matrix"}'::jsonb,now(),now()
FROM ctr.contracts c WHERE c.id='11111111-1111-4111-8111-111111111303'::uuid
AND NOT EXISTS (SELECT 1 FROM prj.projects p WHERE p.contract_id=c.id)
ON CONFLICT (id) DO NOTHING;

UPDATE prj.projects p SET code='GIS-DEV-005',name='도로 GIS 프로젝트',description='Synthetic ROAD project.',ext='{"synthetic":true,"purpose":"gis_scope_matrix"}'::jsonb,updated_at=now()
WHERE p.id=(SELECT id FROM prj.projects WHERE contract_id='11111111-1111-4111-8111-111111111303'::uuid ORDER BY created_at NULLS LAST,id LIMIT 1);

INSERT INTO prj.projects(id,contract_id,code,name,start_date,end_date,status,description,org_unit_id,ext,created_at,updated_at)
VALUES ('11111111-1111-4111-8111-111111111406'::uuid,'11111111-1111-4111-8111-111111111303'::uuid,'GIS-DEV-006','측량 전용 GIS 프로젝트',DATE '2026-09-01',DATE '2026-12-31','in_progress','Synthetic SURVEY project.','11111111-1111-4111-8111-111111111101'::uuid,'{"synthetic":true,"purpose":"gis_scope_matrix"}'::jsonb,now(),now())
ON CONFLICT (id) DO UPDATE SET code=EXCLUDED.code,name=EXCLUDED.name,status=EXCLUDED.status,description=EXCLUDED.description,ext=EXCLUDED.ext,updated_at=now();

-- ---------------------------------------------------------------------------
-- Business scope matrix. Shared synthetic L2 represents underground utilities;
-- L3 determines capability. NON_GIS intentionally has no gis.scope_binding.
-- ---------------------------------------------------------------------------
WITH scopes(project_code,scope_id,lv3_id,remark) AS (
    VALUES
      ('GIS-DEV-001','71000000-0000-4000-8000-000000000001'::uuid,'70000000-0000-4000-8000-000000000201'::uuid,'WATER'),
      ('GIS-DEV-001','71000000-0000-4000-8000-000000000002'::uuid,'70000000-0000-4000-8000-000000000202'::uuid,'SEWER'),
      ('GIS-DEV-002','71000000-0000-4000-8000-000000000003'::uuid,'70000000-0000-4000-8000-000000000201'::uuid,'WATER'),
      ('GIS-DEV-003','71000000-0000-4000-8000-000000000004'::uuid,'70000000-0000-4000-8000-000000000202'::uuid,'SEWER'),
      ('GIS-DEV-004','71000000-0000-4000-8000-000000000005'::uuid,'70000000-0000-4000-8000-000000000299'::uuid,'NON_GIS'),
      ('GIS-DEV-005','71000000-0000-4000-8000-000000000006'::uuid,'70000000-0000-4000-8000-000000000203'::uuid,'ROAD'),
      ('GIS-DEV-006','71000000-0000-4000-8000-000000000007'::uuid,'70000000-0000-4000-8000-000000000204'::uuid,'SURVEY')
)
INSERT INTO prj.scope_item(id,project_id,lv2_id,lv3_id,lv4_id,unit,design_qty,completed_qty,remark,created_at,updated_at)
SELECT s.scope_id,p.id,'70000000-0000-4000-8000-000000000100'::uuid,s.lv3_id,NULL,'NONE',NULL,NULL,'Synthetic GIS scope: '||s.remark,now(),now()
FROM scopes s JOIN prj.projects p ON p.code=s.project_code
ON CONFLICT (id) DO UPDATE SET project_id=EXCLUDED.project_id,lv2_id=EXCLUDED.lv2_id,lv3_id=EXCLUDED.lv3_id,
    lv4_id=NULL,unit=EXCLUDED.unit,remark=EXCLUDED.remark,updated_at=now();

-- Explicit project profile assignment for every matrix project, including the
-- NON_GIS control case. GIS activation still requires a capability binding.
INSERT INTO gis.project_profile(project_id,profile_id,status,auto_assigned)
SELECT p.id,prof.id,'active',true
FROM prj.projects p CROSS JOIN gis.profile prof
WHERE p.code IN ('GIS-DEV-001','GIS-DEV-002','GIS-DEV-003','GIS-DEV-004','GIS-DEV-005','GIS-DEV-006')
  AND prof.code='GEOFLOW_DEV_BASE'
ON CONFLICT (project_id) DO UPDATE SET profile_id=EXCLUDED.profile_id,status='active',auto_assigned=true,updated_at=now();

-- ---------------------------------------------------------------------------
-- Representative geometry for the new projects. Empty tables remain part of
-- the layer plan; QGIS/QField must receive schema layers even when count=0.
-- ---------------------------------------------------------------------------
INSERT INTO gis.survey(id,project_id,name,code,survey_code,survey_date,latitude,longitude,solution_info,raw_data,raw_geom,geom,description)
SELECT v.id,p.id,v.name,v.code,v.code,DATE '2026-09-04',v.lat,v.lon,'SYNTHETIC','{"synthetic":true}'::jsonb,
       ST_SetSRID(ST_MakePoint(v.lon,v.lat),4326),ST_SetSRID(ST_MakePoint(v.lon,v.lat),4326),'Scope matrix survey'
FROM (VALUES
 ('22111111-1111-4111-8111-111111111102'::uuid,'GIS-DEV-002','WATER 측점','DEV-SV-002',36.8160::double precision,127.1520::double precision),
 ('22111111-1111-4111-8111-111111111103'::uuid,'GIS-DEV-003','SEWER 측점','DEV-SV-003',36.8170::double precision,127.1540::double precision),
 ('22111111-1111-4111-8111-111111111106'::uuid,'GIS-DEV-006','SURVEY 측점','DEV-SV-006',36.8200::double precision,127.1600::double precision)
) v(id,project_code,name,code,lat,lon)
JOIN prj.projects p ON p.code=v.project_code
ON CONFLICT (id) DO UPDATE SET project_id=EXCLUDED.project_id,name=EXCLUDED.name,code=EXCLUDED.code,survey_code=EXCLUDED.survey_code,
    latitude=EXCLUDED.latitude,longitude=EXCLUDED.longitude,raw_geom=EXCLUDED.raw_geom,geom=EXCLUDED.geom,description=EXCLUDED.description,updated_at=now();

INSERT INTO gis.doro(id,project_id,source_type,etctxt,geom)
SELECT v.id,p.id,'SYNTHETIC',v.label,ST_GeomFromText(v.wkt,4326)
FROM (VALUES
 ('32111111-1111-4111-8111-111111111102'::uuid,'GIS-DEV-002','WATER 도로 기준','LINESTRING(127.1515 36.8157,127.1525 36.8163)'),
 ('32111111-1111-4111-8111-111111111103'::uuid,'GIS-DEV-003','SEWER 도로 기준','LINESTRING(127.1535 36.8167,127.1545 36.8173)'),
 ('32111111-1111-4111-8111-111111111105'::uuid,'GIS-DEV-005','ROAD 기준','LINESTRING(127.1570 36.8180,127.1590 36.8190)'),
 ('32111111-1111-4111-8111-111111111106'::uuid,'GIS-DEV-006','SURVEY 도로 기준','LINESTRING(127.1595 36.8197,127.1605 36.8203)')
) v(id,project_code,label,wkt)
JOIN prj.projects p ON p.code=v.project_code
ON CONFLICT (id) DO UPDATE SET project_id=EXCLUDED.project_id,source_type=EXCLUDED.source_type,etctxt=EXCLUDED.etctxt,geom=EXCLUDED.geom,updated_at=now();

INSERT INTO gis.wtl_pipe_lm(id,project_id,ftr_cde,ftr_idn,source_name,source_key,description,ext_data,geom)
SELECT '44111111-1111-4111-8111-111111111102'::uuid,p.id,NULL,NULL,'synthetic','WTL-PIPE-P002','WATER-only project pipe','{"synthetic":true}'::jsonb,
       ST_GeomFromText('LINESTRING(127.1517 36.8158,127.1524 36.8162)',4326)
FROM prj.projects p WHERE p.code='GIS-DEV-002'
ON CONFLICT (id) DO UPDATE SET project_id=EXCLUDED.project_id,ftr_cde=NULL,ftr_idn=NULL,source_key=EXCLUDED.source_key,description=EXCLUDED.description,ext_data=EXCLUDED.ext_data,geom=EXCLUDED.geom,updated_at=now();

INSERT INTO gis.wtl_valv_ps(id,project_id,ftr_cde,ftr_idn,source_name,source_key,description,ext_data,geom)
SELECT '44211111-1111-4111-8111-111111111102'::uuid,p.id,NULL,NULL,'synthetic','WTL-VALV-P002','WATER-only project valve','{"synthetic":true}'::jsonb,
       ST_SetSRID(ST_MakePoint(127.1521,36.8160),4326)
FROM prj.projects p WHERE p.code='GIS-DEV-002'
ON CONFLICT (id) DO UPDATE SET project_id=EXCLUDED.project_id,ftr_cde=NULL,ftr_idn=NULL,source_key=EXCLUDED.source_key,description=EXCLUDED.description,ext_data=EXCLUDED.ext_data,geom=EXCLUDED.geom,updated_at=now();

INSERT INTO gis.swl_pipe_lm(id,project_id,ftr_cde,ftr_idn,source_name,source_key,description,ext_data,geom)
SELECT '54111111-1111-4111-8111-111111111103'::uuid,p.id,NULL,NULL,'synthetic','SWL-PIPE-P003','SEWER-only project pipe','{"synthetic":true}'::jsonb,
       ST_GeomFromText('LINESTRING(127.1537 36.8168,127.1544 36.8172)',4326)
FROM prj.projects p WHERE p.code='GIS-DEV-003'
ON CONFLICT (id) DO UPDATE SET project_id=EXCLUDED.project_id,ftr_cde=NULL,ftr_idn=NULL,source_key=EXCLUDED.source_key,description=EXCLUDED.description,ext_data=EXCLUDED.ext_data,geom=EXCLUDED.geom,updated_at=now();

INSERT INTO gis.swl_manh_ps(id,project_id,ftr_cde,ftr_idn,source_name,source_key,description,ext_data,geom)
SELECT '54211111-1111-4111-8111-111111111103'::uuid,p.id,NULL,NULL,'synthetic','SWL-MANH-P003','SEWER-only project manhole','{"synthetic":true}'::jsonb,
       ST_SetSRID(ST_MakePoint(127.1541,36.8170),4326)
FROM prj.projects p WHERE p.code='GIS-DEV-003'
ON CONFLICT (id) DO UPDATE SET project_id=EXCLUDED.project_id,ftr_cde=NULL,ftr_idn=NULL,source_key=EXCLUDED.source_key,description=EXCLUDED.description,ext_data=EXCLUDED.ext_data,geom=EXCLUDED.geom,updated_at=now();

COMMIT;
