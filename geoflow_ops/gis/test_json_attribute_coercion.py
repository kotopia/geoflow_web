import unittest
from .gpkg import PackageField
from .qgis_sync import _coerce_for_pg, SyncRejected

class JSONAttributeTests(unittest.TestCase):
    field = PackageField('ext_data','jsonb',True,True,1)
    def test_empty_ext_data_is_default_object(self):
        for value in (None,'',' \n '):
            self.assertEqual(_coerce_for_pg(value,self.field).adapted,{})
    def test_explicit_values_remain_intact(self):
        for value in ({'source':'field'}, '{"source":"field"}'):
            self.assertEqual(_coerce_for_pg(value,self.field).adapted,{'source':'field'})
    def test_malformed_data_is_not_silently_erased(self):
        for value in ('[object Object]','{bad','private-note'):
            with self.assertRaises(SyncRejected): _coerce_for_pg(value,self.field)
    def test_other_fields_keep_their_semantics(self):
        other=PackageField('gnss_meta','jsonb',True,True,1)
        self.assertIsNone(_coerce_for_pg(None,other))
        with self.assertRaises(SyncRejected): _coerce_for_pg('',other)
