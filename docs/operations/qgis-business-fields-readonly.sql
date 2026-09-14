-- Run with psql -v project_id=<verified-project-uuid> using the official tenant
-- connection. Read-only; do not paste connection credentials into this file.
\set ON_ERROR_STOP on
BEGIN TRANSACTION READ ONLY;
SET LOCAL statement_timeout='30s';
SELECT current_database() AS connected_database;
SELECT id, code, name, status FROM prj.projects WHERE id=:'project_id'::uuid;
SELECT p.id,p.code,pp.status AS assignment_status
FROM gis.project_profile pp JOIN gis.profile p ON p.id=pp.profile_id
WHERE pp.project_id=:'project_id'::uuid;
SELECT id,code,active FROM gis.profile
WHERE code IN ('GEOFLOW_BASE_V1','GEOFLOW_DEV_BASE');
SELECT table_name,column_name,data_type,udt_name,is_nullable,column_default
FROM information_schema.columns WHERE table_schema='gis'
AND table_name IN ('wtl_etc_ps','wtl_fire_ps','wtl_flow_ps','wtl_pipe_lm','wtl_valv_ps')
ORDER BY table_name,ordinal_position;
SELECT ft.physical_name AS layer,fd.id AS field_definition,fd.physical_name,
       fd.data_type,fd.code_group_key,p.code AS profile,pf.enabled,pf.required,
       pf.editable,pf.visible,pf.sort_order,(c.column_name IS NULL) AS stale_definition
FROM gis.meta_feature_type ft JOIN gis.meta_field_def fd ON fd.feature_type_id=ft.id
LEFT JOIN gis.profile_field pf ON pf.field_def_id=fd.id
LEFT JOIN gis.profile p ON p.id=pf.profile_id
LEFT JOIN information_schema.columns c ON c.table_schema='gis'
 AND c.table_name=ft.physical_name AND c.column_name=fd.physical_name
WHERE ft.physical_name IN ('wtl_etc_ps','wtl_fire_ps','wtl_flow_ps','wtl_pipe_lm','wtl_valv_ps')
ORDER BY ft.physical_name,fd.physical_name,p.code;
SELECT g.group_key,g.active,v.code,v.label,v.active AS value_active,v.valid_from,v.valid_to
FROM gis.ref_code_group g LEFT JOIN gis.ref_code_value v ON v.group_id=g.id
WHERE g.group_key='GEOFLOW.WORK_STATUS'
 OR split_part(g.group_key,'.',1) IN ('WTL_ETC_PS','WTL_FIRE_PS','WTL_FLOW_PS','WTL_PIPE_LM','WTL_VALV_PS')
ORDER BY g.group_key,v.sort_order,v.code;
-- Generate aggregate-only statements for columns which actually exist.
-- No employee identifiers/names or raw facility records are returned.
SELECT format(
 'SELECT %L AS layer,count(*) AS total,count(*) FILTER (WHERE t.worker_id IS NOT NULL) AS assigned,count(*) FILTER (WHERE t.worker_id IS NOT NULL AND e.id IS NULL) AS unresolved,count(*) FILTER (WHERE t.worker_id::text=t.project_id::text) AS equals_project_id FROM gis.%I t LEFT JOIN hr.employee_profile e ON e.id::text=t.worker_id::text AND e.is_deleted=false WHERE t.project_id=%L::uuid',
 c.table_name,c.table_name,:'project_id')
FROM information_schema.columns c WHERE c.table_schema='gis' AND c.column_name='worker_id'
AND c.table_name IN ('wtl_etc_ps','wtl_fire_ps','wtl_flow_ps','wtl_pipe_lm','wtl_valv_ps')
\gexec
-- Effective profile sharing includes projects that use the fallback profile.
WITH fallback AS (
 SELECT id FROM gis.profile WHERE active AND code IN ('GEOFLOW_BASE_V1','GEOFLOW_DEV_BASE')
 ORDER BY CASE code WHEN 'GEOFLOW_BASE_V1' THEN 0 ELSE 1 END LIMIT 1
), explicit_profiles AS (
 SELECT pp.project_id,pp.profile_id FROM gis.project_profile pp
 JOIN gis.profile p ON p.id=pp.profile_id AND p.active WHERE pp.status='active'
), effective AS (
 SELECT project_id,profile_id FROM explicit_profiles
 UNION ALL
 SELECT p.id,f.id FROM prj.projects p CROSS JOIN fallback f
 WHERE NOT EXISTS(SELECT 1 FROM explicit_profiles ep WHERE ep.project_id=p.id)
)
SELECT p.id,p.code,count(DISTINCT e.project_id) AS projects_using_profile,
 count(DISTINCT e.project_id) FILTER(WHERE e.project_id<>:'project_id'::uuid) AS other_projects
FROM effective e JOIN gis.profile p ON p.id=e.profile_id
WHERE e.profile_id IN (SELECT profile_id FROM effective WHERE project_id=:'project_id'::uuid)
GROUP BY p.id,p.code;
-- All other profiles using common definitions are included above; do not
-- interpret a project-scoped invocation as project-scoped physical DDL.
SELECT ft.physical_name,fd.physical_name,fd.id,count(DISTINCT pf.profile_id) AS profiles_using_definition,
 array_agg(DISTINCT p.code) FILTER(WHERE p.code IS NOT NULL) AS profiles
FROM gis.meta_feature_type ft JOIN gis.meta_field_def fd ON fd.feature_type_id=ft.id
LEFT JOIN gis.profile_field pf ON pf.field_def_id=fd.id LEFT JOIN gis.profile p ON p.id=pf.profile_id
WHERE ft.physical_name IN ('wtl_etc_ps','wtl_fire_ps','wtl_flow_ps','wtl_pipe_lm','wtl_valv_ps')
AND fd.physical_name IN ('date','status','worker_id','ist_ymd','sys_chk')
GROUP BY ft.physical_name,fd.physical_name,fd.id ORDER BY ft.physical_name,fd.physical_name;
SELECT c.relname,k.conname,pg_get_constraintdef(k.oid) AS definition
FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='gis' AND c.relname IN ('wtl_etc_ps','wtl_fire_ps','wtl_flow_ps','wtl_pipe_lm','wtl_valv_ps')
ORDER BY c.relname,k.conname;
SELECT c.relname,t.tgname,pg_get_triggerdef(t.oid) AS definition
FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='gis' AND NOT t.tgisinternal
AND c.relname IN ('wtl_etc_ps','wtl_fire_ps','wtl_flow_ps','wtl_pipe_lm','wtl_valv_ps')
ORDER BY c.relname,t.tgname;
-- Aggregate fingerprints aid comparison across renames; they are not backups.
SELECT format('SELECT %L AS layer,%L AS field,count(*) FILTER(WHERE %I IS NOT NULL) AS nonnull,bit_xor(hashtextextended(%I::text,0)) AS fingerprint FROM gis.%I',
 table_name,column_name,column_name,column_name,table_name)
FROM information_schema.columns WHERE table_schema='gis'
AND table_name IN ('wtl_etc_ps','wtl_fire_ps','wtl_flow_ps','wtl_pipe_lm','wtl_valv_ps')
AND column_name IN ('date','status','ist_ymd','sys_chk')
\gexec
ROLLBACK;
