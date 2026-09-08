from __future__ import annotations

from unittest import TestCase
from unittest.mock import patch

from .gpkg import PackageField
from .qgis_sync import SyncConflict, SyncOperation, _apply_operation, _coerce_for_pg


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

    def test_every_delete_transport_requires_explicit_survey_unlink(self):
        operation = SyncOperation(
            "delete", "wtl_valv_ps", "WTL_VALV_PS",
            "33333333-3333-4333-8333-333333333333", {}, None,
        )
        with patch("geoflow_ops.gis.qgis_sync._dependent_survey_link_count", return_value=2):
            with self.assertRaises(SyncConflict) as caught:
                _apply_operation("tenant", "project", operation)
        self.assertEqual(caught.exception.conflicts[0]["reason"], "survey_links_exist")
        self.assertEqual(caught.exception.conflicts[0]["link_count"], 2)

    def test_explicit_ext_data_json_is_preserved(self):
        value = _coerce_for_pg('{"source":"qgis"}', self._field("ext_data", "jsonb"))

        self.assertEqual(value.adapted, {"source": "qgis"})
