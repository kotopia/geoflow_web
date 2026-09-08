import unittest
import uuid
from .gpkg import PackageField
from .qgis_sync import _coerce_for_pg, SyncRejected


class UUIDAttributeTests(unittest.TestCase):
    field = PackageField('worker_id', 'uuid', True, True, 1)

    def test_empty_reference_is_absent(self):
        for value in (None, '', '  '):
            self.assertIsNone(_coerce_for_pg(value, self.field))

    def test_uuid_is_canonical(self):
        canonical = '90000000-0000-4000-8000-000000000101'
        for value in (canonical, '{' + canonical + '}', uuid.UUID(canonical)):
            self.assertEqual(_coerce_for_pg(value, self.field), canonical)

    def test_invalid_reference_rejected_without_exposing_value(self):
        for value in ('private-worker-name', 'NULL', 1, False, {}):
            with self.subTest(value=value):
                with self.assertRaises(SyncRejected) as caught:
                    _coerce_for_pg(value, self.field)
                self.assertEqual(str(caught.exception), 'worker_id: invalid UUID')
                self.assertEqual(caught.exception.details, [{'field':'worker_id','reason':'invalid_uuid'}])

    def test_text_empty_string_is_preserved(self):
        text = PackageField('name', 'text', True, True, 1)
        self.assertEqual(_coerce_for_pg('', text), '')
