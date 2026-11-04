from copy import deepcopy
from decimal import Decimal
from tempfile import TemporaryDirectory
import unittest

from integrations.qgis.geoflow_qc_structure.references import CodeBooks, aggregate_values, convert, import_rows, validate_book
from integrations.qgis.geoflow_qc_structure.catalog import LocalCatalogProvider, validate_operation


def book(code='P1', agency='A'):
    return dict(id='material_' + agency, agency=agency, business='water', kind='material', mapping_id='survey',
                entries=[dict(code=code, name='Polyethylene', meaning='material.pe', aliases=['PE', 'Poly'])])


class ReferenceTests(unittest.TestCase):
    def test_exact_aliases_and_agencies(self):
        for agency, code in [('A', 'P1'), ('B', 'PE02')]:
            params = dict(book=book(code, agency))
            self.assertEqual(convert('PE', params), code)
            self.assertEqual(convert('Poly', params), code)
            for value in ['pedc', 'pe', ' PE ', None, '']:
                with self.assertRaises(ValueError):
                    convert(value, params)
            self.assertEqual(convert(' pe ', dict(params, trim=True, casefold=True)), code)
            self.assertEqual(convert('pedc', dict(params, unregistered='keep')), 'pedc')
            self.assertIsNone(convert('pedc', dict(params, unregistered='null')))
            self.assertEqual(convert('pedc', dict(params, unregistered='value', unregistered_value='X')), 'X')

    def test_collision_and_import(self):
        b = book()
        b['entries'][0]['aliases'].append('pe')
        validate_book(b)
        with self.assertRaises(ValueError):
            validate_book(b, casefold=True)
        rows = [['Meaning', '["PE", "Poly"]', '001', 'Name']]
        entries = import_rows(rows, dict(code=2, name=3, meaning=0, aliases=1))
        self.assertEqual(entries[0]['code'], '001')
        b['entries'] = entries
        validate_book(b)
        b['entries'] += deepcopy(entries)
        with self.assertRaises(ValueError):
            validate_book(b)
        with self.assertRaises(ValueError):
            import_rows([[1, 'Name', 'Meaning', '[]']], dict(code=0, name=1, meaning=2, aliases=3))

    def test_immutable_book_and_profile(self):
        with TemporaryDirectory() as directory:
            store = CodeBooks(directory)
            first = store.save(book())
            edited = deepcopy(first)
            edited['entries'][0]['code'] = 'P2'
            second = store.save(edited)
            self.assertEqual([b['revision'] for b in store.revisions()], [1, 2])
            self.assertEqual(convert('PE', dict(book=first)), 'P1')
            self.assertEqual(convert('PE', dict(book=second)), 'P2')
            provider = LocalCatalogProvider(directory)
            profile = provider.resolve('DAEJEON_WATER_PIPE_PILOT')
            profile['field_rules']['FACILITY_CODE'].update(operation='CODE_MAP', params=dict(source_field='mat', book=first))
            provider.save(profile)
            reread = LocalCatalogProvider(directory).resolve(profile['id'])
            self.assertEqual(reread['field_rules']['FACILITY_CODE']['params']['book'], first)
            edited['kind'] = 'other'
            with self.assertRaises(ValueError):
                store.save(edited)

    def test_aggregate_values_and_identity(self):
        result = aggregate_values([(1, None), (2, 0), (3, -2), (4, 5), (4, 5), (5, 5)])
        self.assertEqual((result['searched'], result['valid'], result['excluded']), (5, 4, 1))
        self.assertEqual((result['mean'], result['minimum'], result['maximum']), (Decimal(2), -2, 5))
        for values in [[], [(1, None)]]:
            self.assertIsNone(aggregate_values(values)['mean'])
        self.assertEqual(aggregate_values([(1, 2)])['mean'], 2)
        for value in ['2', True, float('nan')]:
            with self.assertRaises(ValueError):
                aggregate_values([(1, value)])


if __name__ == '__main__':
    unittest.main()
