import datetime as dt
import unittest
from decimal import Decimal
from .gpkg import PackageField
from .qgis_sync import _coerce_for_pg, SyncRejected

class ScalarAttributeTests(unittest.TestCase):
    def field(self, kind): return PackageField('test_field',kind,True,True,1)
    def test_blank_typed_fields_are_absent(self):
        for kind in ('date','timestamp','timestamptz','timestamp(6) with time zone','time','integer','numeric(12,3)','double precision','boolean','uuid'):
            for value in ('',' \n ',None):
                with self.subTest(kind=kind,value=value):
                    self.assertIsNone(_coerce_for_pg(value,self.field(kind)))
    def test_valid_values_keep_type_and_precision(self):
        cases=[('date','2026-09-08',dt.date(2026,9,8)),('date','2026-09-08T00:00:00.000Z',dt.date(2026,9,8)),('timestamp','2026-09-08T12:34:56',dt.datetime(2026,9,8,12,34,56)),('timestamptz','2026-09-08T12:34:56Z',dt.datetime(2026,9,8,12,34,56,tzinfo=dt.timezone.utc)),('time','12:34:56',dt.time(12,34,56)),('integer',1.0,1),('numeric(12,3)','123.456',Decimal('123.456')),('boolean','false',False)]
        for kind,value,expected in cases:self.assertEqual(_coerce_for_pg(value,self.field(kind)),expected)
    def test_bad_nonempty_values_identify_field_without_exposing_value(self):
        for kind,value in [('date','2026-02-30'),('date','private text'),('timestamp','Invalid Date'),('time','99:00'),('integer','1.5'),('numeric','NaN'),('real','Infinity'),('boolean','maybe')]:
            with self.subTest(kind=kind,value=value):
                with self.assertRaises(SyncRejected) as caught:_coerce_for_pg(value,self.field(kind))
                self.assertIn('test_field:',str(caught.exception));self.assertNotIn(value,str(caught.exception))
                self.assertEqual(caught.exception.details[0]['field'],'test_field')
    def test_text_and_json_remain_separate(self):
        self.assertEqual(_coerce_for_pg('',self.field('text')),'')
        with self.assertRaises(SyncRejected):_coerce_for_pg('',self.field('jsonb'))
