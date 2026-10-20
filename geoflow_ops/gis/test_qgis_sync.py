from __future__ import annotations

from unittest import TestCase
from unittest.mock import MagicMock, patch

from .gpkg import PackageField
from .qgis_sync import (
    SyncOperation,
    _apply_operation,
    _coerce_for_pg,
)


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

    def test_facility_delete_executes_only_the_project_scoped_delete(self):
        operation = SyncOperation(
            "delete", "wtl_valv_ps", "WTL_VALV_PS",
            "33333333-3333-4333-8333-333333333333", {}, None,
        )
        cursor = MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.rowcount = 1
        connection = MagicMock()
        connection.cursor.return_value = cursor
        with (
            patch("geoflow_ops.gis.qgis_sync.connections", {"tenant": connection}),
            patch("geoflow_ops.gis.workers.validate_worker_assignment"),
        ):
            _apply_operation("tenant", "project", operation)
        self.assertEqual(cursor.execute.call_count, 1)
        self.assertIn('DELETE FROM "gis"."wtl_valv_ps"', cursor.execute.call_args.args[0])

    def test_explicit_ext_data_json_is_preserved(self):
        value = _coerce_for_pg('{"source":"qgis"}', self._field("ext_data", "jsonb"))

        self.assertEqual(value.adapted, {"source": "qgis"})
