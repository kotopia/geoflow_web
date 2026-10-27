"""Isolated PostGIS rehearsal of the real Survey services, never a live database."""
import importlib.util
import os
import sqlite3
from contextlib import closing
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
if os.getenv('GEOFLOW_SURVEY_TEST_PG') != '1':
    raise SystemExit('GEOFLOW_SURVEY_TEST_PG=1 required; disposable loopback DB only')
from django.conf import settings
settings.configure(SECRET_KEY='isolated-survey-test', DEBUG=False, INSTALLED_APPS=[],
    DATABASES={'default': {'ENGINE':'django.db.backends.postgresql', 'NAME':'survey_final_test',
    'USER':'survey_test', 'PASSWORD':'survey_test', 'HOST':'127.0.0.1', 'PORT':'55448'}})
import django
django.setup()
from django.db import connections, transaction, IntegrityError
from django.test.utils import CaptureQueriesContext
from geoflow_ops.gis.survey_sources import import_survey_source, delete_survey_points, delete_survey_source
from geoflow_ops.gis.survey_sources import list_survey_sources, survey_source_delete_precheck
from geoflow_ops.gis.survey_final import decimal_input, survey_method
from geoflow_ops.gis.survey_backfill import backfill_survey_project
from geoflow_ops.gis.changeset import project_delta, apply_project_changeset, _reserve_receipt, _insert_change_log, _allocate_revisions
from geoflow_ops.gis.gpkg_snapshot_file import build_project_geopackage_file
from geoflow_ops.gis.qgis_sync import SyncRejected
from control.management.commands.deploy_gis_survey_lineage import survey_elevation_count
from control.management.commands.deploy_gis_survey_final_fields import final_fields_pending
from control.management.commands.inspect_gis_definition_rows import inventory, TABLES
from control.management.commands.deploy_gis_survey_target_removal import (migration as retirement_migration, pending as retirement_pending, preserved_inventory, backup_rows, apply_removal, restore)


def bootstrap():
    with connections['default'].cursor() as c:
        c.execute('SELECT current_database()')
        assert c.fetchone()[0] == 'survey_final_test'
        c.execute('CREATE EXTENSION IF NOT EXISTS postgis; CREATE SCHEMA prj; CREATE SCHEMA gis; CREATE SCHEMA hr;')
        c.execute('CREATE TABLE prj.projects(id uuid PRIMARY KEY); CREATE TABLE hr.employee_profile(id uuid PRIMARY KEY,name text,is_deleted boolean DEFAULT false);')
        for name in ('0044_gis_survey_lineage','0045_gis_survey_soft_delete','0046_gis_survey_final_fields'):
            spec = importlib.util.spec_from_file_location(name, ROOT/'geoflow_ops/migrations'/f'{name}.py')
            module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            c.execute(module.Migration.operations[0].sql)
        c.execute('CREATE TABLE gis.definition_layer(id uuid PRIMARY KEY,physical_name text,label text)')
        c.execute('CREATE TABLE gis.definition_field(id uuid PRIMARY KEY,source_layer_id uuid,physical_name text,label text,readonly boolean,updated_at timestamptz DEFAULT now())')
        for table in TABLES:
            if table not in ('definition_layer','definition_field'):
                c.execute(f'CREATE TABLE gis.{table}(id uuid PRIMARY KEY,payload jsonb)')
        layer=str(uuid4())
        c.execute("INSERT INTO gis.definition_layer VALUES (%s,'survey','Survey')",[layer])
        for name in ('survey_no','type','x','y','z','raw_x'):
            c.execute('INSERT INTO gis.definition_field(id,source_layer_id,physical_name,label,readonly) VALUES (%s,%s,%s,%s,false)',[str(uuid4()),layer,name,name])
        # Current live stores omit this optional legacy foundation column.
        c.execute('ALTER TABLE gis.survey DROP COLUMN survey_code')
        c.execute("CREATE TABLE django_migrations(app text,name text,applied timestamptz)")
        c.execute("INSERT INTO django_migrations(app,name,applied) VALUES ('webgisapp','0046_gis_survey_final_fields',now())")
        sql = (ROOT/'docs/architecture/gis-sync-revision-v1.sql').read_text()
        c.execute(sql[sql.index('CREATE TABLE IF NOT EXISTS gis.project_sync_state'):sql.index('COMMIT;')])
        c.execute(retirement_migration().FORWARD_SQL)
        c.execute("INSERT INTO django_migrations(app,name,applied) VALUES ('webgisapp','0047_remove_survey_targets',now())")
        for table in ('wtl_pipe_ps','wtl_valv_ps'):
            c.execute(f'CREATE TABLE gis.{table}(id uuid PRIMARY KEY,project_id uuid NOT NULL,description text,geom geometry(Point,4326),created_at timestamptz DEFAULT now(),updated_at timestamptz DEFAULT now())')



def plan():
    names = {'id':'uuid','project_id':'uuid','survey_no':'varchar(30)','type':'varchar(20)',
             'raw_x':'numeric','raw_y':'numeric','raw_z':'numeric', 'x':'numeric','y':'numeric','z':'numeric',
             'longitude':'double precision','latitude':'double precision','antenna_height':'numeric',
             'survey_date':'date','code':'varchar(30)','raw_code':'text'}
    fields = [{'id':str(uuid4()),'layer_id':'survey','field_name':name,'storage_data_type':kind,
               'storage':{'kind':'column','key':name},'readonly':True,'visible':True}
              for name,kind in names.items()]
    return {'layers':[{'id':'survey','standard_name':'SURVEY','physical_name':'survey','geometry_kind':'POINT'}],
            'definition':{'revision':'final-fields'}, 'form_definition':{'revision':'final-fields','fields':fields}}


class SurveyFinalTests(unittest.TestCase):
    def test_inventory_separates_retained_deleted_and_active(self):
        result = self.run_import(self.payload(count=2))
        source = result['source_id']
        self.assertEqual(survey_source_delete_precheck('default', project_id=self.project, source_id=source)['deletion_policy'], 'source_and_points_soft_delete_v1')
        delete_survey_points('default', project_id=self.project, survey_ids=[result['points'][0]['id']])
        inventory = list_survey_sources('default', project_id=self.project, include_deleted=True)
        self.assertEqual((inventory[0]['point_count'], inventory[0]['deleted_point_count']), (1, 1))
        # Historical preservation fixture, never a new production deletion policy.
        with connections['default'].cursor() as c:
            c.execute("UPDATE gis.survey_source SET deleted_at=now(),delete_reason='isolated_retained_fixture' WHERE id=%s", [source])
        self.assertEqual(list_survey_sources('default', project_id=self.project), [])
        inventory = list_survey_sources('default', project_id=self.project, include_deleted=True)
        self.assertEqual(inventory[0]['point_count'], 1)
        # Execute the actual route body against PostGIS without booting unrelated apps.
        import ast
        import json
        from types import SimpleNamespace
        from django.http import JsonResponse
        tree = ast.parse((ROOT/'geoflow_ops/gis/survey_views.py').read_text(encoding='utf-8'))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'project_survey_points_api')
        function.decorator_list = []
        namespace = {'connections': connections, 'JsonResponse': JsonResponse,
                     '_context': lambda request, pid: ('default', SimpleNamespace(id=pid), {})}
        exec(compile(ast.Module(body=[function], type_ignores=[]), 'survey_views.py', 'exec'), namespace)
        response = namespace['project_survey_points_api'](SimpleNamespace(GET={'source_state':'retained'}), self.project)
        rows = json.loads(response.content)['points']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['source_state'], 'deleted')
        self.assertEqual(rows[0]['current_crs'], 'EPSG:5186')

    def setUp(self):
        self.project = str(uuid4())
        with connections['default'].cursor() as c:
            c.execute('INSERT INTO prj.projects(id) VALUES (%s)',[self.project])

    def payload(self, count=1, **changes):
        value = {'source_type':'GNSS','original_file_name':'survey.csv','source_crs':'EPSG:5186',
                 'survey_date':'2025-10-17', 'points':[{'source_row_id':f'P{i:03}',
                 'raw_x':'235768.352','raw_y':'413130.660','raw_z':'49.196',
                 'antenna_height':0,'raw_code':'V'} for i in range(count)]}
        value.update(changes)
        return value

    def run_import(self, payload):
        return import_survey_source('default',project_id=self.project,payload=payload)

    def test_inventory_accepts_only_authorized_five_field_transition(self):
        with transaction.atomic():
            with connections['default'].cursor() as c:
                baseline=inventory(c,survey_final_readonly=True,expected_transition=True)
                c.execute("UPDATE gis.definition_field SET readonly=true,updated_at=now() WHERE physical_name IN ('survey_no','type','x','y','z')")
                self.assertEqual(inventory(c,survey_final_readonly=True),baseline)
                c.execute("UPDATE gis.definition_field SET readonly=false WHERE physical_name='x'")
                self.assertNotEqual(inventory(c,survey_final_readonly=True),baseline)
                c.execute("UPDATE gis.definition_field SET readonly=true WHERE physical_name='x'")
                c.execute("UPDATE gis.definition_field SET label='unexpected' WHERE physical_name='raw_x'")
                self.assertNotEqual(inventory(c,survey_final_readonly=True),baseline)
            transaction.set_rollback(True)

    def test_default_inventory_remains_strict(self):
        with transaction.atomic():
            with connections['default'].cursor() as c:
                baseline=inventory(c)
                c.execute("UPDATE gis.definition_field SET readonly=true WHERE physical_name='type'")
                self.assertNotEqual(inventory(c),baseline)
            transaction.set_rollback(True)

    def test_operational_inventory_without_legacy_survey_code(self):
        with connections['default'].cursor() as c:
            before=survey_elevation_count(c)
            c.execute("INSERT INTO gis.survey(id,project_id,raw_code) VALUES (%s,%s,'H')",[str(uuid4()),self.project])
            self.assertEqual(survey_elevation_count(c),before+1)
            self.assertFalse(final_fields_pending(c))
            with transaction.atomic():
                c.execute("DELETE FROM django_migrations WHERE name='0046_gis_survey_final_fields'")
                self.assertTrue(final_fields_pending(c))
                transaction.set_rollback(True)
            self.assertFalse(final_fields_pending(c))

    def test_22_then_3_and_delta_geopackage(self):
        result=self.run_import(self.payload(22))
        self.assertEqual(result['created'],22)
        self.assertEqual([p['survey_no'] for p in result['points']], [f'251017-{i:03}' for i in range(1,23)])
        self.assertTrue(all(p['type']=='GNSS' and p['x']==235768.352 and p['y']==413130.660
                            and p['z']==49.196 and p['antenna_height']==0 for p in result['points']))
        self.assertEqual([p['survey_no'] for p in self.run_import(self.payload(3))['points']],
                         ['251017-023','251017-024','251017-025'])
        with patch('geoflow_ops.gis.changeset.changeset_runtime_enabled',return_value=True):
            delta=project_delta('default',project_id=self.project,since_revision=0)
        for change in delta['changes']:
            self.assertTrue({'survey_no','type','raw_x','raw_y','raw_z','x','y','z','longitude','latitude','antenna_height','survey_date','code','raw_code'} <= set(change['attributes']))
        path,meta=build_project_geopackage_file('default',project_id=self.project,plan=plan())
        try:
            with closing(sqlite3.connect(path)) as c:
                self.assertEqual(c.execute('SELECT count(*) FROM survey WHERE survey_no IS NOT NULL AND type=? AND x=? AND y=? AND z=?',('GNSS',235768.352,413130.660,49.196)).fetchone()[0],25)
                self.assertEqual(c.execute('SELECT srs_id FROM gpkg_geometry_columns WHERE table_name=?',('survey',)).fetchone()[0],4326)
        finally:
            path.unlink()

    def test_total_station_and_multiple_dates(self):
        payload=self.payload(3,source_type='CSV',survey_type='TOTAL_STATION')
        payload['points'][1]['survey_date']='2025-10-18'
        result=self.run_import(payload)
        self.assertEqual([p['survey_no'] for p in result['points']],['251017-001','251018-001','251017-002'])
        self.assertTrue(all(p['type']=='TOTAL_STATION' for p in result['points']))
        self.assertEqual(survey_method('TOTAL'),'TOTAL_STATION')

    def test_geographic_raw_and_normalized_geometry(self):
        payload=self.payload()
        payload['points'][0].update(raw_x='127.1',raw_y='36.1',raw_crs='EPSG:4326',raw_z=0)
        p=self.run_import(payload)['points'][0]
        self.assertEqual((p['raw_x'],p['raw_y'],p['raw_z']),(127.1,36.1,0))
        self.assertAlmostEqual(p['longitude'],127.1);self.assertAlmostEqual(p['latitude'],36.1)
        self.assertGreater(p['x'],100000);self.assertGreater(p['y'],100000);self.assertEqual(p['z'],0)
        with connections['default'].cursor() as c:
            c.execute('SELECT ST_SRID(geom),longitude=ST_X(geom),latitude=ST_Y(geom) FROM gis.survey WHERE id=%s',[p['id']])
            self.assertEqual(c.fetchone(),(4326,True,True))

    def test_geographic_requires_unambiguous_target(self):
        payload=self.payload(source_crs='EPSG:4326')
        payload['points'][0].update(raw_x=127.1,raw_y=36.1)
        with self.assertRaisesRegex(SyncRejected,'requires target_crs'):
            self.run_import(payload)
        payload['target_crs']='EPSG:5187'
        self.assertAlmostEqual(self.run_import(payload)['points'][0]['x'],28895.860,places=3)

    def test_revision_keeps_uuid_and_number(self):
        first=self.run_import(self.payload(2))
        second=self.run_import(self.payload(3,source_group_id=first['source_group_id'],supersedes_id=first['source_id']))
        self.assertEqual(second['updated'],2);self.assertEqual(second['created'],1)
        for a,b in zip(first['points'],second['points']):
            self.assertEqual((a['id'],a['survey_no']),(b['id'],b['survey_no']))
        self.assertEqual(second['points'][2]['survey_no'],'251017-003')

    def test_nulls_zeros_and_atomic_rejection(self):
        payload=self.payload(2)
        payload['points'][0].update(raw_z=None,antenna_height=None)
        payload['points'][1].update(raw_z=0,antenna_height=0)
        result=self.run_import(payload)
        self.assertIsNone(result['points'][0]['z']);self.assertIsNone(result['points'][0]['antenna_height'])
        self.assertEqual(result['points'][1]['z'],0)
        with connections['default'].cursor() as c:
            c.execute('SELECT current_revision FROM gis.project_sync_state WHERE project_id=%s',[self.project]);revision=c.fetchone()[0]
        payload=self.payload(2);payload['points'][1]['survey_no']='client-owned'
        with self.assertRaisesRegex(SyncRejected,'unsupported fields'):
            self.run_import(payload)
        with connections['default'].cursor() as c:
            c.execute('SELECT count(*) FROM gis.survey WHERE project_id=%s',[self.project]);self.assertEqual(c.fetchone()[0],2)
            c.execute('SELECT current_revision FROM gis.project_sync_state WHERE project_id=%s',[self.project]);self.assertEqual(c.fetchone()[0],revision)
        for value in ('NaN','Infinity',True):
            with self.assertRaises(SyncRejected): decimal_input(value,'test')

    def test_concurrent_same_day_imports(self):
        barrier=threading.Barrier(2)
        def worker():
            try:
                barrier.wait(timeout=10)
                return self.run_import(self.payload(22))
            finally: connections['default'].close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:worker(),range(2)))
        numbers=[p['survey_no'] for r in results for p in r['points']]
        self.assertEqual(len(set(numbers)),44)
        self.assertEqual(sorted(numbers),[f'251017-{i:03}' for i in range(1,45)])

    def test_unique_constraint(self):
        p=self.run_import(self.payload())['points'][0]
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connections['default'].cursor() as c:
                c.execute('INSERT INTO gis.survey(id,project_id,survey_no) VALUES (%s,%s,%s)',[str(uuid4()),self.project,p['survey_no']])

    def test_backfill_idempotent_preserves_normal_values(self):
        p=self.run_import(self.payload())['points'][0]
        with connections['default'].cursor() as c:
            c.execute("UPDATE gis.survey SET survey_no=NULL,type=NULL,x=NULL,y=123,z=NULL,longitude=NULL WHERE id=%s",[p['id']])
        counts=backfill_survey_project('default',self.project)
        self.assertEqual(counts['updated'],1)
        self.assertEqual(backfill_survey_project('default',self.project)['updated'],0)
        with connections['default'].cursor() as c:
            c.execute('SELECT survey_no,type,x,y,z,raw_y FROM gis.survey WHERE id=%s',[p['id']]);r=c.fetchone()
            self.assertEqual(r[0:2],('251017-001','GNSS'))
            self.assertEqual(float(r[2]),235768.352);self.assertEqual(float(r[3]),123);self.assertEqual(float(r[5]),413130.660)

    def test_backfill_keeps_unknown_date_method_and_zero(self):
        payload=self.payload(source_type='CSV',survey_date=None)
        payload['points'][0]['raw_z']=0
        point=self.run_import(payload)['points'][0]
        counts=backfill_survey_project('default',self.project)
        self.assertEqual(counts['updated'],0)
        self.assertEqual(counts['missing_date'],1);self.assertEqual(counts['unknown_method'],1)
        with connections['default'].cursor() as c:
            c.execute('SELECT survey_no,type,z,raw_z FROM gis.survey WHERE id=%s',[point['id']])
            row=c.fetchone();self.assertEqual(row,(None,None,0,0))

    def test_backfill_repairs_proven_geographic_degree_copy(self):
        payload=self.payload()
        payload['points'][0].update(raw_x=127.1,raw_y=36.1,raw_crs='EPSG:4326')
        point=self.run_import(payload)['points'][0]
        with connections['default'].cursor() as c:
            c.execute('UPDATE gis.survey SET x=raw_x,y=raw_y WHERE id=%s',[point['id']])
        self.assertEqual(backfill_survey_project('default',self.project)['updated'],1)
        with connections['default'].cursor() as c:
            c.execute('SELECT x,y,raw_x,raw_y FROM gis.survey WHERE id=%s',[point['id']])
            row=c.fetchone();self.assertAlmostEqual(float(row[0]),point['x'],places=3)
            self.assertAlmostEqual(float(row[1]),point['y'],places=3)
            self.assertEqual((float(row[2]),float(row[3])),(127.1,36.1))

    def test_500_batch_has_no_per_point_source_or_number_query(self):
        worker=str(uuid4())
        with connections['default'].cursor() as c:
            c.execute('INSERT INTO hr.employee_profile(id) VALUES (%s)',[worker])
        with CaptureQueriesContext(connections['default']) as captured:
            self.run_import(self.payload(500,worker_id=worker))
        sql=[q['sql'] for q in captured]
        self.assertEqual(sum('max(split_part(survey_no' in q.lower() for q in sql),1)
        self.assertEqual(sum('SELECT DISTINCT ON (s.source_row_id)' in q for q in sql),1)
        self.assertEqual(sum('SELECT id::text FROM hr.employee_profile' in q for q in sql),1)

    def asset_plan(self, table='wtl_pipe_ps'):
        layer_id='11111111-1111-4111-8111-111111111401'
        fields=[{'id':str(uuid4()),'layer_id':layer_id,'layer_standard_name':table.upper(),'field_name':name,'storage_data_type':kind,
                 'storage':{'kind':'column','key':name},'readonly':name!='description','visible':True}
                for name,kind in [('id','uuid'),('project_id','uuid'),('description','text')]]
        return {'layers':[{'id':layer_id,'standard_name':table.upper(),'physical_name':table,'geometry_kind':'POINT'}],
                'definition':{'revision':'independent'},'form_definition':{'revision':'independent','fields':fields}}

    def create_asset(self, table='wtl_pipe_ps', survey_id=None):
        feature=str(uuid4())
        with connections['default'].cursor() as c:
            if survey_id:
                c.execute(f'INSERT INTO gis.{table}(id,project_id,geom) SELECT %s,project_id,geom FROM gis.survey WHERE id=%s',[feature,survey_id])
            else:
                c.execute(f'INSERT INTO gis.{table}(id,project_id,geom) VALUES (%s,%s,ST_SetSRID(ST_MakePoint(127,36),4326))',[feature,self.project])
        return feature

    def test_retirement_forward_reverse_and_data_recovery(self):
        # Restore the historical schema only inside this disposable transaction.
        with transaction.atomic():
            point=self.run_import(self.payload())['points'][0]
            asset=self.create_asset(survey_id=point['id'])
            with connections['default'].cursor() as c:
                c.execute(retirement_migration().REVERSE_SQL)
                c.execute("INSERT INTO gis.survey_link(id,survey_id,layer_id,target_id,match_method) VALUES (%s,%s,%s,%s,'manual')",[str(uuid4()),point['id'],str(uuid4()),asset])
            client, changes=str(uuid4()),str(uuid4())
            _reserve_receipt('default',project_id=self.project,client_id=client,changeset_id=changes,actor_ref=None,base_revision=None)
            first,_,_=_allocate_revisions('default',self.project,1)
            _insert_change_log('default',project_id=self.project,revision=first,client_id=client,changeset_id=changes,
                              standard_name='SURVEY_LINK',physical_name='survey_link',object_id=str(uuid4()),
                              action='create',changed_fields=[],old_values={},new_values={},geom_before=None,geom_after=None,actor_ref=None)
            with connections['default'].cursor() as c:
                c.execute("UPDATE gis.changeset_receipt SET response_payload=%s::jsonb WHERE project_id=%s AND client_id=%s AND changeset_id=%s",['{"protocol":"survey_link_changeset_v1"}',self.project,client,changes])
                before=preserved_inventory(c); rows=backup_rows(c)
                self.assertEqual(len(rows['targets']),1)
                apply_removal(c)
                self.assertFalse(retirement_pending(c));self.assertEqual(preserved_inventory(c),before)
                self.assertEqual(backup_rows(c)['targets'],[])
                restore(c,{'preserved':before,'rows':rows})
                self.assertTrue(retirement_pending(c));self.assertEqual(backup_rows(c),rows)
                self.assertEqual(preserved_inventory(c),before)
                apply_removal(c);apply_removal(c)
                self.assertFalse(retirement_pending(c));self.assertEqual(preserved_inventory(c),before)
            with patch('geoflow_ops.gis.changeset.changeset_runtime_enabled',return_value=True):
                delta=project_delta('default',project_id=self.project,since_revision=first-1)
                self.assertEqual(delta['changes'],[])
                self.assertEqual(delta['next_revision'],first)
            transaction.set_rollback(True)

    def test_retirement_without_optional_sync_runtime(self):
        # Empty live tenants have the GIS foundation without revision tables.
        with transaction.atomic():
            with connections['default'].cursor() as c:
                c.execute('DROP TABLE gis.feature_change_log; DROP TABLE gis.changeset_receipt')
                c.execute(retirement_migration().REVERSE_SQL)
                before=preserved_inventory(c)
                rows=backup_rows(c)
                self.assertEqual(rows,{'targets':[],'logs':[],'receipts':[]})
                apply_removal(c)
                self.assertFalse(retirement_pending(c))
                self.assertEqual(preserved_inventory(c),before)
                apply_removal(c)
                self.assertEqual(preserved_inventory(c),before)
                restore(c,{'preserved':before,'rows':rows})
                self.assertEqual(backup_rows(c),rows)
                self.assertEqual(preserved_inventory(c),before)
            transaction.set_rollback(True)

    def test_source_and_point_delete_do_not_change_assets(self):
        for delete_source in (False,True):
            point=self.run_import(self.payload())['points'][0]
            self.create_asset(survey_id=point['id'])
            with connections['default'].cursor() as c:
                before=preserved_inventory(c)['wtl_pipe_ps']
            if delete_source:
                result=delete_survey_source('default',project_id=self.project,source_id=point['source_id'])
            else:
                result=delete_survey_points('default',project_id=self.project,survey_ids=[point['id']])
            self.assertEqual(result['survey_points_deleted'],1)
            with connections['default'].cursor() as c:
                self.assertEqual(preserved_inventory(c)['wtl_pipe_ps'],before)
            self.assertFalse(any('link' in k or 'depth_dependency' in k for k in result))

    def test_facility_crud_has_no_target_sql_and_preserves_observations(self):
        point=self.run_import(self.payload())['points'][0]
        for table in ('wtl_pipe_ps','wtl_valv_ps'):
            asset=self.create_asset(table,survey_id=point['id'])
            with connections['default'].cursor() as c:
                c.execute("SELECT encode(ST_AsBinary(geom),'hex') FROM gis.survey WHERE id=%s",[point['id']])
                geometry=c.fetchone()[0];before=preserved_inventory(c)
            new_asset=str(uuid4())
            changes=[{'action':'create','layer':table.upper(),'id':new_asset,'attributes':{'description':'created'},'geometry_wkb':geometry},
                     {'action':'update','layer':table.upper(),'id':asset,'attributes':{'description':'updated'}},
                     {'action':'delete','layer':table.upper(),'id':asset}]
            with patch('geoflow_ops.gis.changeset.changeset_runtime_enabled',return_value=True), CaptureQueriesContext(connections['default']) as captured:
                responses=[apply_project_changeset('default',project_id=self.project,plan=self.asset_plan(table),payload={'client_id':str(uuid4()),'changeset_id':str(uuid4()),'changes':[change]}) for change in changes]
            self.assertEqual(tuple(sum(r[key] for r in responses) for key in ('created','updated','deleted')),(1,1,1))
            self.assertFalse(any('survey_link' in q['sql'].lower() for q in captured))
            with connections['default'].cursor() as c:
                after=preserved_inventory(c)
            self.assertEqual(before['survey'],after['survey']);self.assertEqual(before['survey_source'],after['survey_source'])



if __name__=='__main__':
    bootstrap()
    unittest.main(verbosity=2)
