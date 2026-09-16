import os
from pathlib import Path
import unittest
from uuid import uuid4
from control.services import gis_definitions as defs
from control.services import gis_definition_transition as transition
from geoflow_ops.gis.central_definitions import resolve, reference_payload, project_config
from unittest.mock import MagicMock
import json

ROOT=Path(__file__).resolve().parents[2]

class ResolutionTests(unittest.TestCase):
    def data(self):
        return {'groups':[{'id':'g','name':'아산시'}],
            'fields':[{'id':'f','label':'추락방지시설','kind':'boolean','source_layer':None,'physical_name':None,'sort_order':5}],
            'group_fields':[{'group_id':'g','layer_name':'MANHOLE','field_id':'f','sort_order':2,'required':True}],
            'codes':[],'rules':[]}

    def test_common_group_and_project_isolation(self):
        data=self.data();layers=[{'standard_name':'MANHOLE','id':'local-1'}]
        a=resolve(data,{'group_id':'g','additions':{}},layers)
        self.assertEqual(a['items'][0]['feature_type_id'],'local-1')
        self.assertEqual(a['items'][0]['sort_order'],2)
        self.assertTrue(a['items'][0]['inherited'])
        b=resolve(data,{'group_id':None,'additions':{}},layers)
        self.assertEqual(b['items'],[])
        self.assertEqual(resolve(data,{'group_id':'g'},[])['items'],[])
        self.assertEqual(resolve(data,{'group_id':'g'},[{'standard_name':'OTHER','id':'other'}])['items'],[])

    def test_saved_json_text_roundtrip_and_group_import_all_layers(self):
        cur=MagicMock()
        cur.fetchone.side_effect=[('gis.project_definition',),('g','{}','{}')]
        config=project_config(cur,'project')
        data=self.data()
        data['layers']=[{'standard_name':'MANHOLE'},{'standard_name':'PIPE'}]
        data['group_fields'].append({'group_id':'g','layer_name':'PIPE','field_id':'f','sort_order':3,'required':False})
        layers=[{'id':'m','standard_name':'MANHOLE'}]
        items=resolve(data,config,layers,include_unavailable=True)['items']
        self.assertEqual(len(items),2)
        self.assertEqual([i['standard_name'] for i in items if not i['layer_available']],['PIPE'])
        self.assertEqual(len(resolve(data,config,layers)['items']),1)

    def test_individual_addition_survives_save_and_does_not_duplicate_group(self):
        cur=MagicMock()
        cur.fetchone.side_effect=[('gis.project_definition',),('g',json.dumps({'f':['MANHOLE']}),'{}')]
        config=project_config(cur,'project')
        layers=[{'id':'m','standard_name':'MANHOLE'}]
        self.assertEqual(len(resolve(self.data(),config,layers)['items']),1)
        config['group_id']=None
        self.assertFalse(resolve(self.data(),config,layers)['items'][0]['inherited'])

    def test_invalid_saved_json_reports_validation_error(self):
        for raw in ('[]','not-json','{"f": "MANHOLE"}'):
            cur=MagicMock();cur.fetchone.side_effect=[('gis.project_definition',),(None,raw,'{}')]
            with self.assertRaises(defs.DefinitionError):project_config(cur,'project')

    def test_private_items_are_only_from_project_config(self):
        f=self.data()['fields'][0]|{'id':'p','source_layer':'MANHOLE'}
        a=resolve(self.data(),{'private_items':{'p':f}},[{'standard_name':'MANHOLE','id':'l'}])
        self.assertEqual(a['items'][0]['id'],'p')
        self.assertEqual(resolve(self.data(),{},[{'standard_name':'MANHOLE','id':'l'}])['items'],[])

    def test_reference_scope_and_wire_compatibility(self):
        data=self.data();data['fields'][0].update(source_layer='MANHOLE',physical_name='saa_cde')
        data['codes']=[{'id':'v','field_id':'f','code':'DCIP','label':'주철','sort_order':1}]
        self.assertEqual(reference_payload(data,[])['groups'],[])
        p=reference_payload(data,['MANHOLE'])
        self.assertEqual(p['groups'][0]['values'][0]['code'],'DCIP')
        self.assertEqual(p['bindings'][0]['field_name'],'saa_cde')


@unittest.skipUnless(os.getenv('GEOFLOW_FORMS_ISOLATED_PG')=='1','isolated PostgreSQL opt-in only')
class CentralPostgresTests(unittest.TestCase):
    def setUp(self):
        import psycopg2
        self.db=psycopg2.connect(host='127.0.0.1',port=55440,dbname='geoflow_forms_test',user='geoflow_test',password='geoflow_test')
        self.addCleanup(self.db.close);self.addCleanup(self.db.rollback)
        self.cur=self.db.cursor();self.addCleanup(self.cur.close)
        self.cur.execute('CREATE SCHEMA catalog; CREATE TABLE catalog.category_node(id uuid PRIMARY KEY,name text,code text,level int,ord int,active boolean)')
        self.catalog=str(uuid4())
        self.cur.execute("INSERT INTO catalog.category_node VALUES (%s,'하수도','SEWERAGE',2,1,true)",[self.catalog])
        self.cur.execute((ROOT/'docs/architecture/gis-central-definitions.sql').read_text())
        self.cur.execute("INSERT INTO gis.definition_layer VALUES ('MANHOLE','하수맨홀'),('PIPE','상수관로')")
        self.cur.execute("INSERT INTO gis.definition_layer_catalog VALUES ('MANHOLE',%s)",[self.catalog])

    def save(self,action,**data):return defs.mutate(self.cur,{'action':action,**data})
    def field(self,label='추락방지시설',**kw):return self.save('field',label=label,kind='text',**kw)
    def code(self,field,code):return self.save('code',field=field,code=code,label=code)

    def test_project_saved_json_with_django_postgres_decoder(self):
        # Match Django's raw cursor decoder, not psycopg2's default dict conversion.
        import psycopg2.extras
        psycopg2.extras.register_default_jsonb(self.db, loads=lambda value:value)
        self.cur.execute('CREATE SCHEMA prj; CREATE TABLE prj.projects(id uuid PRIMARY KEY)')
        transition.retire_empty_legacy(self.cur)
        project=str(uuid4());g=self.save('group',label='아산시청');f=self.field('FPD_STA')
        self.cur.execute('INSERT INTO prj.projects VALUES (%s)',[project])
        self.cur.execute("INSERT INTO gis.project_definition(project_id,group_id,additions) VALUES (%s,%s,%s::jsonb)",
                         [project,g,json.dumps({f:['MANHOLE']})])
        config=project_config(self.cur,project)
        self.assertEqual(config['additions'],{f:['MANHOLE']})
        items=resolve(defs.snapshot(self.cur),config,[{'id':'m','standard_name':'MANHOLE'}])['items']
        self.assertEqual(items[0]['label'],'FPD_STA')

    def test_group_scope_layer_field_sequence(self):
        g=self.save('group',label='아산시');f=self.field()
        with self.assertRaises(defs.DefinitionError):self.save('group_layer',group=g,layer='MANHOLE')
        self.save('scope',group=g,catalog=self.catalog);self.save('group_layer',group=g,layer='MANHOLE')
        self.save('group_field',group=g,layer='MANHOLE',field=f,sort_order='7',required='true')
        data=defs.snapshot(self.cur)
        self.assertEqual(data['groups'][0]['name'],'아산시');self.assertEqual(data['group_fields'][0]['sort_order'],7)
        with self.assertRaises(defs.DefinitionError):self.save('delete_scope',group=g,catalog=self.catalog)
        self.save('delete_group_field',group=g,layer='MANHOLE',field=f)
        self.save('delete_group_layer',group=g,layer='MANHOLE')
        self.save('delete_scope',group=g,catalog=self.catalog)
        self.save('delete_group',id=g)

    def test_untyped_layerless_field_codes_and_edit(self):
        f=self.field();c=self.code(f,'01')
        self.save('code',id=c,field=f,code='01',label='있음',sort_order=3)
        data=defs.snapshot(self.cur)
        self.assertEqual(data['field_layers'],[])
        self.assertEqual(data['codes'][0]['label'],'있음')
        self.save('field_layer',field=f,layer='PIPE');self.save('field_layer',field=f,layer='MANHOLE')
        self.assertEqual(len(defs.snapshot(self.cur)['codes']),1)
        self.save('delete_field_layer',field=f,layer='PIPE');self.save('delete_field_layer',field=f,layer='MANHOLE')
        self.save('delete_code',id=c);self.save('delete_field',id=f)
        self.assertEqual(defs.snapshot(self.cur)['fields'],[])

    def test_condition_values_and_cycles(self):
        a=self.field('재질');b=self.field('접합');c=self.field('마감')
        ac=self.code(a,'DCIP');bc=self.code(b,'KP');cc=self.code(c,'A')
        r=self.save('rule',source_field=a,source_code=ac,target_field=b,allowed=[bc])
        with self.assertRaises(defs.DefinitionError):self.save('rule',source_field=a,source_code=ac,target_field=b,allowed=[cc])
        self.save('rule',source_field=b,source_code=bc,target_field=c,allowed=[cc])
        with self.assertRaises(defs.DefinitionError):self.save('rule',source_field=c,source_code=cc,target_field=a,allowed=[ac])
        self.save('delete_rule',id=r)
        self.assertEqual(len(defs.snapshot(self.cur)['rules']),1)

    def test_photo_cannot_have_codes(self):
        f=self.save('field',label='사진',kind='photo')
        with self.assertRaises(defs.DefinitionError):self.code(f,'1')

    def test_standard_fields_cannot_be_deleted_or_rebound(self):
        f=str(uuid4());self.cur.execute("INSERT INTO gis.definition_field(id,label,kind,source_layer,physical_name) VALUES (%s,'재질','text','PIPE','saa_cde')",[f])
        with self.assertRaises(defs.DefinitionError):self.save('delete_field',id=f)
        with self.assertRaises(defs.DefinitionError):self.save('field_layer',field=f,layer='MANHOLE')

    def test_unused_legacy_retirement_and_replay(self):
        self.cur.execute('CREATE SCHEMA prj; CREATE TABLE prj.projects(id uuid PRIMARY KEY); CREATE TABLE gis.form_item(id uuid PRIMARY KEY); CREATE TABLE gis.profile_form_item(item_id uuid REFERENCES gis.form_item(id)); CREATE TABLE gis.project_form_item(item_id uuid REFERENCES gis.form_item(id))')
        state=transition.retire_empty_legacy(self.cur)
        self.assertTrue(all(v is not None for v in state.values()))
        self.assertTrue(all(v is None for v in transition.retire_empty_legacy(self.cur).values()))
        self.cur.execute("SELECT to_regclass('gis.project_definition')")
        self.assertIsNotNone(self.cur.fetchone()[0])

    def test_populated_legacy_is_not_dropped(self):
        self.cur.execute('CREATE TABLE gis.form_item(id uuid PRIMARY KEY); INSERT INTO gis.form_item VALUES (%s)',[str(uuid4())])
        with self.assertRaises(defs.DefinitionError):transition.inspect_tenant(self.cur)
        self.cur.execute('SELECT count(*) FROM gis.form_item');self.assertEqual(self.cur.fetchone()[0],1)

    def test_unknown_dependency_prevents_drop(self):
        import psycopg2
        self.cur.execute('CREATE SCHEMA prj; CREATE TABLE prj.projects(id uuid PRIMARY KEY); CREATE TABLE gis.form_item(id uuid PRIMARY KEY); CREATE VIEW gis.unknown_view AS SELECT * FROM gis.form_item')
        self.cur.execute('SAVEPOINT before_retire')
        with self.assertRaises(psycopg2.errors.DependentObjectsStillExist):transition.retire_empty_legacy(self.cur)
        self.cur.execute('ROLLBACK TO SAVEPOINT before_retire')
        self.cur.execute("SELECT to_regclass('gis.form_item')");self.assertIsNotNone(self.cur.fetchone()[0])

    def test_bootstrap_is_atomic_and_keeps_ids_on_retry(self):
        self.cur.execute('DROP SCHEMA gis CASCADE')
        source={'layers':[{'standard_name':'MANHOLE','label':'하수맨홀'}],
            'bindings':[{'standard_name':'MANHOLE','catalog_item_id':self.catalog}],
            'fields':[{'layer_name':'MANHOLE','physical_name':'saa_cde','label':'재질',
                       'data_type':'text','sort_order':1,'code_group_key':'MATERIAL'}],
            'codes':[{'group_key':'MATERIAL','code':'DCIP','label':'주철','sort_order':1}]}
        ddl=(ROOT/'docs/architecture/gis-central-definitions.sql').read_text()
        self.assertTrue(transition.bootstrap(self.cur,source,ddl))
        before=defs.snapshot(self.cur)
        self.assertFalse(transition.bootstrap(self.cur,source,ddl))
        self.assertEqual(before,defs.snapshot(self.cur))
        self.assertEqual(before['codes'][0]['code'],'DCIP')
        self.assertEqual(len(before['layer_catalogs']),1)
