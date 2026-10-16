"""Isolated PostGIS rehearsal of the real Survey services, never a live database."""
import importlib.util
import os
import sqlite3
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
from geoflow_ops.gis.survey_sources import import_survey_source
from geoflow_ops.gis.survey_final import decimal_input, survey_method
from geoflow_ops.gis.survey_backfill import backfill_survey_project
from geoflow_ops.gis.changeset import project_delta
from geoflow_ops.gis.gpkg_snapshot_file import build_project_geopackage_file
from geoflow_ops.gis.qgis_sync import SyncRejected


def bootstrap():
    with connections['default'].cursor() as c:
        c.execute('SELECT current_database()')
        assert c.fetchone()[0] == 'survey_final_test'
        c.execute('CREATE EXTENSION IF NOT EXISTS postgis; CREATE SCHEMA prj; CREATE SCHEMA gis; CREATE SCHEMA hr;')
        c.execute('CREATE TABLE prj.projects(id uuid PRIMARY KEY); CREATE TABLE hr.employee_profile(id uuid PRIMARY KEY,is_deleted boolean DEFAULT false);')
        for name in ('0044_gis_survey_lineage','0045_gis_survey_soft_delete','0046_gis_survey_final_fields'):
            spec = importlib.util.spec_from_file_location(name, ROOT/'geoflow_ops/migrations'/f'{name}.py')
            module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            c.execute(module.Migration.operations[0].sql)
        sql = (ROOT/'docs/architecture/gis-sync-revision-v1.sql').read_text()
        c.execute(sql[sql.index('CREATE TABLE IF NOT EXISTS gis.project_sync_state'):sql.index('COMMIT;')])


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
            with sqlite3.connect(path) as c:
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
        self.assertGreater(self.run_import(payload)['points'][0]['x'],100000)

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


if __name__=='__main__':
    bootstrap()
    unittest.main(verbosity=2)
