"""Isolated PostGIS regression. Requires a disposable localhost cluster.
Never imports runtime settings or resolves production credentials.
"""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
if os.environ.get("GEOFLOW_RUN_ISOLATED_POSTGIS") != "1":
    raise unittest.SkipTest("Explicit disposable PostGIS opt-in required")
import psycopg2
from django.conf import settings
PORT = int(os.environ.get('GEOFLOW_TEST_PGPORT','55439'))
if not 55000 <= PORT <= 55999:
    raise RuntimeError('Use a dedicated local test port in 55000..55999')
DBS = {'default':'geoflow_business_central_test','tenant':'geoflow_business_tenant_test',
       'other_tenant':'geoflow_business_other_tenant_test'}
admin = psycopg2.connect(host='127.0.0.1',port=PORT,user='geoflow_test',dbname='postgres')
admin.autocommit=True
with admin.cursor() as cur:
    for name in DBS.values():
        cur.execute('SELECT 1 FROM pg_database WHERE datname=%s',[name])
        if not cur.fetchone(): cur.execute('CREATE DATABASE '+name)
admin.close()
settings.configure(SECRET_KEY='isolated-test-only',DEBUG=True,USE_TZ=True,
    CENTRAL_DB_ALIAS='default',
    INSTALLED_APPS=['django.contrib.auth','django.contrib.contenttypes','control','geoflow_ops'],
    DATABASES={a:dict(ENGINE='django.db.backends.postgresql',NAME=n,HOST='127.0.0.1',PORT=PORT,USER='geoflow_test') for a,n in DBS.items()},
    GDAL_LIBRARY_PATH=os.environ.get('GDAL_LIBRARY_PATH'),GEOS_LIBRARY_PATH=os.environ.get('GEOS_LIBRARY_PATH'))
import django
django.setup()
from django.db import connections
from geoflow_ops.gis import business_fields as bf, workers, reference_catalog, gpkg
from geoflow_ops.gis.qgis_sync import SyncOperation, SyncRejected, _apply_operation
from geoflow_ops.gis.qgis_views import qgis_projects_api


class BusinessContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project=str(uuid4());cls.user=str(uuid4());cls.employee=str(uuid4());cls.other=str(uuid4())
        cls.foreign_employee=str(uuid4())
        with connections['other_tenant'].cursor() as cur:
            cur.execute('DROP SCHEMA IF EXISTS hr CASCADE; CREATE SCHEMA hr; CREATE TABLE hr.employee_profile(id uuid PRIMARY KEY,email text,name text,is_deleted bool DEFAULT false)')
            cur.execute('INSERT INTO hr.employee_profile VALUES(%s,%s,%s,false)',[cls.foreign_employee,'foreign@example.invalid','Foreign worker'])
        with connections['default'].cursor() as cur:
            cur.execute('DROP TABLE IF EXISTS users')
            cur.execute('CREATE TABLE users(id uuid PRIMARY KEY,email text,name_display text)')
            cur.execute('INSERT INTO users VALUES(%s,%s,%s)',[cls.user,'test@example.invalid','Account'])
        with connections['tenant'].cursor() as cur:
            cur.execute('CREATE EXTENSION IF NOT EXISTS postgis')
            cur.execute('DROP SCHEMA IF EXISTS gis CASCADE; DROP SCHEMA IF EXISTS prj CASCADE; DROP SCHEMA IF EXISTS hr CASCADE')
            cur.execute('CREATE SCHEMA prj; CREATE SCHEMA hr; CREATE TABLE prj.projects(id uuid PRIMARY KEY); CREATE TABLE hr.employee_profile(id uuid PRIMARY KEY,email text,name text,is_deleted bool DEFAULT false,updated_at timestamptz,created_at timestamptz)')
            cur.execute('INSERT INTO prj.projects VALUES(%s)',[cls.project])
            cur.execute('INSERT INTO hr.employee_profile(id,email,name) VALUES(%s,%s,%s),(%s,%s,%s)',[cls.employee,'test@example.invalid','Worker',cls.other,'other@example.invalid','Other'])
            for file in ('gis-schema-foundation.sql','gis-initial-feature-tables-v0.1.sql','gis-metadata-seed-v0.1.sql','gis-sync-revision-v1.sql'):
                sql=(ROOT/'docs/architecture'/file).read_text(encoding='utf-8-sig').replace('\\encoding UTF8','')
                cur.execute(sql)
            cur.execute('CREATE TABLE gis.project_profile(project_id uuid,profile_id uuid,status text)')
            keys={v for m in bf.REFERENCES.values() for v in m.values()}|{'GEOFLOW.WORK_STATUS'}
            for key in sorted(keys):
                gid=str(uuid4());cur.execute('INSERT INTO gis.ref_code_group(id,group_key,name) VALUES(%s,%s,%s)',[gid,key,key])
                pairs=[('todo','미완료'),('done','완료'),('fix','보완필요')] if key=='GEOFLOW.WORK_STATUS' else [('A','Approved')]
                for code,label in pairs:cur.execute('INSERT INTO gis.ref_code_value(id,group_id,code,label) VALUES(%s,%s,%s,%s)',[str(uuid4()),gid,code,label])
        cls.request=NS(user=NS(is_authenticated=True,email='test@example.invalid',pk=7),session={})

    def setUp(self):
        # Every test rolls back its changes, including transactional DDL.
        connections['tenant'].set_autocommit(False)

    def tearDown(self):
        connections['tenant'].rollback();connections['tenant'].set_autocommit(True)
        if getattr(self, '_committed_snapshot_test', False):
            self.setUpClass()

    def reconcile(self):
        with connections['tenant'].cursor() as cur:return bf.reconcile(cur,self.project)

    def plan(self):
        with connections['tenant'].cursor() as cur:
            state=bf.inspect_contract(cur,self.project)
        return {'profile':{'id':state['profile']},'layers':[dict(standard_name=t.upper(),physical_name=t,label=t,domain='WTL',geometry_kind='LINE' if t=='wtl_pipe_lm' else 'POINT') for t in bf.TABLES]}

    def test_reconcile_repeat_and_permissions_preserved(self):
        with connections['tenant'].cursor() as cur:
            cur.execute("UPDATE gis.profile_field SET editable=false,visible=false,enabled=false,sort_order=17 WHERE field_def_id IN (SELECT id FROM gis.meta_field_def WHERE physical_name='ist_ymd')")
            cur.execute("SELECT id::text FROM gis.meta_field_def WHERE physical_name='ist_ymd' AND feature_type_id=(SELECT id FROM gis.meta_feature_type WHERE physical_name='wtl_pipe_lm')")
            before=cur.fetchone()[0]
        self.assertGreater(self.reconcile(),0);self.assertEqual(self.reconcile(),0)
        with connections['tenant'].cursor() as cur:
            cur.execute('SELECT fd.physical_name,pf.editable,pf.visible,pf.enabled,pf.sort_order FROM gis.meta_field_def fd JOIN gis.profile_field pf ON pf.field_def_id=fd.id WHERE fd.id=%s',[before])
            self.assertEqual(cur.fetchone(),('date',False,False,False,17))
            cur.execute("SELECT count(*) FROM gis.meta_field_def WHERE physical_name='ist_ymd' AND feature_type_id=(SELECT id FROM gis.meta_feature_type WHERE physical_name='swl_pipe_lm')")
            self.assertEqual(cur.fetchone()[0],1)

    def test_both_columns_conflict_no_mutation(self):
        with connections['tenant'].cursor() as cur:cur.execute('ALTER TABLE gis.wtl_pipe_lm ADD date date')
        with self.assertRaises(bf.ContractConflict):self.reconcile()
        with connections['tenant'].cursor() as cur:
            cur.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema='gis' AND table_name='wtl_etc_ps' AND column_name='worker_id'")
            self.assertEqual(cur.fetchone()[0],0)

    def test_preflight_shared_profile_defaults_constraints_and_data(self):
        with connections['tenant'].cursor() as cur:
            before=bf.inspect_contract(cur,self.project)
            profile=before['profile'];other_project=str(uuid4())
            cur.execute('INSERT INTO prj.projects VALUES(%s)',[other_project])
            cur.execute("INSERT INTO gis.project_profile VALUES(%s,%s,'active')",[other_project,profile])
            cur.execute("ALTER TABLE gis.wtl_pipe_lm ALTER sys_chk SET DEFAULT 'todo'")
            cur.execute("ALTER TABLE gis.wtl_pipe_lm ADD CONSTRAINT work_status_review CHECK(sys_chk IS NULL OR sys_chk IN ('todo','done','fix'))")
            cur.execute("INSERT INTO gis.wtl_pipe_lm(id,project_id,ist_ymd) VALUES(%s,%s,'2001-02-03')",[str(uuid4()),self.project])
            before=bf.inspect_contract(cur,self.project)
            self.assertEqual(before['profile_impact'],dict(explicit_projects=1,fallback_projects=1,other_effective_projects=1))
            bf.reconcile(cur,self.project)
            after=bf.inspect_contract(cur,self.project)
            old=before['tables']['wtl_pipe_lm'];new=after['tables']['wtl_pipe_lm']
            self.assertEqual(old['counts']['ist_ymd_fingerprint'],new['counts']['date_fingerprint'])
            self.assertEqual(old['counts']['sys_chk_fingerprint'],new['counts']['status_fingerprint'])
            self.assertEqual(old['column_details']['sys_chk']['default'],new['column_details']['status']['default'])
            self.assertIn('work_status_review',dict(new['constraints']))
            cur.execute('ALTER TABLE gis.wtl_pipe_lm ALTER date SET DEFAULT CURRENT_DATE')
            with self.assertRaises(bf.ContractConflict):bf.plan_contract(bf.inspect_contract(cur,self.project))

    def test_both_metadata_conflict_reports_profiles(self):
        with connections['tenant'].cursor() as cur:
            cur.execute("INSERT INTO gis.meta_field_def(id,feature_type_id,physical_name,standard_name,label,data_type) SELECT %s,feature_type_id,'date','DATE','Work','date' FROM gis.meta_field_def WHERE physical_name='ist_ymd' AND feature_type_id=(SELECT id FROM gis.meta_feature_type WHERE physical_name='wtl_pipe_lm')",[str(uuid4())])
        with self.assertRaises(bf.ContractConflict) as caught:self.reconcile()
        self.assertTrue(any(c.get('reason')=='both_metadata_definitions' and 'links' in c for c in caught.exception.conflicts))

    def test_already_renamed_column_repairs_stale_metadata(self):
        with connections['tenant'].cursor() as cur:
            cur.execute('ALTER TABLE gis.wtl_pipe_lm RENAME ist_ymd TO date')
            cur.execute('INSERT INTO gis.wtl_pipe_lm(id,project_id,date) VALUES(%s,%s,%s)',[str(uuid4()),self.project,'2001-02-03'])
        self.reconcile()
        with connections['tenant'].cursor() as cur:
            cur.execute('SELECT date::text FROM gis.wtl_pipe_lm WHERE project_id=%s',[self.project]);self.assertEqual(cur.fetchone()[0],'2001-02-03')

    def test_reference_conflict_preserved(self):
        with connections['tenant'].cursor() as cur:cur.execute("UPDATE gis.meta_field_def SET code_group_key='OTHER' WHERE physical_name='saa_cde'")
        with self.assertRaises(bf.ContractConflict):self.reconcile()

    def test_removed_field_disabled_only_in_effective_profile(self):
        other_profile=str(uuid4())
        with connections['tenant'].cursor() as cur:
            cur.execute("INSERT INTO gis.profile(id,code,name) VALUES(%s,'OTHER','Other')",[other_profile])
            cur.execute("SELECT id::text FROM gis.meta_field_def WHERE physical_name='description' AND feature_type_id=(SELECT id FROM gis.meta_feature_type WHERE physical_name='wtl_pipe_lm')")
            fid=cur.fetchone()[0]
            cur.execute('INSERT INTO gis.profile_field(id,profile_id,field_def_id) VALUES(%s,%s,%s)',[str(uuid4()),other_profile,fid])
            cur.execute('ALTER TABLE gis.wtl_pipe_lm DROP COLUMN description')
        self.reconcile()
        with connections['tenant'].cursor() as cur:
            cur.execute('SELECT profile_id::text,enabled FROM gis.profile_field WHERE field_def_id=%s',[fid]);links=dict(cur.fetchall())
        self.assertTrue(links.pop(other_profile));self.assertEqual(list(links.values()),[False])

    def test_approved_reference_and_empty_scope(self):
        self.reconcile()
        catalog=reference_catalog.project_reference_catalog(using='tenant',standard_names=['WTL_PIPE_LM'])
        self.assertEqual({g['code_group_key'] for g in catalog['groups']},{'WTL_PIPE_LM.SAA_CDE','WTL_PIPE_LM.MOP_CDE','GEOFLOW.WORK_STATUS'})
        with patch.object(reference_catalog,'connections') as db:
            result=reference_catalog.project_reference_catalog(using='tenant',standard_names=set())
            self.assertEqual(result['groups'],[]);db.__getitem__.assert_not_called()
        self.assertGreater(reference_catalog.project_reference_catalog(using='tenant',standard_names=None)['group_count'],3)

    def test_linked_unlinked_ambiguous(self):
        self.assertEqual(workers.current_user_context(self.request,'tenant')['worker_id'],self.employee)
        req=NS(user=NS(is_authenticated=True,email='absent@example.invalid'),session={})
        self.assertEqual(workers.current_user_context(req,'tenant')['worker_link_status'],'unlinked')
        with connections['tenant'].cursor() as cur:cur.execute('INSERT INTO hr.employee_profile(id,email,name) VALUES(%s,%s,%s)',[str(uuid4()),'TEST@example.invalid','Duplicate'])
        info=workers.current_user_context(self.request,'tenant')
        self.assertEqual(info['worker_link_status'],'ambiguous');self.assertIsNone(info['worker_id'])

    def test_project_list_contract_extended(self):
        qs=NS(filter=lambda **kw:[],__getitem__=lambda s,k:[])
        with patch('geoflow_ops.gis.qgis_views._require_qgis_context',return_value='tenant'),patch('geoflow_ops.gis.qgis_views._project_queryset',return_value=[]),patch('geoflow_ops.gis.qgis_views.gis_enabled_project_ids',return_value=None),patch('geoflow_ops.gis.qgis_views.project_access_policy',return_value=NS(visible_project_ids=lambda:None,mode='worker')):
            self.request.method='GET'
            import json
            data=json.loads(qgis_projects_api(self.request).content)
        self.assertEqual(data['results'],[]);self.assertEqual(data['count'],0);self.assertEqual(data['scope'],'worker')
        self.assertEqual(data['current_user']['user_id'],self.user);self.assertEqual(data['current_user']['employee_id'],self.employee)

    def test_cross_tenant_deleted_and_permission_validation(self):
        self.reconcile()
        policy=NS(can_webgis_write=lambda _:True,can_edit_project=lambda _:False)
        def check(value):workers.validate_worker_assignment('tenant',self.project,SyncOperation('create','wtl_pipe_lm','WTL_PIPE_LM',str(uuid4()),{'worker_id':value},None),self.request)
        with patch.object(workers,'project_access_policy',return_value=policy):
            check(self.employee)
            for value in (self.other,self.project,str(uuid4()),'7'):
                with self.subTest(value=value),self.assertRaises(SyncRejected):check(value)
            policy.can_edit_project=lambda _:True
            check(self.other)
            with self.assertRaises(SyncRejected):check(self.foreign_employee)
            with self.assertRaises(SyncRejected):check(str(uuid4()))
            with connections['tenant'].cursor() as cur:cur.execute('UPDATE hr.employee_profile SET is_deleted=true WHERE id=%s',[self.other])
            with self.assertRaises(SyncRejected):check(self.other)

    def test_existing_unresolved_worker_survives_unrelated_write(self):
        self.reconcile();obj=str(uuid4())
        with connections['tenant'].cursor() as cur:cur.execute('INSERT INTO gis.wtl_pipe_lm(id,project_id,worker_id) VALUES(%s,%s,%s)',[obj,self.project,self.project])
        _apply_operation('tenant',self.project,SyncOperation('update','wtl_pipe_lm','WTL_PIPE_LM',obj,{'description':'changed'},None))
        with connections['tenant'].cursor() as cur:
            cur.execute('SELECT worker_id::text,description FROM gis.wtl_pipe_lm WHERE id=%s',[obj]);self.assertEqual(cur.fetchone(),(self.project,'changed'))
        _apply_operation('tenant',self.project,SyncOperation('update','wtl_pipe_lm','WTL_PIPE_LM',obj,{'worker_id':self.project},None))

    def test_scoped_worker_names(self):
        self.reconcile()
        with connections['tenant'].cursor() as cur:cur.execute('INSERT INTO gis.wtl_pipe_lm(id,project_id,worker_id) VALUES(%s,%s,%s)',[str(uuid4()),self.project,self.project])
        current,rows=workers.project_workers(self.request,'tenant',self.project,self.plan())
        self.assertEqual({r['id'] for r in rows},{self.project,self.employee})
        self.assertFalse(next(r for r in rows if r['id']==self.project)['resolved'])
        self.assertNotIn(self.other,{r['id'] for r in rows})

    def test_changeset_geometry_only_then_business_save_and_replay(self):
        from geoflow_ops.gis.changeset import apply_project_changeset, project_delta
        self.reconcile();plan=self.plan()
        policy=NS(can_webgis_write=lambda _:True,can_edit_project=lambda _:False)
        os.environ['GEOFLOW_DEV_RUNTIME_STRICT']='1'
        changes=[]
        with connections['tenant'].cursor() as cur:
            for table in bf.TABLES:
                wkt='LINESTRING(127 37,127.01 37.01)' if table=='wtl_pipe_lm' else 'POINT(127 37)'
                cur.execute("SELECT encode(ST_AsBinary(ST_GeomFromText(%s,4326)),'hex')",[wkt])
                changes.append(dict(action='create',layer=table.upper(),id=str(uuid4()),geometry_wkb=cur.fetchone()[0],attributes={}))
        def payload(items):return dict(client_id=self.user,changeset_id=str(uuid4()),changes=items)
        with patch.object(workers,'project_access_policy',return_value=policy):
            result=apply_project_changeset('tenant',project_id=self.project,plan=plan,payload=payload(changes),request=self.request)
            self.assertEqual(result['created'],5)
            with connections['tenant'].cursor() as cur:
                for table in bf.TABLES:
                    cur.execute(f'SELECT date,worker_id FROM gis."{table}" WHERE project_id=%s',[self.project]);self.assertEqual(cur.fetchone(),(None,None))
            edits=[dict(action='update',layer=c['layer'],id=c['id'],attributes={'date':'2026-09-14','status':'todo','worker_id':self.employee}) for c in changes]
            body=payload(edits)
            result=apply_project_changeset('tenant',project_id=self.project,plan=plan,payload=body,request=self.request)
            self.assertEqual(result['updated'],5)
            replay=apply_project_changeset('tenant',project_id=self.project,plan=plan,payload=body,request=self.request)
            self.assertTrue(replay['replayed'])
            bad=payload([dict(action='update',layer=changes[0]['layer'],id=changes[0]['id'],attributes={'worker_id':self.project})])
            with self.assertRaises(SyncRejected):apply_project_changeset('tenant',project_id=self.project,plan=plan,payload=bad,request=self.request)
        delta=project_delta('tenant',project_id=self.project,since_revision=0)
        self.assertEqual(delta['current_revision'],10)
        from geoflow_ops.gis.gpkg_syncable import build_syncable_project_geopackage
        connections['tenant'].commit()
        connections['tenant'].set_autocommit(True)
        self._committed_snapshot_test = True
        package,metadata=build_syncable_project_geopackage('tenant',project_id=self.project,plan=plan)
        self.assertTrue(package.startswith(b'SQLite format 3'))

    def test_manifest_and_real_geopackage_five_layers(self):
        self.reconcile();plan=self.plan()
        manifest=gpkg.project_geopackage_layer_manifest('tenant',plan)
        self.assertEqual(len(manifest),5)
        for layer in manifest:
            fields={f['name']:f for f in layer['fields']}
            self.assertTrue({'date','status','worker_id'}<=fields.keys())
            self.assertNotIn('ist_ymd',fields);self.assertNotIn('sys_chk',fields)
            self.assertEqual(fields['status']['code_group_key'],'GEOFLOW.WORK_STATUS')
        payload,metadata=gpkg.build_project_geopackage('tenant',project_id=self.project,plan=plan)
        self.assertTrue(payload.startswith(b'SQLite format 3'));self.assertEqual(len(metadata),5)


if __name__=='__main__':
    try:unittest.main()
    finally:connections.close_all()
