import unittest
from survey.import_selection import (duplicate_status, local_date,
                                     metadata_candidates, point_metadata,
                                     review_rows)
from survey.import_file import SourceRow


class SelectionTests(unittest.TestCase):
    def test_exact_lineage_only_and_resurvey_kept(self):
        point = {'source_row_id': 'P1', 'raw_x': 1.0, 'raw_y': 2.0, 'raw_z': 3.0}
        old = {**point, 'source_group_id': 'group', 'raw_crs': 'EPSG:5186'}
        self.assertEqual(duplicate_status(point, [old], 'group', 'EPSG:5186'), 'DUPLICATE')
        for changed in ({**point, 'raw_x': 1.000001}, {**point, 'raw_z': 4}, {**point, 'survey_date': '2026-10-05'}):
            self.assertEqual(duplicate_status(changed, [old], 'group', 'EPSG:5186'), 'POSSIBLE_DUPLICATE')
        self.assertEqual(duplicate_status(point, [old]), 'POSSIBLE_DUPLICATE')
        self.assertEqual(duplicate_status(point, []), 'NEW')

    def test_invalid_rows_are_unchecked(self):
        rows = [SourceRow({'id': 'P1', 'x': 1, 'y': 2}, 2), SourceRow({'id': 'P2', 'x': 'bad', 'y': 2}, 3)]
        records = review_rows(rows, dict(source_row_id='id', raw_x='x', raw_y='y'),
            dict(original_file_name='file.csv', source_type='CSV', source_crs='EPSG:5186'))
        self.assertTrue(records[0]['checked'])
        self.assertEqual(records[1]['state'], 'ERROR'); self.assertFalse(records[1]['checked'])
        self.assertIn('3행', records[1]['error'])

    def test_date_priority_and_only_explicit_candidates(self):
        self.assertEqual(local_date('2026/05/20', '2026-10-05'), '2026-05-20')
        self.assertEqual(local_date('', '2026-10-05'), '2026-10-05')
        candidates = metadata_candidates(['이름', '코드', '측량일', 'PDOP', '안테나높이', 'survey_code'])
        self.assertEqual(candidates['pdop'], 'PDOP')
        self.assertNotIn('survey_code', candidates)

    def test_antenna_height_null_zero_and_invalid_policy(self):
        mapping = {'antenna_height': 'Antenna Height'}
        self.assertNotIn('antenna_height', point_metadata(
            {'Antenna Height': '   '}, mapped_columns=mapping))
        self.assertEqual(point_metadata(
            {'Antenna Height': '0'}, mapped_columns=mapping
        )['antenna_height'], 0.0)
        self.assertEqual(point_metadata(
            {'Antenna Height': '1.75'}, mapped_columns=mapping
        )['antenna_height'], 1.75)
        with self.assertRaisesRegex(ValueError, '숫자가 아닙니다'):
            point_metadata({'Antenna Height': 'invalid'}, mapped_columns=mapping)


if __name__ == '__main__':
    unittest.main()
