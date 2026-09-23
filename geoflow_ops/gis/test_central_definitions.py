import json
import os
from pathlib import Path
import unittest
from unittest.mock import MagicMock
from uuid import uuid4

from control.services import gis_definitions as defs
from control.services import gis_definition_transition as transition
from geoflow_ops.gis.central_definitions import project_config, reference_payload, resolve, validate_attributes
from control.management.commands.repair_gis_definition_layouts import normalize_layout
from geoflow_ops.gis.layer_plan import _scope_rows

ROOT=Path(__file__).resolve().parents[2]


class ResolutionTests(unittest.TestCase):
    def data(self):
        return {
          'groups':[{'id':'g','name':'아산시'}],
          'layers':[{'id':'m','standard_name':'MANHOLE','physical_name':'manhole','label':'맨홀','active':True,'sort_order':1}],
          'fields':[{'id':'f','label':'추락방지시설','kind':'boolean','widget_type':'boolean',
            'source_layer_id':None,'physical_name':None,'standard_name':None,'sort_order':5,
            'visible':True,'required':False,'readonly':False,'layout':{},'unit':'','description':''}],
          'group_fields':[{'group_id':'g','layer_id':'m','field_id':'f','sort_order':2,'required':True,
                           'visible':None,'readonly':None,'layout':{}}],
          'codes':[],'rules':[],
        }

    def test_group_imports_all_linked_layers_and_project_isolation(self):
        data=self.data(); data['layers'].append({'id':'p','standard_name':'PIPE','physical_name':'pipe','label':'관로','active':True,'sort_order':2})
        data['group_fields'].append({'group_id':'g','layer_id':'p','field_id':'f','sort_order':3,'required':False,'visible':None,'readonly':None,'layout':{}})
        active=[data['layers'][0]]
        result=resolve(data,{'group_id':'g','additions':{},'private_items':{},'overrides':{}},active,include_unavailable=True)
        self.assertEqual({field['layer_id'] for field in result['fields']},{'m','p'})
        self.assertEqual([field['layer_id'] for field in result['fields'] if not field['layer_available']],['p'])
        isolated=resolve(data,{'group_id':None,'additions':{},'private_items':{},'overrides':{}},active)
        self.assertEqual(isolated['fields'],[])

    def test_standard_and_additional_fields_share_one_shape(self):
        data=self.data(); data['fields'].append({'id':'s','label':'관종','kind':'text','widget_type':'combo',
          'source_layer_id':'m','physical_name':'saa_cde','standard_name':'SAA_CDE','storage_data_type':'character varying(50)',
          'sort_order':1,'visible':True,'required':False,'readonly':False,'layout':{},'unit':'','description':''})
        data['codes']=[{'id':'c','field_id':'s','code':'DCIP','label':'덕타일주철관','sort_order':1,'enabled':True}]
        result=resolve(data,{'group_id':'g','additions':{},'private_items':{},'overrides':{}},data['layers'])
        by_id={field['id']:field for field in result['fields']}
        self.assertEqual(by_id['s']['reference_codes'][0]['id'],'c')
        self.assertEqual(by_id['s']['storage']['kind'],'column')
        self.assertEqual(by_id['f']['storage']['kind'],'ext_data')
        self.assertEqual(result['items'],result['fields'])

    def test_saved_json_v3_roundtrip(self):
        cur=MagicMock(); cur.fetchone.side_effect=[('gis.project_definition',),('g','{"f":["m"]}','{}','{}',None)]
        config=project_config(cur,'project')
        self.assertEqual(config['additions'],{'f':['m']})
        self.assertEqual(config['overrides'],{})

    def test_reference_codes_keep_uuid(self):
        data=self.data(); field=data['fields'][0]
        field.update(source_layer_id='m',physical_name='saa_cde',standard_name='SAA_CDE')
        data['codes']=[{'id':'code-uuid','field_id':'f','code':'DCIP','label':'주철','sort_order':1,'enabled':True}]
        payload=reference_payload(data,['m'])
        self.assertEqual(payload['groups'][0]['values'][0]['id'],'code-uuid')
        self.assertEqual(payload['bindings'][0]['layer_id'],'m')

    def test_server_validation_uses_code_uuid_rules(self):
        fields=[{'id':'material','layer_standard_name':'PIPE','label':'재질','required':True,'visible':True,
                 'storage':{'kind':'column','key':'material'},'reference_codes':[{'id':'dcip','value':'DCIP','enabled':True}]},
                {'id':'joint','layer_standard_name':'PIPE','label':'접합','required':False,'visible':True,
                 'storage':{'kind':'column','key':'joint'},'reference_codes':[{'id':'kp','value':'KP','enabled':True},{'id':'bolt','value':'BOLT','enabled':True}]}]
        plan={'form_definition':{'fields':fields,'rules':[{'source_field_id':'material','source_code_id':'dcip',
              'target_field_id':'joint','allowed_code_ids':['kp']}]}}
        validate_attributes(plan,'PIPE',{'material':'DCIP','joint':'KP'})
        with self.assertRaises(defs.DefinitionError): validate_attributes(plan,'PIPE',{'material':'DCIP','joint':'BOLT'})

    def test_physical_schema_merge_rejects_tenant_type_drift(self):
        base={'layers':[{'standard_name':'PIPE','physical_name':'pipe','geometry_kind':'LINE',
                        'feature_role':'ASSET','scope_type':'PROJECT'}],
              'fields':[{'layer_name':'PIPE','physical_name':'pip_dip','storage_data_type':'numeric(10,2)',
                         'storage_udt_name':'numeric','nullable':True,'storage_default':None,
                         'max_length':None,'precision':10,'scale':2,'sort_order':1}],
              'bindings':[],'codes':[]}
        other=json.loads(json.dumps(base)); other['fields'][0]['storage_data_type']='character varying(20)'
        other['fields'][0]['storage_udt_name']='varchar'; other['fields'][0]['precision']=None
        other['fields'][0]['scale']=None; other['fields'][0]['max_length']=20
        with self.assertRaises(defs.DefinitionError): transition.merge_source_snapshots([base,other])

    def test_physical_schema_merge_unions_non_conflicting_layers(self):
        first={'layers':[{'standard_name':'PIPE','physical_name':'pipe','geometry_kind':'LINE',
                         'feature_role':'ASSET','scope_type':'PROJECT'}],
               'fields':[],'bindings':[],'codes':[]}
        second={'layers':[{'standard_name':'MANHOLE','physical_name':'manhole','geometry_kind':'POINT',
                          'feature_role':'ASSET','scope_type':'PROJECT'}],
                'fields':[],'bindings':[],'codes':[]}
        merged=transition.merge_source_snapshots([first,second])
        self.assertEqual([layer['standard_name'] for layer in merged['layers']],['MANHOLE','PIPE'])

    def test_standard_field_admin_uses_catalog_layer_physical_field_flow(self):
        template=(ROOT/'control/templates/control/gis/definitions.html').read_text()
        for marker in ('standard-catalog','standard-layer','new-standard-layer','new-standard-field',
                       'standard-field-search','standard-kind-filter','standard-widget-filter',
                       'standard-visible-filter','standard-required-filter','standard-readonly-filter',
                       'standard-field-table','physical_field_create_admin','physical_field_update_admin',
                       'physical_field_delete_admin'):
            self.assertIn(marker,template)
        self.assertIn('#standard-table thead th{position:sticky',template)
        self.assertIn('standardLayersForCatalog',template)
        self.assertIn('Layer/Field CRUD는 표준/레이어 필드에서 수행합니다.',template)
        admin = template.split('function renderAdminV2(){',1)[1].split('function renderAdminFields(){',1)[0]
        self.assertNotIn('레이어 그룹 관리', admin)
        self.assertNotIn('레이어 정의 생성', admin)
        self.assertNotIn('필드 일괄 편집', admin)

    def test_standard_field_selection_ui_contract(self):
        template=(ROOT/'control/templates/control/gis/definitions.html').read_text()
        for marker in (
            '조회 업무범위','연결 업무범위','data-layer-catalog-checkbox',
            'data-bs-auto-close="outside"','name="standard-field-selection"',
            'data-standard-field-row','table-primary','aria-selected',
            '수정할 필드를 목록에서 선택하세요.','선택 필드:',
            '신규 필드 생성','delete-selected-standard-field',
            'selected-standard-field-delete-form','활성 상태'
        ):
            self.assertIn(marker, template)
        self.assertIn('function selectStandardField(fieldId)', template)
        self.assertIn("if(b.id==='new-standard-field'){editingStandardField='';", template)
        standard_table = template.split("$('standard-table').innerHTML=",1)[1].split('function selectStandardField',1)[0]
        self.assertNotIn('data-edit-standard-field', standard_table)
        self.assertNotIn('<th>관리</th>', standard_table)
        self.assertNotIn('미반영/비활성', standard_table)
        self.assertIn('>활성<', standard_table)
        self.assertIn('>비활성<', standard_table)

    def test_one_stop_rename_wiring_and_messages(self):
        views=(ROOT/'control/views_gis_admin.py').read_text()
        execution=(ROOT/'control/services/gis_schema_execution.py').read_text()
        template=(ROOT/'control/templates/control/gis/definitions.html').read_text()
        self.assertIn("request.POST.get('action')=='physical_field_update_admin'", views)
        self.assertIn('apply_rename_from_field_save', views)
        self.assertIn('물리 필드명 변경에 실패했습니다. 기존 필드명은 유지됩니다.', views)
        self.assertIn('물리 필드명을 {rename[\'old_name\']} → {rename[\'new_name\']}로 변경했습니다.', views)
        self.assertIn('def apply_rename_from_field_save', execution)
        self.assertIn('approve(change_id, actor=actor)', execution)
        self.assertIn('apply(change_id, registered_tenant_ids(), actor=actor)', execution)
        self.assertIn("result.message||'저장했습니다.'", template)

    def test_one_stop_alter_type_and_cleanup_contract(self):
        views=(ROOT/'control/views_gis_admin.py').read_text()
        execution=(ROOT/'control/services/gis_schema_execution.py').read_text()
        manager_source=(ROOT/'control/services/gis_schema_manager.py').read_text()
        cleanup=(ROOT/'control/management/commands/cleanup_gis_standard_fields.py').read_text()
        deploy=(ROOT/'.github/workflows/gis-definition-code-deploy.yml').read_text()

        self.assertIn('apply_type_from_field_save', views)
        self.assertIn('DB 타입 변경에 실패했습니다. 기존 정의와 컬럼 타입은 유지됩니다.', views)
        self.assertIn("DB 타입을 {alter_type['old_type']} → {alter_type['new_type']}으로 변경했습니다.", views)
        self.assertIn('def apply_type_from_field_save', execution)
        self.assertIn('def validate_alter_type_pair', manager_source)
        self.assertIn('USING {}::{}', manager_source)
        self.assertIn('char_length({}) > %s', manager_source)

        water_pos=cleanup.index('# STEP 3: WATER')
        rename_pos=cleanup.index('# STEP 4: SEWER rename')
        drop_pos=cleanup.index('# STEP 5: SEWER physical DROP')
        verify_pos=cleanup.index('# STEP 6: central + tenant invariants')
        self.assertLess(water_pos,rename_pos)
        self.assertLess(rename_pos,drop_pos)
        self.assertLess(drop_pos,verify_pos)
        self.assertIn('SEWER_DROP_FIELDS = ("mng_cde", "ftr_idn", "gid", "off_cde", "hjd_cde", "bjd_cde", "sht_num")', cleanup)
        self.assertIn('SEWER_RENAMES = (("ist_ymd", "date"), ("sys_chk", "status"))', cleanup)
        self.assertIn('cleanup_gis_standard_fields --apply', deploy)

    def test_qgis_flow_dip_repair_and_logging_contract(self):
        repair=(ROOT/'control/management/commands/repair_qgis_flow_dip.py').read_text()
        qgis_views=(ROOT/'geoflow_ops/gis/qgis_views.py').read_text()
        deploy=(ROOT/'.github/workflows/gis-definition-code-deploy.yml').read_text()

        self.assertIn('LAYER_STANDARD = "WTL_FLOW_PS"', repair)
        self.assertIn('OLD_NAME = "flow_dip"', repair)
        self.assertIn('NEW_NAME = "flo_dip"', repair)
        self.assertNotIn('apply_rename_from_field_save', repair)
        self.assertNotIn('ALTER TABLE', repair)
        self.assertIn('METADATA_PHYSICAL_NAME_REPAIR', repair)
        self.assertIn('UPDATE gis.definition_field', repair)
        self.assertIn('purge_project_server_snapshots', repair)
        self.assertIn('build_syncable_project_geopackage_file', repair)
        self.assertIn('central_flow_dip_count', repair)
        self.assertIn('project_definition_flow_dip_count', repair)
        self.assertIn('Final Form Definition에 flow_dip가 남아 있습니다.', repair)
        self.assertIn('QGIS_PACKAGE_DB_FAIL', qgis_views)
        self.assertIn('project_id=%s alias=%s endpoint=qgis-package', qgis_views)
        self.assertIn('qgis_package_materialization_failed', qgis_views)
        self.assertIn('repair_qgis_flow_dip --apply', deploy)

    def test_legacy_layout_normalization_only_recovers_json_objects(self):
        self.assertEqual(normalize_layout('{"section":"기본"}'), {'section':'기본'})
        self.assertEqual(normalize_layout(['기본']), {})
        self.assertEqual(normalize_layout('["기본"]'), {})
        self.assertEqual(normalize_layout('not-json'), {})


@unittest.skipUnless(os.getenv('GEOFLOW_FORMS_ISOLATED_PG')=='1','isolated PostgreSQL opt-in only')
class CentralPostgresTests(unittest.TestCase):
    def setUp(self):
        import psycopg2
        self.db=psycopg2.connect(host='127.0.0.1',port=55440,dbname='geoflow_forms_test',user='geoflow_test',password='geoflow_test')
        self.addCleanup(self.db.close); self.addCleanup(self.db.rollback)
        self.cur=self.db.cursor(); self.addCleanup(self.cur.close)
        self.cur.execute('DROP SCHEMA IF EXISTS gis CASCADE; DROP SCHEMA IF EXISTS catalog CASCADE; DROP SCHEMA IF EXISTS prj CASCADE')
        self.cur.execute('''CREATE SCHEMA catalog;
          CREATE TABLE catalog.category_node(
            id uuid PRIMARY KEY,code text,name text,level smallint,ord integer,active boolean,
            org_unit_id uuid,geom_hint text,created_at timestamptz,updated_at timestamptz);
          CREATE TABLE catalog.category_facet(
            id uuid PRIMARY KEY,code text,name text,ord integer,active boolean,
            created_at timestamptz,updated_at timestamptz);
          CREATE TABLE catalog.category_facet_option(
            id uuid PRIMARY KEY,facet_id uuid REFERENCES catalog.category_facet(id),code text,name text,
            ord integer,active boolean,default_unit text,geom_hint text,
            created_at timestamptz,updated_at timestamptz)''')
        self.catalog=str(uuid4()); self.cur.execute(
            "INSERT INTO catalog.category_node(id,code,name,level,ord,active) VALUES (%s,'SEWERAGE','하수도',2,1,true)",
            [self.catalog],
        )
        self.cur.execute((ROOT/'docs/architecture/gis-central-definitions.sql').read_text())
        self.manhole=str(uuid4()); self.pipe=str(uuid4())
        self.cur.execute("INSERT INTO gis.definition_layer(id,standard_name,physical_name,label) VALUES (%s,'MANHOLE','manhole','하수맨홀'),(%s,'PIPE','pipe','상수관로')",[self.manhole,self.pipe])
        self.cur.execute('INSERT INTO gis.definition_layer_catalog(layer_id,catalog_level,catalog_item_id) VALUES (%s,2,%s)',[self.manhole,self.catalog])

    def save(self,action,**data): return defs.mutate(self.cur,{'action':action,**data})
    def field(self,label='추락방지시설',**kw): return self.save('field',label=label,kind='text',**kw)
    def code(self,field,code): return self.save('code',field=field,code=code,label=code)

    def test_group_layer_field_and_rule(self):
        group=self.save('group',label='아산시'); material=self.field('재질'); joint=self.field('접합')
        with self.assertRaises(defs.DefinitionError): self.save('group_layer',group=group,layer=self.manhole)
        self.save('scope',group=group,catalog=self.catalog); self.save('group_layer',group=group,layer=self.manhole)
        self.save('group_field',group=group,layer=self.manhole,field=material,sort_order=7,required='true')
        source=self.code(material,'DCIP'); target=self.code(joint,'KP')
        self.save('rule',source_field=material,source_code=source,target_field=joint,allowed=[target])
        data=defs.snapshot(self.cur)
        self.assertEqual(data['group_fields'][0]['layer_id'],self.manhole)
        self.assertEqual(data['rules'][0]['allowed'],[target])

    def test_snapshot_uses_catalog_ord_and_accepts_real_facet_schema(self):
        later = str(uuid4())
        self.cur.execute(
            "INSERT INTO catalog.category_node(id,code,name,level,ord,active) "
            "VALUES (%s,'WATER','상수도',2,9,true)",
            [later],
        )
        facet = str(uuid4())
        option = str(uuid4())
        self.cur.execute(
            "INSERT INTO catalog.category_facet(id,code,name,ord,active) "
            "VALUES (%s,'FACILITY','시설',1,true)",
            [facet],
        )
        self.cur.execute(
            "INSERT INTO catalog.category_facet_option(id,facet_id,code,name,ord,active) "
            "VALUES (%s,%s,'MANHOLE','맨홀',1,true)",
            [option, facet],
        )
        group = self.save('group', label='아산시')
        self.save('scope', group=group, catalog=option, catalog_level=3)

        data = defs.snapshot(self.cur)
        self.assertEqual([row['code'] for row in data['catalogs']], ['SEWERAGE', 'WATER'])
        self.assertEqual(data['scopes'][0]['catalog_id'], option)

    def test_layer_plan_scope_query_accepts_canonical_table_without_active_column(self):
        self.cur.execute('''CREATE SCHEMA prj;
          CREATE TABLE prj.scope_item(
            id uuid PRIMARY KEY, project_id uuid, lv2_id uuid,
            lv3_id uuid, lv4_id uuid, unit varchar(20),
            design_qty numeric(18,3), completed_qty numeric(18,3),
            remark varchar(255), created_at timestamptz, updated_at timestamptz)''')
        project = str(uuid4())
        scope = str(uuid4())
        self.cur.execute(
            'INSERT INTO prj.scope_item(id,project_id,lv2_id) VALUES (%s,%s,%s)',
            [str(uuid4()), project, scope],
        )

        self.assertEqual(_scope_rows(self.cur), [(project, scope, None, None)])
        self.assertEqual(
            _scope_rows(self.cur, project_id=project),
            [(project, scope, None, None)],
        )
        self.assertEqual(
            _scope_rows(self.cur, project_ids=[project]),
            [(project, scope, None, None)],
        )

    def test_standard_field_edit_persists_and_updates_final_definition(self):
        field_id=str(uuid4())
        self.cur.execute('''INSERT INTO gis.definition_field(
          id,source_layer_id,physical_name,standard_name,label,storage_data_type,storage_udt_name,
          max_length,kind,widget_type,visible,required,readonly,sort_order,layout)
          VALUES (%s,%s,'saa_cde','SAA_CDE','관종','character varying(10)','varchar',10,
          'text','text',true,false,false,10,'{"section":"기본","width":6}'::jsonb)''',[field_id,self.pipe])

        self.save('standard_field',id=field_id,label='관종 수정',kind='text',widget_type='combo',
                  visible='true',required='true',readonly='true',sort_order='20')
        first=defs.snapshot(self.cur)
        saved=next(field for field in first['fields'] if field['id']==field_id)
        self.assertEqual((saved['label'],saved['kind'],saved['widget_type']),('관종 수정','text','combo'))
        self.assertEqual((saved['visible'],saved['form_visible'],saved['table_visible'],
                          saved['required'],saved['readonly'],saved['sort_order']),
                         (True,True,True,True,True,20))
        self.assertEqual((saved['storage_data_type'],saved['max_length']),('character varying(10)',10))
        self.assertEqual(saved['layout'], {'section':'기본','width':6})

        final=resolve(first,{'group_id':None,'additions':{},'private_items':{},'overrides':{}},
                      [next(layer for layer in first['layers'] if layer['id']==self.pipe)])
        resolved=next(field for field in final['fields'] if field['id']==field_id)
        self.assertEqual((resolved['label'],resolved['semantic_data_type'],resolved['widget_type']),
                         ('관종 수정','text','combo'))
        self.assertEqual((resolved['visible'],resolved['required'],resolved['readonly'],resolved['display_order']),
                         (True,True,True,20))

        reloaded=defs.snapshot(self.cur)
        persisted=next(field for field in reloaded['fields'] if field['id']==field_id)
        self.assertEqual((persisted['label'],persisted['widget_type'],persisted['sort_order']),
                         ('관종 수정','combo',20))
        self.assertEqual((persisted['form_visible'],persisted['table_visible']),(True,True))
        self.assertEqual(persisted['layout'], {'section':'기본','width':6})

    def test_standard_field_ignores_layout_payload_but_additional_field_validates_it(self):
        field_id=str(uuid4())
        self.cur.execute('''INSERT INTO gis.definition_field(
          id,source_layer_id,physical_name,standard_name,label,kind,widget_type,layout)
          VALUES (%s,%s,'mop_cde','MOP_CDE','재질','text','text','{"section":"시설"}'::jsonb)''',
          [field_id,self.pipe])

        self.save('standard_field',id=field_id,label='재질 수정',kind='text',widget_type='combo',
                  visible='true',sort_order='30',layout='["표준 화면에서는 무시"]')
        self.cur.execute('SELECT layout FROM gis.definition_field WHERE id=%s',[field_id])
        self.assertEqual(self.cur.fetchone()[0], {'section':'시설'})

        with self.assertRaisesRegex(defs.DefinitionError, '레이아웃은 객체여야 합니다'):
            self.save('field',label='추가 필드',kind='text',layout='[]')

    def test_physical_numeric_metadata_is_not_text(self):
        source={'layers':[{'standard_name':'PIPE','physical_name':'pipe','label':'관로','domain_code':'WATER','geometry_kind':'LINE','sort_order':1}],
          'bindings':[],'codes':[],
          'fields':[{'layer_name':'PIPE','layer_table':'pipe','physical_name':'pip_dip','storage_data_type':'numeric(10,2)',
            'storage_udt_name':'numeric','nullable':True,'storage_default':None,'max_length':None,'precision':10,'scale':2,
            'standard_name':'PIP_DIP','label':'관경','legacy_widget_type':'','metadata_required':False,'sort_order':1,
            'unit':'','description':'','code_group_key':'','profile_required':False,'profile_readonly':False,'profile_visible':True}]}
        old={'groups':[],'layers':[],'layer_catalogs':[],'fields':[],'field_layers':[],'codes':[],
             'scopes':[],'group_layers':[],'group_fields':[],'rules':[]}
        self.cur.execute('DROP SCHEMA gis CASCADE')
        transition._create(self.cur,(ROOT/'docs/architecture/gis-central-definitions.sql').read_text())
        transition._restore_authored(self.cur,old,source)
        row=defs.snapshot(self.cur)['fields'][0]
        self.assertEqual((row['storage_data_type'],row['kind'],row['widget_type'],row['precision'],row['scale']),
                         ('numeric(10,2)','decimal','decimal',10,2))

    def test_project_runtime_uses_layer_uuid(self):
        self.cur.execute('CREATE SCHEMA prj; CREATE TABLE prj.projects(id uuid PRIMARY KEY)')
        transition.prepare_project_runtime(self.cur)
        project=str(uuid4()); self.cur.execute('INSERT INTO prj.projects VALUES (%s)',[project])
        self.cur.execute("INSERT INTO gis.project_definition(project_id,additions,private_items) VALUES (%s,%s::jsonb,%s::jsonb)",
                         [project,json.dumps({'f':['MANHOLE']}),json.dumps({'x':{'source_layer':'PIPE'}})])
        transition.migrate_project_config(self.cur,{'MANHOLE':self.manhole,'PIPE':self.pipe})
        config=project_config(self.cur,project)
        self.assertEqual(config['additions']['f'],[self.manhole])
        self.assertEqual(config['private_items']['x']['source_layer_id'],self.pipe)

    def test_tenant_physical_schema_drives_type_and_legacy_runtime_fk_transition(self):
        self.cur.execute('DROP SCHEMA gis CASCADE; CREATE SCHEMA gis')
        feature_id=str(uuid4()); field_id=str(uuid4()); profile_id=str(uuid4())
        survey_id=str(uuid4()); target_id=str(uuid4())
        self.cur.execute('''CREATE TABLE gis.pipe(id uuid PRIMARY KEY,pip_dip numeric(10,2),memo varchar(80));
          CREATE TABLE gis.meta_feature_type(id uuid PRIMARY KEY,standard_name text,physical_name text,
            label text,domain_code text,geometry_kind text,feature_role text,scope_type text,sort_order int,active bool);
          CREATE TABLE gis.meta_field_def(id uuid PRIMARY KEY,feature_type_id uuid REFERENCES gis.meta_feature_type,
            physical_name text,standard_name text,label text,widget_type text,required_default bool,sort_order int,
            unit text,description text,code_group_key text);
          CREATE TABLE gis.profile(id uuid PRIMARY KEY);
          CREATE TABLE gis.profile_field(id uuid PRIMARY KEY,profile_id uuid REFERENCES gis.profile,
            field_def_id uuid REFERENCES gis.meta_field_def,enabled bool,required bool,editable bool,visible bool,sort_order int);
          CREATE TABLE gis.profile_feature(id uuid PRIMARY KEY,profile_id uuid REFERENCES gis.profile,
            feature_type_id uuid REFERENCES gis.meta_feature_type);
          CREATE TABLE gis.project_profile(project_id uuid PRIMARY KEY,profile_id uuid REFERENCES gis.profile);
          CREATE TABLE gis.capability(id uuid PRIMARY KEY);
          CREATE TABLE gis.capability_feature(id uuid PRIMARY KEY,capability_id uuid REFERENCES gis.capability,
            feature_type_id uuid REFERENCES gis.meta_feature_type,enabled bool);
          CREATE TABLE gis.scope_binding(id uuid PRIMARY KEY,capability_id uuid REFERENCES gis.capability,
            catalog_level int,catalog_item_id uuid,active bool);
          CREATE TABLE gis.ref_code_group(id uuid PRIMARY KEY,group_key text,active bool);
          CREATE TABLE gis.ref_code_value(id uuid PRIMARY KEY,group_id uuid REFERENCES gis.ref_code_group,
            code text,label text,sort_order int,active bool,valid_from date,valid_to date);
          CREATE TABLE gis.survey(id uuid PRIMARY KEY);
          CREATE TABLE gis.survey_link(id uuid PRIMARY KEY,survey_id uuid REFERENCES gis.survey,
            feature_type_id uuid REFERENCES gis.meta_feature_type,target_id uuid);
          CREATE TABLE gis.import_batch(id uuid PRIMARY KEY,profile_id uuid REFERENCES gis.profile)''')
        self.cur.execute("INSERT INTO gis.meta_feature_type VALUES (%s,'PIPE','pipe','관로','WATER','LINE','ASSET','PROJECT',1,true)",[feature_id])
        self.cur.execute("INSERT INTO gis.meta_field_def VALUES (%s,%s,'pip_dip','PIP_DIP','관경','lineedit',false,2,'','','')",[field_id,feature_id])
        self.cur.execute('INSERT INTO gis.profile VALUES (%s)',[profile_id])
        self.cur.execute('INSERT INTO gis.profile_field VALUES (%s,%s,%s,true,false,true,true,2)',[str(uuid4()),profile_id,field_id])
        self.cur.execute('INSERT INTO gis.survey VALUES (%s); INSERT INTO gis.survey_link VALUES (%s,%s,%s,%s); INSERT INTO gis.import_batch VALUES (%s,%s)',
                         [survey_id,str(uuid4()),survey_id,feature_id,target_id,str(uuid4()),profile_id])

        source=transition.source_snapshot(self.cur)
        pip_dip=next(field for field in source['fields'] if field['physical_name']=='pip_dip')
        self.assertEqual((pip_dip['storage_data_type'],pip_dip['precision'],pip_dip['scale']),('numeric(10,2)',10,2))

        layer_id=str(uuid4())
        transition.migrate_runtime_fks(self.cur,{'PIPE':layer_id})
        self.cur.execute('SELECT layer_id::text FROM gis.survey_link')
        self.assertEqual(self.cur.fetchone()[0],layer_id)
        self.cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='gis' AND table_name='import_batch'")
        self.assertEqual({row[0] for row in self.cur.fetchall()},{'id','definition_revision'})
        transition.retire_legacy(self.cur)
        for table in transition.LEGACY_DEFINITION:
            self.cur.execute('SELECT to_regclass(%s)', ['gis.'+table])
            self.assertIsNone(self.cur.fetchone()[0])

    def test_bootstrap_builds_v3_from_physical_snapshot(self):
        source={'layers':[{'id':str(uuid4()),'standard_name':'PIPE','physical_name':'pipe','label':'관로',
                  'domain_code':'WATER','geometry_kind':'LINE','feature_role':'ASSET','scope_type':'PROJECT','sort_order':1}],
          'bindings':[],'codes':[],
          'fields':[{'layer_name':'PIPE','layer_table':'pipe','physical_name':'pip_dip','storage_data_type':'numeric(10,2)',
            'storage_udt_name':'numeric','nullable':True,'storage_default':None,'max_length':None,'precision':10,'scale':2,
            'standard_name':'PIP_DIP','label':'관경','legacy_widget_type':'','metadata_required':False,'sort_order':1,
            'unit':'','description':'','code_group_key':'','profile_required':False,'profile_readonly':False,'profile_visible':True}]}
        self.cur.execute('DROP SCHEMA gis CASCADE; CREATE SCHEMA gis')
        created=transition.bootstrap(self.cur,source,(ROOT/'docs/architecture/gis-central-definitions.sql').read_text())
        self.assertTrue(created)
        self.cur.execute("SELECT kind,widget_type,storage_data_type,precision,scale FROM gis.definition_field WHERE physical_name='pip_dip'")
        self.assertEqual(self.cur.fetchone(),('decimal','decimal','numeric(10,2)',10,2))
        self.cur.execute("SELECT obj_description('gis.definition_group'::regclass)")
        self.assertEqual(self.cur.fetchone()[0],transition.V3_COMMENT)
