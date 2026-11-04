from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
import xml.etree.ElementTree as ET
import zipfile

from integrations.qgis.geoflow_qc_structure.catalog import LocalCatalogProvider, validate_field
from integrations.qgis.geoflow_qc_structure.qc import blocked, run_qc, type_valid, number_digits
from integrations.qgis.geoflow_qc_structure.structure import operation, preview, post_qc
from scripts.qgis.build_plugin_repository import build_zip, build_xml, metadata


class FixtureSpatial:
    crs = None

    def exists(self, geometry):
        return geometry is not None

    def valid(self, geometry):
        return geometry == 'line'

    def geometry_type(self, geometry):
        return 'LINESTRING'

    def geometry_key(self, geometry):
        return geometry

    def measure(self, geometry, params, kind):
        return {'LENGTH': 10, 'AREA': 20, 'ANGLE': 90}[kind]

    def lookup(self, geometry, params, kind, existence=False):
        if existence:
            return geometry == 'line'
        return {'START_REFERENCE': 'A', 'END_REFERENCE': 'B', 'SPATIAL_LOOKUP': 'C'}[kind]


class PilotTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.provider = LocalCatalogProvider(temp.name)
        self.spatial = FixtureSpatial()
        self.p = self.provider.resolve('DAEJEON_WATER_PIPE_PILOT')
        self.fields = self.provider.get_fields()

    def test_field_contract(self):
        f = dict(semantic_key='X',physical_name='x',data_type='VARCHAR',length=6)
        for kind in ('CHAR','VARCHAR'):
            validate_field(dict(f,data_type=kind))
            with self.assertRaises(ValueError):
                validate_field(dict(f,data_type=kind,length=0))
        validate_field(dict(f,data_type='NUMERIC',precision=5,scale=2))
        with self.assertRaises(ValueError):
            validate_field(dict(f,data_type='NUMERIC',precision=2,scale=3))
        validate_field(dict(f,data_type='GEOMETRY',geometry_type='MULTILINESTRING',srid=5186))
        with self.assertRaises(ValueError):
            validate_field(dict(f,data_type='GEOMETRY',geometry_type='bad',srid=5186))
        self.assertEqual(number_digits(Decimal('0.00120')),(0,4))
        self.assertTrue(type_valid(date(2026,1,1),'DATE'))
        self.assertFalse(type_valid('2026-01-01','DATE'))
        self.assertTrue(type_valid(32767,'SMALLINT'))
        self.assertFalse(type_valid(32768,'SMALLINT'))
        self.assertFalse(type_valid(True,'INTEGER'))

    def test_qc_results(self):
        types = [
            ('REQUIRED', 'name', {}),('NULL_CHECK','a',{}),
            ('TYPE_CHECK','id',{'data_type':'INTEGER'}),
            ('LENGTH_CHECK','name',{'length':3}),
            ('PRECISION_CHECK','n',{'precision':3,'scale':1}),
            ('SCALE_CHECK','n',{'scale':1}),
            ('RANGE_CHECK','n',{'min':0,'max':5}),
            ('REFERENCE_CODE_VALID','name',{'codes':['good']}),
            ('GEOMETRY_VALID',None,{}),('DUPLICATE','id',{}),
            ('REFERENCE_EXISTS',None,{}),('START_REFERENCE',None,{}),('END_REFERENCE',None,{})
        ]
        rules = {t:dict(type=t,field=f,params=p) for t,f,p in types}
        rows = [(1,dict(name='    ',id='x',n=100.22,a=None),'bad'),
                (2,dict(name='good',id='x',n=1,a=1),'line')]
        findings = run_qc('layer',rows,rules,self.spatial,'PRE',selected={1})
        self.assertEqual({f.rule_id for f in findings},{t for t,_,_ in types})
        self.assertTrue(blocked(findings))
        self.assertTrue(all(f.feature_id == 1 for f in findings))

    def test_operations_dispatch(self):
        attrs = {'x':1}
        cases = [('KEEP',{},1),('COPY',{'source_field':'x'},1),('CONSTANT',{'value':5},5),
                 ('LENGTH',{},10),('AREA',{},20),('ANGLE',{},90),
                 ('CODE_MAP',{'source_field':'x','mapping':{'1':'C'}},'C'),
                 ('START_REFERENCE',{},'A'),('END_REFERENCE',{},'B'),('SPATIAL_LOOKUP',{},'C'),
                 ('CONDITION',{'source_field':'x','equals':1,'then':'Y','else':'N'},'Y')]
        for name,p,expected in cases:
            self.assertEqual(operation(name,p,attrs,'line',self.spatial,'x'),expected)

    def test_revision_history_and_override(self):
        raw = self.provider.profiles()[self.p['id']]
        raw['field_rules']['EXTRA'] = {'operation':'CONSTANT','params':{'value':'X'},
            'field':dict(semantic_key='EXTRA',physical_name='extra',data_type='CHAR',length=1)}
        saved = self.provider.save(raw)
        self.assertEqual(saved['revision'],2)
        self.assertIn('EXTRA',self.provider.resolve(raw['id'])['field_rules'])
        raw['field_rules']['EXTRA']['params']['value'] = 'Y'
        self.assertEqual(self.provider.save(raw)['revision'],3)
        self.assertEqual(len(list((self.directory/'profiles').glob('*.json'))),2)
        self.assertEqual(saved['snapshot']['profile']['field_rules']['EXTRA']['params']['value'],'X')
        self.assertIn('line_geometry',self.p['qc_rules'])
        self.assertEqual(self.p['field_rules']['PIPE_LENGTH']['target'],'BYC_LEN')

    def test_block_warning_preview_post_and_source_protection(self):
        source = [(1,{'pip_len':3.25},None)]
        findings,changes,rows,fields = preview('pipe',source,self.p,self.fields,self.spatial)
        self.assertTrue(blocked(findings))
        self.assertFalse(rows)
        p = dict(self.p,qc_rules={'missing':dict(type='NULL_CHECK',field='pip_len',severity='WARNING')})
        findings,changes,rows,fields = preview('pipe',[(1,{'pip_len':None},'line')],p,self.fields,self.spatial)
        self.assertFalse(blocked(findings))
        self.assertEqual(len(changes),3)
        overflow = deepcopy(self.p)
        overflow['field_rules']['PIPE_LENGTH'].update(operation='CONSTANT', params={'value':1000.25})
        f,c,r,s = preview('pipe',[(1,{},'line')],overflow,self.fields,self.spatial)
        self.assertTrue(blocked(post_qc('pipe',r,self.p,s,self.spatial)))
        self.assertEqual(source,[(1,{'pip_len':3.25},None)])

    def test_supplied_sql_subset_parity(self):
        # In-memory fixture, reproducing only the three assignments in the source SQL.
        source = [(1,{'pip_len':12.34},'line'),(2,{'pip_len':None},'line')]
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE pipe (pip_len REAL, BYC_LEN REAL, ftr_cde TEXT, mng_cde TEXT)')
            db.executemany('INSERT INTO pipe (pip_len) VALUES (?)',[(12.34,),(None,)])
            db.execute("UPDATE pipe SET BYC_LEN = pip_len, ftr_cde = 'SA001', mng_cde = 'MNG002'")
            expected = db.execute('SELECT BYC_LEN, ftr_cde, mng_cde FROM pipe ORDER BY rowid').fetchall()
        copy_profile = deepcopy(self.p)
        copy_profile['field_rules']['PIPE_LENGTH'].update(operation='COPY', params={'source_field':'pip_len'})
        findings, changes, rows, fields = preview('pipe',source,copy_profile,self.fields,self.spatial)
        actual = [(float(v['BYC_LEN']) if v['BYC_LEN'] is not None else None,v['ftr_cde'],v['mng_cde']) for _,v,_ in rows]
        self.assertEqual(actual,expected)
        self.assertFalse(post_qc('pipe',rows,self.p,fields,self.spatial))

    def test_generated_fields_without_source_attributes(self):
        source = [(1, {}, 'line'), (2, {'pip_len': None, 'ftr_cde': None}, 'line')]
        findings, changes, rows, fields = preview('pipe', source, self.p, self.fields, self.spatial)
        self.assertFalse(blocked(findings))
        self.assertTrue(all(values == {'BYC_LEN': Decimal('10.00'), 'ftr_cde': 'SA001', 'mng_cde': 'MNG002'}
                            for _, values, _ in rows))
        self.assertFalse(post_qc('pipe', rows, self.p, fields, self.spatial))
        self.assertEqual(source[0][1], {})

    def test_output_precision_and_facility_value_choice(self):
        class Measured(FixtureSpatial):
            def measure(self, geometry, params, kind):
                return 12.345
        profile = deepcopy(self.p)
        rule = profile['field_rules']['PIPE_LENGTH']
        for target, scale, expected in [('pip_len', 1, Decimal('12.3')), ('byc_len', 2, Decimal('12.35'))]:
            rule['target'] = target
            rule['field'].update(physical_name=target, precision=5, scale=scale)
            profile['field_rules']['FACILITY_CODE'].update(operation='COPY', params={'source_field':'ftr_cde'})
            source = [(1, {'ftr_cde':'SA200'}, 'line'), (2, {'ftr_cde':'SA203'}, 'line'), (3, {'ftr_cde':None}, 'line')]
            findings, changes, rows, fields = preview('pipe', source, profile, self.fields, Measured())
            self.assertFalse(blocked(findings))
            self.assertEqual([attrs['ftr_cde'] for _,attrs,_ in rows], ['SA200','SA203',None])
            self.assertTrue(all(attrs[target] == expected for _,attrs,_ in rows))
            self.assertFalse(post_qc('pipe', rows, profile, fields, Measured()))
        profile['field_rules']['FACILITY_CODE'].update(operation='CONSTANT', params={'value':'SA001'})
        _, _, rows, _ = preview('pipe', source, profile, self.fields, Measured())
        self.assertEqual([attrs['ftr_cde'] for _,attrs,_ in rows], ['SA001']*3)
        profile['field_rules']['FACILITY_CODE'].update(operation='COPY', params={'source_field':'missing'})
        _, changes, _, _ = preview('pipe', source, profile, self.fields, Measured())
        self.assertTrue(any(row[-1].startswith('ERROR') for row in changes))

    def test_package_and_existing_entry_preservation(self):
        from scripts.ops import publish_qgis_plugin_repository as publish
        source = Path('integrations/qgis/geoflow_qc_structure')
        filename = source.name+'-'+metadata(source)['version']+'.zip'
        dest = self.directory/filename
        sha = build_zip(source,dest)
        self.assertEqual(sha,build_zip(source,self.directory/'repeat.zip'))
        xml = build_xml(metadata(source),publish.SITE+'releases/'+filename,filename,sha)
        previous = b'<plugins><pyqgis_plugin name="GeoFlow Connector"><file_name>geoflow_connector.zip</file_name><description>unchanged</description></pyqgis_plugin></plugins>'
        merged = ET.fromstring(publish.merge_test_index(previous,xml))
        self.assertEqual(ET.tostring(merged[0]),ET.tostring(ET.fromstring(previous)[0]))
        self.assertEqual(merged[1].findtext('file_name'),source.name+'.zip')
        self.assertEqual(publish.validate_package(xml,dest,'test')[1],sha)
        with self.assertRaises(SystemExit):
            publish.validate_package(xml,dest,'stable')
        with zipfile.ZipFile(dest) as z:
            self.assertTrue(all(n.startswith(source.name+'/') for n in z.namelist()))
            self.assertFalse(any('test_' in n or '__pycache__' in n for n in z.namelist()))


if __name__ == '__main__':
    unittest.main()

