from __future__ import annotations

from unittest import TestCase
from unittest.mock import MagicMock, patch

from .gpkg import PackageField
from .qgis_sync import (
    SyncOperation,
    _apply_operation,
    _coerce_for_pg,
    _detach_survey_links_for_deletes,
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

    def test_linked_facility_delete_detaches_provenance_then_deletes(self):
        operation = SyncOperation(
            "delete", "wtl_valv_ps", "WTL_VALV_PS",
            "33333333-3333-4333-8333-333333333333", {}, None,
        )
        detach = MagicMock(return_value=2)
        cursor = MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.rowcount = 1
        connection = MagicMock()
        connection.cursor.return_value = cursor
        with (
            patch("geoflow_ops.gis.qgis_sync._detach_survey_links_for_deletes", detach),
            patch("geoflow_ops.gis.qgis_sync.connections", {"tenant": connection}),
            patch("geoflow_ops.gis.workers.validate_worker_assignment"),
        ):
            _apply_operation("tenant", "project", operation)
        detach.assert_called_once_with("tenant", [operation], request=None)
        self.assertIn('DELETE FROM "gis"."wtl_valv_ps"', cursor.execute.call_args.args[0])

    def test_bulk_delete_detaches_links_in_one_update_without_n_plus_one(self):
        operations = [
            SyncOperation(
                "delete", "wtl_pipe_ps", "WTL_PIPE_PS",
                f"00000000-0000-4000-8000-{index:012d}", {}, None,
            )
            for index in range(38)
        ]
        exists_cursor = MagicMock()
        exists_cursor.__enter__.return_value = exists_cursor
        exists_cursor.fetchone.return_value = (True,)
        update_cursor = MagicMock()
        update_cursor.__enter__.return_value = update_cursor
        update_cursor.rowcount = 38
        connection = MagicMock()
        connection.cursor.side_effect = [exists_cursor, update_cursor]
        definition = {
            "layers": [{
                "id": "11111111-1111-4111-8111-111111111111",
                "physical_name": "wtl_pipe_ps",
            }]
        }
        with (
            patch("geoflow_ops.gis.qgis_sync.connections", {"tenant": connection}),
            patch("geoflow_ops.gis.central_definitions.central_snapshot", return_value=definition),
        ):
            detached = _detach_survey_links_for_deletes("tenant", operations)
        self.assertEqual(detached, 38)
        self.assertEqual(connection.cursor.call_count, 2)
        sql = update_cursor.execute.call_args.args[0]
        self.assertEqual(sql.count("(%s::uuid,%s::uuid)"), 38)
        self.assertIn("link_status='UNLINKED'", sql)

    def test_explicit_ext_data_json_is_preserved(self):
        value = _coerce_for_pg('{"source":"qgis"}', self._field("ext_data", "jsonb"))

        self.assertEqual(value.adapted, {"source": "qgis"})
