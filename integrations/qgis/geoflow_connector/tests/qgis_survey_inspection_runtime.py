"""Isolated QGIS canvas/identity regressions; no network or production data."""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QDialog, QPushButton, QListWidget
from qgis.core import QgsCoordinateReferenceSystem, QgsProject
from qgis.gui import QgsMapCanvas
from qgis_survey_popup_runtime import PopupTests, fixture, APP, SOURCE, SURVEY
from geoflow_connector.ui.survey_panel import SurveyPanel, inventory_rows
from geoflow_connector.ui.survey_inspection import location, detail, finite_pair


class InspectionTests(PopupTests):
    # Reuse isolated fixture setup, not the inherited popup test suite.
    def test_navigation_preserves_check_edit_selection_and_form(self):
        canvas = QgsMapCanvas()
        canvas.setDestinationCrs(QgsCoordinateReferenceSystem('EPSG:5186'))
        self.plugin.iface.mapCanvas = lambda: canvas
        popup = SurveyPanel(self.plugin, self.window)
        self.select_source(popup)
        rows = [dict(popup.point_rows[0], survey_no='B'),
                dict(popup.point_rows[0], id='50000000-0000-4000-8000-000000000002', survey_no='A', longitude=127.001)]
        popup.point_rows = rows
        popup._fill_points(popup.featureTable, rows)
        table = popup.featureTable
        table.setSortingEnabled(True)
        table.sortItems(1, Qt.SortOrder.AscendingOrder)
        table.selectRow(0)
        self.assertEqual(popup.inspection.selected(table)[0]['id'], rows[1]['id'])
        states = [table.item(i, 0).checkState() for i in range(2)]
        selected_fids = self.layer.selectedFeatureIds()
        self.layer.startEditing()
        self.plugin.work._dirty_page = lambda: object()
        self.plugin.work.on_feature_selected = Mock()
        popup.inspection.show(popup.inspection.selected(table))
        self.assertEqual(len(popup.inspection.bands), 1)
        self.assertGreater(canvas.extent().width(), 19)
        popup.inspection.show(rows, entire=True)
        self.assertEqual(len(popup.inspection.bands), 2)
        self.assertEqual(states, [table.item(i, 0).checkState() for i in range(2)])
        self.assertEqual(self.layer.selectedFeatureIds(), selected_fids)
        self.assertTrue(self.layer.isEditable())
        self.plugin.work.on_feature_selected.assert_not_called()
        self.plugin.active_client.post_json.assert_not_called()
        self.plugin.active_client.delete_json_detailed.assert_not_called()
        popup.inspection.clear()
        self.layer.rollBack()
        popup.close()
        canvas.deleteLater()

    def test_null_zero_raw_and_geometry_semantics(self):
        self.assertEqual(finite_pair(0, 0), (0, 0))
        for row in ({'raw_x': 1, 'raw_y': 2, 'raw_crs': 'EPSG:5186'},
                    {'x': None, 'y': 3, 'current_crs': 'EPSG:5186'},
                    {'longitude': float('nan'), 'latitude': 0}):
            with self.assertRaises(ValueError):
                location(row)
        g, crs = location({'longitude': 0, 'latitude': 0})
        self.assertEqual(g.asPoint().x(), 0)
        self.assertEqual(crs.authid(), 'EPSG:4326')
        g, crs = location({'geom': 'POINT (200000 500000)', 'geometry_crs': 'EPSG:5186'})
        self.assertEqual(crs.authid(), 'EPSG:5186')
        description = detail({'x': None, 'raw_x': 0, 'survey_no': 'N', 'source_row_id': '8'}, [])
        self.assertIn('현재 X/Y/Z: 좌표 없음', description)
        self.assertIn('원시 X/Y/Z: 0', description)

    def test_empty_history_is_not_source_and_other_profile_retained_rows(self):
        popup = SurveyPanel(self.plugin, self.window)
        from geoflow_connector.ui.survey_panel import QSettings
        import json
        QSettings().setValue(popup._deleted_sources_key(), json.dumps([SOURCE]))
        popup.sources(refresh_settings=False)
        self.assertEqual(popup.sourceCombo.findData(popup.RETAINED_POINTS), -1)
        original = self.plugin.active_client.get_json.side_effect
        point = {'id': SURVEY, 'source_row_id': '1', 'source_id': None, 'longitude': 0, 'latitude': 0}
        self.plugin.active_client.get_json.side_effect = lambda url: (
            {'ok': True, 'points': [point]} if 'survey-points/' in url else original(url))
        with patch.object(popup, '_deleted_source_ids', return_value=set()):
            popup.sources(refresh_settings=False)
            self.assertGreaterEqual(popup.sourceCombo.findData(popup.RETAINED_POINTS), 0)
        self.plugin.active_client.get_json.side_effect = lambda url: {'ok': False}
        with self.assertRaises(ValueError):
            popup.sources(refresh_settings=False)
        self.assertIn(SOURCE, popup._deleted_source_ids())
        popup.close()

    def test_missing_list_is_not_zero(self):
        for payload in ({}, {'ok': False}, {'points': None}, {'points': [{'id': 'invalid'}]}):
            with self.assertRaises(ValueError):
                inventory_rows(payload, 'points')
        self.assertEqual(inventory_rows({'ok': True, 'points': []}, 'points'), [])

    def test_pair_navigation_uses_survey_and_gis_uuid_after_sort(self):
        canvas = QgsMapCanvas()
        canvas.setDestinationCrs(QgsCoordinateReferenceSystem('EPSG:4326'))
        self.plugin.iface.mapCanvas = lambda: canvas
        QgsProject.instance().addMapLayer(self.layer)
        popup = SurveyPanel(self.plugin, self.window)
        self.select_source(popup)
        rows = [dict(popup.point_rows[0], survey_no='B'),
                dict(popup.point_rows[0], id='50000000-0000-4000-8000-000000000002', survey_no='A', longitude=127.000001)]
        popup._fill_points(popup.featureTable, rows)
        table = popup.featureTable
        for i in range(2):
            table.item(i, 0).setCheckState(Qt.CheckState.Checked)
        table.setSortingEnabled(True)
        table.sortItems(1, Qt.SortOrder.AscendingOrder)
        table.selectRow(0)
        feature = next(self.layer.getFeatures())
        with patch.object(popup, '_point_mapping', return_value={'layer': 'TEST_LAYER'}), \
             patch.object(popup, '_display_storage_code', return_value='SA100'), \
             patch('geoflow_connector.ui.survey_inspection.overlap_distance_m', return_value=0.1), \
             patch('geoflow_connector.ui.survey_inspection.nearby_targets', return_value=[{'feature': feature, 'distance_m': 0.1}]):
            popup.inspection.compare(table)
        pairs = popup.inspection.comparison_pairs
        self.assertEqual(len(pairs), 2)
        self.assertTrue(all(p[0]['id'] == rows[1]['id'] for p in pairs))
        dialog = popup.inspection.comparison_dialog
        listing = dialog.findChild(QListWidget)
        both = next(b for b in dialog.findChildren(QPushButton) if b.text() == '두 점 함께 보기')
        for i in range(len(pairs)):
            listing.setCurrentRow(i)
            both.click()
            self.assertEqual(len(popup.inspection.bands), 2)
        self.assertTrue(all(table.item(i, 0).checkState() == Qt.CheckState.Checked for i in range(2)))
        self.plugin.active_client.post_json.assert_not_called()
        popup.inspection.clear()
        dialog.close()
        popup.close()
        QgsProject.instance().removeMapLayer(self.layer.id())
        canvas.deleteLater()


if __name__ == '__main__':
    suite = unittest.TestSuite(InspectionTests(name) for name in InspectionTests.__dict__ if name.startswith('test_'))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
