import unittest
from scripts.dev.reconnect_qfield_project import replace_claim


class ClaimReplacementTests(unittest.TestCase):
    data = b'''<?xml version="1.0"?><!DOCTYPE qgis><qgis><properties><GeoFlow><project_id>p</project_id><server_url>http://192.168.0.6:8000</server_url><qfield_claim_token type="QString">old</qfield_claim_token></GeoFlow></properties><layers><!-- preserve me --></layers></qgis>'''
    connection = dict(format='geoflow_qfield_claim_recovery_v1', project_id='p', server_url='http://192.168.0.6:8000', claim_token='a'*40)

    def test_only_token_bytes_change(self):
        self.assertEqual(replace_claim(self.data, self.connection), self.data.replace(b'>old<', b'>' + b'a'*40 + b'<'))

    def test_wrong_project_and_server_rejected(self):
        for field in ('project_id', 'server_url', 'format', 'claim_token'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                replace_claim(self.data, dict(self.connection, **{field: 'wrong'}))

    def test_duplicate_and_missing_claim_rejected(self):
        for data in (self.data.replace(b'</GeoFlow>', b'<qfield_claim_token>extra</qfield_claim_token></GeoFlow>'), self.data.replace(b'qfield_claim_token', b'other_property')):
            with self.assertRaises(ValueError):
                replace_claim(data, self.connection)
