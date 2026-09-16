import unittest
from geoflow_ops.gis.form_definitions import identifier, text, DefinitionError
from control.services.gis_definitions import field_values

class DefinitionValidationTests(unittest.TestCase):
    def test_bad_identifiers(self):
        for v in (None,'','DROP TABLE x'):
            with self.assertRaises(DefinitionError): identifier(v)

    def test_numeric_limits(self):
        for d in ({'kind':'decimal','precision':0},{'kind':'decimal','precision':4,'scale':5},
                  {'kind':'text','max_length':0},{'kind':'sql'}):
            with self.assertRaises(DefinitionError): field_values({'label':'시험',**d})

    def test_precision_and_order(self):
        self.assertEqual(field_values({'label':'길이','kind':'decimal','precision':8,'scale':3,'sort_order':12}),
                         ['길이','decimal',None,8,3,12])
