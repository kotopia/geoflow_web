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

    def test_all_declared_feature_json_object_defaults_are_covered(self):
        from pathlib import Path
        import re
        from .qgis_sync import _JSON_OBJECT_DEFAULT_FIELDS
        root = Path(__file__).resolve().parents[2]
        declared = set()
        for filename in ('gis-schema-foundation.sql', 'gis-initial-feature-tables-v0.1.sql'):
            sql = (root / 'docs/architecture' / filename).read_text()
            declared.update(re.findall(r"(\w+)\s+jsonb\s+NOT NULL\s+DEFAULT\s+'\{\}'", sql, re.I))
        self.assertEqual(declared, set(_JSON_OBJECT_DEFAULT_FIELDS))
        # Reproduce the pending mixed valve/survey batch's untouched JSON values.
        for name in declared:
            field = PackageField(name, 'jsonb', True, True, 1)
            for value in (None, '', '  '):
                self.assertEqual(_coerce_for_pg(value, field).adapted, {})
            self.assertEqual(_coerce_for_pg('{"measurement":12.3}', field).adapted, {'measurement':12.3})
            with self.assertRaises(SyncRejected):
                _coerce_for_pg('{unreadable measurement', field)
