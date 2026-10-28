"""DB-free central direction contract tests; production writes are not exercised."""
import json
import unittest
from uuid import uuid4
from unittest.mock import Mock
from control.services.gis_definitions import mutate
from geoflow_ops.gis.form_definitions import DefinitionError
from geoflow_ops.gis.central_definitions import resolve
from integrations.qgis.geoflow_connector.services.direction_math import validate_config


class DirectionDefinitionTests(unittest.TestCase):
    def setUp(self):
        self.ref=str(uuid4()); self.layer=str(uuid4()); self.field=str(uuid4())
        self.cfg=dict(reference_layer_ids=[self.ref],method='connected',distance=1,unit='m',
                      offset=0,allow_reverse=True,ambiguity='review',zero_axis='north',
                      positive_direction='clockwise',symbol_offset=90,axis_tolerance=1,tie_tolerance=0.01)
    def cursor(self):
        cur=Mock();cur.fetchone.return_value=(self.layer,'decimal','ang_dir');cur.fetchall.return_value=[(self.ref,)]
        return cur
    def test_save_existing_field_json_only(self):
        cur=self.cursor()
        self.assertEqual(mutate(cur,dict(action='direction',id=self.field,direction=json.dumps(self.cfg))),self.field)
        sql,params=cur.execute.call_args.args
        self.assertIn('jsonb_set',sql);self.assertEqual(params[-1],self.field)
        self.assertEqual(json.loads(params[0]),validate_config(self.cfg))
        self.assertFalse(any('ALTER TABLE' in call.args[0] or 'INSERT' in call.args[0] for call in cur.execute.call_args_list))
    def test_missing_reference_or_invalid_settings_fail_closed(self):
        cur=self.cursor();cur.fetchall.return_value=[]
        with self.assertRaises(DefinitionError):mutate(cur,dict(action='direction',id=self.field,direction=self.cfg))
        for key,value in [('method','name_guess'),('unit','degrees'),('reference_layer_ids',['not-uuid'])]:
            bad=dict(self.cfg);bad[key]=value
            with self.assertRaises(DefinitionError):mutate(self.cursor(),dict(action='direction',id=self.field,direction=bad))
    def test_final_form_preserves_authoritative_setting(self):
        field=dict(id=self.field,source_layer_id=self.layer,physical_name='ang_dir',standard_name='ANG_DIR',label='Angle',
                   kind='decimal',widget_type='decimal',sort_order=0,visible=True,required=False,readonly=False,
                   layout={'direction':self.cfg})
        layer=dict(id=self.layer,standard_name='ANY_POINT',physical_name='any_point',label='Anything',sort_order=0,active=True)
        data=dict(fields=[field],layers=[layer],groups=[],group_fields=[],codes=[],rules=[])
        result=resolve(data,{'group_id':None,'additions':{},'private_items':{},'overrides':{self.field:{'layout':{}}}},[layer])
        self.assertEqual(result['fields'][0]['direction'],self.cfg)

if __name__=='__main__':unittest.main()
