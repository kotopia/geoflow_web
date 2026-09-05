from __future__ import annotations

from unittest import TestCase

from .gpkg import PackageField
from .qgis_sync import _coerce_for_pg


class QgisSyncCoercionTests(TestCase):
    @staticmethod
    def _field(name: str, data_type: str) -> PackageField:
        return PackageField(
            name=name,
            data_type=data_type,
            editable=True,
            visible=True,
            sort_order=1,
        )

    def test_null_ext_data_uses_empty_json_object(self):
        value = _coerce_for_pg(None, self._field("ext_data", "jsonb"))

        self.assertEqual(value.adapted, {})

    def test_other_nullable_json_field_preserves_null(self):
        value = _coerce_for_pg(None, self._field("metadata", "jsonb"))

        self.assertIsNone(value)

    def test_explicit_ext_data_json_is_preserved(self):
        value = _coerce_for_pg('{"source":"qgis"}', self._field("ext_data", "jsonb"))

        self.assertEqual(value.adapted, {"source": "qgis"})
