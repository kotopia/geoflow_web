"""Real QGIS/Qt and Dynamic Form save; mocked server, isolated settings."""
import json
import tempfile
from time import perf_counter
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID

from qgis_survey_popup_runtime import APP, fixture, PROJECT, SOURCE
from qgis.PyQt.QtCore import QDate, QSettings, Qt
from qgis.PyQt.QtWidgets import QLabel
from qgis.core import (QgsVectorLayer, QgsCoordinateReferenceSystem,
                       QgsCoordinateTransform, QgsDefaultValue, QgsFeature, QgsProject,
                       QgsPointXY, QgsVariantUtils)
from geoflow_connector.ui.survey_panel import SurveyPanel, SurveyValidationError
from geoflow_connector.forms.dynamic.binding import DynamicFormBinding
from geoflow_connector.forms.dynamic.form import DynamicForm
from geoflow_connector.survey.creation import apply_target_inheritance
from geoflow_connector.app.survey_integration import SurveyIntegrationMixin
from geoflow_connector.app.plugin import GeoFlowConnectorPlugin
from geoflow_connector.survey.code_mapping import (
    depth_create_key, facility_identity, read_depth_create_targets,
    read_storage_codes, storage_code_key, write_depth_create_targets,
    write_storage_codes,
)


class CreationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        settings_file = str(Path(self.temp.name) / 'survey.ini')
        self.patches = [patch(
            'geoflow_connector.ui.survey_panel.QSettings',
            side_effect=lambda: QSettings(settings_file, QSettings.Format.IniFormat),
        )]
        for item in self.patches: item.start()
        self.window, _, self.plugin = fixture()
        self.plugin._pull_and_apply_delta = Mock(return_value=0)
        self.layers = []
        for name, crs in (('A', 'EPSG:4326'), ('B', 'EPSG:5186'), ('C', 'EPSG:4326')):
            layer = QgsVectorLayer(
                f'Point?crs={crs}&field=id:string&field=FTR_CDE:string&field=status:string'
                '&field=project_id:string&field=worker_id:string&field=date:date'
                '&field=survey_no:string&field=survey_id:string&field=survey_source_id:string',
                name, 'memory')
            layer.setCustomProperty('geoflow/standard_name', name)
            layer.setCustomProperty('geoflow/physical_name', name.lower())
            layer.setDefaultValueDefinition(
                layer.fields().indexOf('status'), QgsDefaultValue("'미완료'")
            )
            self.layers.append(layer)
            QgsProject.instance().addMapLayer(layer)
        self.plugin._managed_layers = lambda: self.layers
        self.plugin.commit_layers_online = Mock(side_effect=lambda layers, **_kwargs: {
            "ok": all(layer.commitChanges(False) for layer in layers),
            "provider_commit_called": True,
            "provider_commit_result": True,
            "operation_counts": {"create": sum(
                layer.featureCount() for layer in layers
            ), "update": 0, "delete": 0},
        })
        self.points = [dict(id=f'50000000-0000-4000-8000-{i+1:012d}', source_row_id=f'P{i+1}',
                            raw_code=code, longitude=127.0 + i * .001, latitude=36.0,
                            survey_date='2026-10-08', worker_id='worker-A',
                            survey_no=f'261008-{i + 1:03d}')
                       for i, code in enumerate(
                           ('A1', 'A1', 'A1', 'B1', 'B1', 'B2', 'B2',
                            'C1', 'C1', 'C1'))]
        def get(url):
            if 'survey-sources/' in url:
                return {'results': [dict(id=SOURCE, original_file_name='six.csv', version=1)]}
            if 'survey-points/' in url:
                return {'results': self.points}
            return {'results': []}
        self.plugin.active_client.get_json.side_effect = get
        self.bindings = []
        def open_form(layer, feature):
            field = dict(id='FTR_CDE', label='FTR_CDE', layer_standard_name=layer.name(),
                         semantic_data_type='text', widget_type='text', visible=True, required=True,
                         readonly=False, display_order=1, layout={}, reference_codes=[],
                         storage=dict(kind='column', key='FTR_CDE'))
            form = DynamicForm({'fields': [field], 'rules': []}, [field])
            page = SimpleNamespace(note=QLabel(), dirty=False, feature_id=feature.id(), update_dirty=lambda: None)
            binding = DynamicFormBinding(page, layer, form, True)
            binding.load(layer.getFeature(feature.id()), force=True)
            self.binding = binding; self.bindings.append(binding)
        self.plugin.work.on_feature_selected = open_form
        self.popup = SurveyPanel(self.plugin, self.window)
        # Synthetic A1/B1/B2/C1 values are explicit standard-code aliases in
        # this fixture; production never derives these with raw_code.upper().
        self.popup._standard_code = lambda raw: (
            "J" if str(raw or "").strip() in {"j", "J", "je", "JE"}
            else (str(raw or "").strip() or None)
        )
        self.popup._saved_mappings = lambda: {code: dict(ftr_cde=code, layer=code[0]) for code in ('A1', 'B1', 'B2', 'C1')}
        self.popup._mapping_options = lambda: (
            [(code, code, code[0]) for code in ('A1', 'B1', 'B2', 'C1')]
            + [('SA900', '상수관로심도', 'WTL_PIPE_PS')]
        )
        self.popup._storage_codes = lambda: {
            facility_identity(code[0], code): {
                'facility_id': facility_identity(code[0], code),
                'facility_label': code, 'standard_name': code[0],
                'storage_field': 'ftr_cde', 'storage_code': code,
                'code_label': code,
            }
            for code in ('A1', 'B1', 'B2', 'C1')
        }
        self.popup.sourceCombo.setCurrentIndex(
            self.popup.sourceCombo.findData(SOURCE)
        )
        self.popup.render_features()

    def enable_exposed_depth_mode(self, points=None):
        for point in points or self.points:
            point["raw_data"] = {
                **(point.get("raw_data") or {}),
                "survey_work_code": "L3",
            }
        self.popup.creationModeCombo.setCurrentIndex(
            self.popup.creationModeCombo.findData(
                self.popup.CREATE_FACILITY_WITH_DEPTH
            )
        )
        self.popup.render_features()

    def tearDown(self):
        for method in ('get_json', 'post_json', 'post_json_detailed', 'delete_json_detailed'):
            for call in getattr(self.plugin.active_client, method).call_args_list:
                self.assertNotIn('survey-link', str(call))
        self.popup.close_service(); self.popup.close()
        for binding in self.bindings: binding.dispose()
        for layer in self.layers:
            if layer.isEditable(): layer.rollBack()
            QgsProject.instance().removeMapLayer(layer.id())
        self.window.close(); self.window.deleteLater()
        for item in reversed(self.patches): item.stop()
        self.temp.cleanup()

    def test_ten_features_three_layers_batch_without_dynamic_form(self):
        self.plugin.active_client.get_json.reset_mock()
        result = self.popup.start_selected()
        self.assertEqual(result, {'created': 10, 'failed': 0, 'errors': {}})
        self.assertEqual(self.plugin.commit_layers_online.call_count, 1)
        self.assertEqual(
            self.plugin.commit_layers_online.call_args.kwargs["trigger"],
            "survey_batch_create",
        )
        self.assertEqual([layer.featureCount() for layer in self.layers], [3, 4, 3])
        self.assertEqual(self.bindings, [])
        self.plugin._sync_active_project.assert_not_called()
        self.assertEqual(self.plugin.active_client.get_json.call_count, 0)
        self.plugin.active_client.post_json.assert_not_called()
        perf = self.popup._last_batch_performance
        self.assertLess(perf["unaccounted_ms"], 200)
        for layer in self.layers:
            features = sorted(layer.getFeatures(), key=lambda row: row.geometry().asPoint().x())
            expected_points = sorted(
                (point for point in self.points if point['raw_code'].startswith(layer.name())),
                key=lambda row: row['longitude'])
            for feature, point in zip(features, expected_points):
                UUID(str(feature['id']))
                self.assertTrue(QgsVariantUtils.isNull(feature['status']))
                self.assertEqual(feature['FTR_CDE'], point['raw_code'])
                self.assertEqual(feature['worker_id'], 'worker-A')
                self.assertEqual(feature['date'].toString('yyyy-MM-dd'), '2026-10-08')
                self.assertEqual(feature['survey_no'], point['survey_no'])
                self.assertTrue(QgsVariantUtils.isNull(feature['survey_id']))
                self.assertTrue(QgsVariantUtils.isNull(feature['survey_source_id']))
                self.assertEqual(str(feature['project_id']), PROJECT)
                transform = QgsCoordinateTransform(
                    QgsCoordinateReferenceSystem('EPSG:4326'), layer.crs(),
                    QgsProject.instance())
                expected = transform.transform(QgsPointXY(
                    point['longitude'], point['latitude']))
                self.assertLess(feature.geometry().asPoint().distance(expected), 1e-6)
        self.popup.refresh_creation_states()
        self.assertTrue(all(
            self.popup.featureTable.item(row, 0).checkState()
            == Qt.CheckState.Unchecked
            for row in range(self.popup.featureTable.rowCount())
        ))
        with self.assertRaisesRegex(ValueError, '생성할 측량점'):
            self.popup.start_selected()
        self.assertEqual(sum(layer.featureCount() for layer in self.layers), 10)

    def test_batch_5_13_20_50_uses_one_online_save(self):
        before_measurements, measurements, after_perf = {}, {}, {}
        for count in (5, 13, 20, 50):
            for layer in self.layers:
                self.assertTrue(layer.dataProvider().truncate())
            self.popup._selection.clear()
            self.plugin.commit_layers_online.reset_mock()
            points = [dict(
                id=f'70000000-0000-4000-8000-{index + 1:012d}',
                source_row_id=f'B{index + 1}', raw_code='A1',
                longitude=127.0 + index * .001, latitude=36.0,
                survey_date='2026-10-08', worker_id='worker-A',
            ) for index in range(count)]
            self.popup.point_rows = points
            self.popup.render_features()
            started = perf_counter()
            result = self.popup.start_selected()
            elapsed_ms = (perf_counter() - started) * 1000
            self.assertEqual(result['created'], count)
            self.assertEqual(self.plugin.commit_layers_online.call_count, 1)
            self.assertEqual(self.layers[0].featureCount(), count)
            self.assertEqual(self.popup._last_batch_performance['online_save_count'], 1)
            measurements[count] = elapsed_ms
            after_perf[count] = dict(self.popup._last_batch_performance)
            for layer in self.layers:
                self.assertTrue(layer.dataProvider().truncate())
            self.popup._selection.clear()
            self.plugin.commit_layers_online.reset_mock()
            self.popup.point_rows = points
            self.popup.render_features()
            legacy_started = perf_counter()
            for point in points:
                feature, _target_id = self.popup._new_target_feature(
                    self.layers[0], point, 'A1', null_status=True
                )
                if not self.layers[0].isEditable():
                    self.assertTrue(self.layers[0].startEditing())
                self.assertTrue(self.layers[0].addFeature(feature))
                result = self.plugin.commit_layers_online(
                    [self.layers[0]], stop_editing=False,
                    trigger='survey_per_feature_benchmark',
                )
                self.assertTrue(result['ok'])
            before_measurements[count] = (perf_counter() - legacy_started) * 1000
            self.assertEqual(self.layers[0].featureCount(), count)
            self.assertEqual(self.plugin.commit_layers_online.call_count, count)
        self.assertEqual(set(measurements), {5, 13, 20, 50})
        print("SURVEY_BATCH_BENCHMARK=" + json.dumps(
            {
                str(key): {
                    "before_ms": round(before_measurements[key], 3),
                    "after_ms": round(measurements[key], 3),
                    "before_online_save": key,
                    "after_online_save": 1,
                    "server_save_ms": after_perf[key]["online_save_ms"],
                    "unaccounted_ms": after_perf[key]["unaccounted_ms"],
                }
                for key in measurements
            },
            sort_keys=True,
        ))

    def test_missing_storage_code_has_structured_reason_and_context(self):
        self.popup._storage_codes = lambda: {}
        self.popup._saved_mappings = lambda: {
            code: {
                "facility_id": facility_identity(code[0], code),
                "facility_label": code, "layer": code[0],
            }
            for code in ('A1', 'B1', 'B2', 'C1')
        }
        with self.assertRaises(SurveyValidationError) as raised:
            self.popup.start_selected()
        error = raised.exception
        self.assertEqual(error.reason, "storage_code_missing")
        self.assertEqual(error.context["target_layer"], "A")
        self.assertEqual(error.context["storage_field"], "ftr_cde")
        self.assertEqual(error.context["survey_id"], self.points[0]["id"])
        self.assertEqual(error.context["raw_code"], "A1")
        self.assertEqual(error.context["survey_code"], "A1")

    def test_one_invalid_row_aborts_all_selected_before_online_save(self):
        configured = self.popup._storage_codes()
        configured.pop(facility_identity("A", "A1"))
        self.popup._storage_codes = lambda: configured
        self.popup._saved_mappings = lambda: {
            code: {
                "facility_id": facility_identity(code[0], code),
                "facility_label": code, "layer": code[0],
            }
            for code in ('A1', 'B1', 'B2', 'C1')
        }
        self.plugin.commit_layers_online.reset_mock()
        with self.assertRaises(SurveyValidationError) as raised:
            self.popup.start_selected()
        self.assertEqual(raised.exception.reason, "storage_code_missing")
        self.assertEqual(sum(layer.featureCount() for layer in self.layers), 0)
        self.plugin.commit_layers_online.assert_not_called()

    def test_layer_failure_aborts_whole_batch_before_server_save(self):
        self.layers[1].setReadOnly(True)
        with self.assertRaises(RuntimeError):
            self.popup.start_selected()
        self.assertEqual([layer.featureCount() for layer in self.layers], [0, 0, 0])
        self.plugin.commit_layers_online.assert_not_called()

    def test_single_row_auxiliary_still_opens_dynamic_form_draft(self):
        for row in range(1, self.popup.featureTable.rowCount()):
            self.popup.featureTable.item(row, 0).setCheckState(Qt.CheckState.Unchecked)
        self.popup.featureTable.setCurrentCell(0, 1)
        self.popup.create_draft()
        self.assertEqual(sum(l.featureCount() for l in self.layers), 1)
        self.assertEqual(len(self.bindings), 1)
        self.assertLess(self.binding.feature_id, 0)
        self.assertTrue(self.binding.discard())

    def test_missing_or_invalid_storage_code_is_blocked_before_create(self):
        for row in range(1, self.popup.featureTable.rowCount()):
            self.popup.featureTable.item(row, 0).setCheckState(Qt.CheckState.Unchecked)
        self.popup._saved_mappings = lambda: {
            "A1": {
                "facility_id": facility_identity("A", "A1"),
                "facility_label": "A1", "layer": "A",
            }
        }
        self.popup._storage_codes = lambda: {}
        with self.assertRaisesRegex(ValueError, "저장 코드가 설정되지 않았습니다"):
            self.popup.start_selected()
        self.assertEqual(sum(layer.featureCount() for layer in self.layers), 0)
        self.popup._storage_codes = lambda: {
            facility_identity("A", "A1"): {
                "standard_name": "A", "storage_code": "LABEL_NOT_A_CODE",
            }
        }
        with self.assertRaisesRegex(ValueError, "중앙 정의에 존재하지 않습니다"):
            self.popup.start_selected()
        self.assertEqual(sum(layer.featureCount() for layer in self.layers), 0)

    def test_offline_batch_reports_failure_without_persistent_queue(self):
        for row in range(1, self.popup.featureTable.rowCount()):
            self.popup.featureTable.item(row, 0).setCheckState(Qt.CheckState.Unchecked)
        self.plugin.active_client.post_json.side_effect = RuntimeError('offline')
        self.plugin.commit_layers_online.side_effect = RuntimeError('offline')
        with self.assertRaisesRegex(RuntimeError, 'offline'):
            self.popup.start_selected()
        self.assertEqual(sum(layer.featureCount() for layer in self.layers), 0)
        self.plugin.active_client.post_json.assert_not_called()

    def test_depth_draft_precalculates_without_post_save_relationship(self):
        layer = self.layers[0]
        layer.setCustomProperty('geoflow/standard_name', 'WTL_PIPE_PS')
        from qgis.core import QgsField
        from qgis.PyQt.QtCore import QMetaType
        layer.dataProvider().addAttributes([QgsField('pip_dep', QMetaType.Type.Double)])
        layer.updateFields()
        self.popup._point_mapping = lambda point: {
            'layer': 'WTL_PIPE_PS', 'facility_label': 'depth', 'facility_id': 'depth'}
        self.popup._storage_codes = lambda: {'depth': {'storage_code': 'SA900'}}
        self.popup._resolve_point_storage = lambda *a, **k: ({}, 'SA900', [])
        self.popup.featureTable.setCurrentCell(0, 1)
        with patch('geoflow_connector.services.depth.DepthService.calculate_survey_point',
                   return_value={'ok': True, 'depth': 2.5}):
            self.popup._create_draft()
        self.assertEqual(next(layer.getFeatures())['pip_dep'], 2.5)
        self.plugin.commit_layers_online.assert_not_called()
        self.plugin.active_client.post_json.assert_not_called()

    def test_same_batch_spatial_duplicate_aborts_before_save(self):
        self.points[1]['longitude'] = self.points[0]['longitude']
        self.popup.point_rows = self.points
        self.popup.render_features()
        with self.assertRaisesRegex(SurveyValidationError, 'P2 ↔ P1.*A / A1.*0.000m') as caught:
            self.popup.start_selected()
        self.assertEqual(caught.exception.context['conflicting_survey_id'], self.points[0]['id'])
        self.assertEqual(caught.exception.context['distance_m'], 0)
        self.plugin.commit_layers_online.assert_not_called()
        self.assertEqual(sum(layer.featureCount() for layer in self.layers), 0)

    def test_nearby_different_target_layers_are_allowed(self):
        self.points[3]['longitude'] = self.points[0]['longitude'] + .000005
        self.popup.render_features()
        self.assertEqual(self.popup.start_selected()['created'], 10)

    def test_nearby_same_layer_different_storage_codes_are_allowed(self):
        self.points[5]['longitude'] = self.points[3]['longitude'] + .000005
        self.popup.render_features()
        self.assertEqual(self.popup.start_selected()['created'], 10)

    def test_spatial_status_uses_type_project_and_current_geometry(self):
        point = self.points[0]
        layer = self.layers[0]
        feature, _ = self.popup._new_target_feature(layer, point, 'different')
        layer.dataProvider().addFeature(feature)
        self.assertTrue(self.popup._creation_state(point)[1])
        feature, _ = self.popup._new_target_feature(layer, point, 'A1')
        feature['project_id'] = 'other-project'
        layer.dataProvider().addFeature(feature)
        self.assertTrue(self.popup._creation_state(point)[1])
        feature, _ = self.popup._new_target_feature(layer, point, 'A1')
        layer.dataProvider().addFeature(feature)
        self.assertFalse(self.popup._creation_state(point)[1])
        moved = {**point, 'longitude': point['longitude'] + .01}
        self.assertTrue(self.popup._creation_state(moved)[1])

    def test_auxiliary_depth_duplicate_blocks_entire_batch(self):
        layer = QgsVectorLayer(
            'Point?crs=EPSG:4326&field=id:string&field=FTR_CDE:string&field=pip_dep:double',
            'depth-duplicate', 'memory')
        layer.setCustomProperty('geoflow/standard_name', 'WTL_PIPE_PS')
        self.layers.append(layer)
        QgsProject.instance().addMapLayer(layer)
        feature, _ = self.popup._new_target_feature(layer, self.points[0], 'SA900')
        layer.dataProvider().addFeature(feature)
        self.enable_exposed_depth_mode()
        self.popup._depth_create_targets = lambda: {('A', 'A1')}
        with self.assertRaisesRegex(ValueError, '동일 심도'):
            self.popup.start_selected()
        self.plugin.commit_layers_online.assert_not_called()
        self.assertEqual(sum(item.featureCount() for item in self.layers[:3]), 0)

    def test_atomic_failure_rolls_back_facility_and_depth(self):
        layer = QgsVectorLayer(
            'Point?crs=EPSG:4326&field=id:string&field=FTR_CDE:string&field=pip_dep:double',
            'depth-failure', 'memory')
        layer.setCustomProperty('geoflow/standard_name', 'WTL_PIPE_PS')
        self.layers.append(layer)
        QgsProject.instance().addMapLayer(layer)
        self.enable_exposed_depth_mode()
        self.popup._depth_create_targets = lambda: {('A', 'A1')}
        self.plugin.commit_layers_online.side_effect = lambda *a, **k: {'ok': False}
        with self.assertRaises(RuntimeError):
            self.popup.start_selected()
        self.assertEqual(self.plugin.commit_layers_online.call_count, 1)
        self.assertEqual(sum(item.featureCount() for item in self.layers), 0)

    def test_spatial_status_survives_new_panel_without_cache(self):
        self.popup.start_selected()
        self.plugin.active_client.get_json.reset_mock()
        # The status is computed from current geometries, including after restart.
        self.assertFalse(hasattr(self.plugin, '_survey_target_records'))
        self.popup.close()
        self.popup = SurveyPanel(self.plugin, self.window)
        self.popup._point_mapping = lambda point: {
            'layer': 'A', 'facility_id': 'fixture', 'facility_label': 'A1'}
        self.popup._storage_codes = lambda: {'fixture': {'storage_code': 'A1'}}
        self.plugin.active_client.get_json.reset_mock()
        self.assertEqual(self.popup._creation_state(self.points[0]), ('생성완료', False))
        self.plugin.active_client.get_json.assert_not_called()





    def test_missing_survey_date_overrides_1900_sentinel_with_null(self):
        layer = QgsVectorLayer("Point?field=date:date", "date-target", "memory")
        feature = QgsFeature(layer.fields())
        feature["date"] = QDate(1900, 1, 1)
        applied = apply_target_inheritance(feature, layer, {"survey_date": None})
        self.assertIn("date", applied)
        self.assertTrue(QgsVariantUtils.isNull(feature["date"]))

    def test_selected_ftr_code_creates_facility_and_depth_in_one_commit(self):
        depth_layer = QgsVectorLayer(
            "Point?crs=EPSG:4326&field=id:string&field=FTR_CDE:string"
            "&field=pip_dep:double&field=project_id:string&field=worker_id:string"
            "&field=date:date&field=survey_no:string&field=survey_id:string"
            "&field=survey_source_id:string",
            "depth", "memory",
        )
        depth_layer.setCustomProperty("geoflow/standard_name", "WTL_PIPE_PS")
        depth_layer.setCustomProperty("geoflow/physical_name", "wtl_pipe_ps")
        self.layers.append(depth_layer)
        QgsProject.instance().addMapLayer(depth_layer)
        self.enable_exposed_depth_mode()
        for row in range(1, self.popup.featureTable.rowCount()):
            self.popup.featureTable.item(row, 0).setCheckState(
                Qt.CheckState.Unchecked
            )
        self.popup._depth_create_targets = lambda: {("A", "A1")}
        atomic_calls = []
        def atomic_commit(layers, **kwargs):
            atomic_calls.append((list(layers), dict(kwargs)))
            return {
                "ok": all(layer.commitChanges(False) for layer in layers),
                "provider_commit_called": True,
            }
        self.plugin.commit_layers_online = Mock(side_effect=atomic_commit)
        with patch(
            "geoflow_connector.services.depth.DepthService.calculate_survey_point",
            return_value={"ok": True, "depth": 2.5, "distance_m": 1.0},
        ):
            result = self.popup.start_selected()
        self.assertEqual(result["created"], 1)
        self.assertEqual(self.layers[0].featureCount(), 1)
        self.assertEqual(depth_layer.featureCount(), 1)
        self.assertEqual(len(atomic_calls), 1)
        self.assertEqual(
            {layer.customProperty("geoflow/standard_name")
             for layer in atomic_calls[0][0]},
            {"A", "WTL_PIPE_PS"},
        )
        depth = next(depth_layer.getFeatures())
        self.assertEqual(depth["FTR_CDE"], "SA900")
        self.assertEqual(depth["pip_dep"], 2.5)
        self.assertEqual(depth["worker_id"], "worker-A")
        self.assertEqual(depth["date"].toString("yyyy-MM-dd"), "2026-10-08")
        self.assertEqual(depth["survey_no"], self.points[0]["survey_no"])
        state, eligible = self.popup._creation_state(self.points[0])
        self.assertFalse(eligible)

    def test_facility_only_mode_never_creates_auxiliary_depth(self):
        depth_layer = QgsVectorLayer(
            "Point?crs=EPSG:4326&field=id:string&field=FTR_CDE:string"
            "&field=pip_dep:double&field=survey_no:string",
            "facility-only-depth", "memory",
        )
        depth_layer.setCustomProperty("geoflow/standard_name", "WTL_PIPE_PS")
        depth_layer.setCustomProperty("geoflow/physical_name", "wtl_pipe_ps")
        self.layers.append(depth_layer)
        QgsProject.instance().addMapLayer(depth_layer)
        for row in range(1, self.popup.featureTable.rowCount()):
            self.popup.featureTable.item(row, 0).setCheckState(
                Qt.CheckState.Unchecked
            )
        self.assertEqual(
            self.popup._creation_mode(), self.popup.CREATE_FACILITY_ONLY
        )
        result = self.popup.start_selected()
        self.assertEqual(result["created"], 1)
        self.assertEqual(self.layers[0].featureCount(), 1)
        self.assertEqual(depth_layer.featureCount(), 0)
        committed = self.plugin.commit_layers_online.call_args.args[0]
        self.assertEqual([
            layer.customProperty("geoflow/standard_name") for layer in committed
        ], ["A"])

    def test_ten_facilities_and_depths_use_one_batch_commit(self):
        depth_layer = QgsVectorLayer(
            "Point?crs=EPSG:4326&field=id:string&field=FTR_CDE:string"
            "&field=pip_dep:double&field=project_id:string&field=worker_id:string"
            "&field=date:date&field=survey_no:string&field=survey_id:string"
            "&field=survey_source_id:string",
            "depth-ten", "memory",
        )
        depth_layer.setCustomProperty("geoflow/standard_name", "WTL_PIPE_PS")
        depth_layer.setCustomProperty("geoflow/physical_name", "wtl_pipe_ps")
        self.layers.append(depth_layer)
        QgsProject.instance().addMapLayer(depth_layer)
        self.enable_exposed_depth_mode()
        self.popup._depth_create_targets = lambda: {
            ("A", "A1"), ("B", "B1"), ("B", "B2"), ("C", "C1")
        }
        self.plugin.commit_layer_online = Mock()
        self.plugin.commit_layers_online.reset_mock()
        with patch(
            "geoflow_connector.services.depth.DepthService.calculate_survey_point",
            return_value={"ok": True, "depth": 2.5, "distance_m": 1.0},
        ):
            result = self.popup.start_selected()
        self.assertEqual(result["created"], 10)
        self.assertEqual(sum(layer.featureCount() for layer in self.layers[:3]), 10)
        self.assertEqual(depth_layer.featureCount(), 10)
        self.assertEqual(self.plugin.commit_layers_online.call_count, 1)
        self.plugin.commit_layer_online.assert_not_called()
        self.assertEqual(
            self.plugin.commit_layers_online.call_args.kwargs["trigger"],
            "survey_batch_create",
        )
        self.assertTrue(all(feature["pip_dep"] == 2.5
                            for feature in depth_layer.getFeatures()))

    def test_ten_depth_only_rows_create_with_pip_dep_and_no_followup_update(self):
        depth_layer = QgsVectorLayer(
            "Point?crs=EPSG:4326&field=id:string&field=FTR_CDE:string"
            "&field=pip_dep:double&field=project_id:string&field=worker_id:string"
            "&field=date:date&field=survey_no:string&field=survey_id:string"
            "&field=survey_source_id:string",
            "depth-only", "memory",
        )
        depth_layer.setCustomProperty("geoflow/standard_name", "WTL_PIPE_PS")
        depth_layer.setCustomProperty("geoflow/physical_name", "wtl_pipe_ps")
        self.layers.append(depth_layer)
        QgsProject.instance().addMapLayer(depth_layer)
        points = [{
            **self.points[0],
            "id": f'71000000-0000-4000-8000-{index + 1:012d}',
            "source_row_id": f'T{index + 1}', "raw_code": "T",
            "code": "T", "raw_z": 20.0 + index,
            "longitude": 127.0 + index * .001,
        } for index in range(10)]
        identity = facility_identity("WTL_PIPE_PS", "상수관로심도")
        self.popup._saved_mappings = lambda: {"T": {
            "facility_id": identity, "facility_label": "상수관로심도",
            "layer": "WTL_PIPE_PS",
        }}
        self.popup._mapping_options = lambda: [
            ("SA900", "상수관로심도", "WTL_PIPE_PS")
        ]
        self.popup._storage_codes = lambda: {identity: {
            "facility_id": identity, "facility_label": "상수관로심도",
            "standard_name": "WTL_PIPE_PS", "storage_field": "ftr_cde",
            "storage_code": "SA900", "code_label": "상수관로심도",
        }}
        self.popup._depth_create_targets = lambda: set()
        self.popup.point_rows = points
        self.popup.render_features()
        self.plugin.commit_layers_online.reset_mock()
        self.plugin.commit_layer_online = Mock()
        with patch(
            "geoflow_connector.services.depth.DepthService.calculate_survey_point",
            return_value={"ok": True, "depth": 1.565, "distance_m": 1.0},
        ):
            result = self.popup.start_selected()
        self.assertEqual(result["created"], 10)
        self.assertEqual(depth_layer.featureCount(), 10)
        self.assertEqual(self.plugin.commit_layers_online.call_count, 1)
        self.plugin.commit_layer_online.assert_not_called()
        self.assertTrue(all(feature["FTR_CDE"] == "SA900"
                            and feature["pip_dep"] == 1.565
                            for feature in depth_layer.getFeatures()))

    def test_depth_create_setting_persists_by_project(self):
        settings, _mapping = self.popup._settings()
        key = depth_create_key(
            self.plugin.active_client.base_url,
            self.plugin.integration_state()["project_id"],
        )
        expected = {("A", "A1"), ("B", "B2")}
        write_depth_create_targets(settings, key, expected)
        reloaded = QSettings(settings.fileName(), QSettings.Format.IniFormat)
        self.assertEqual(read_depth_create_targets(reloaded, key), expected)

    def test_pipe_sa900_storage_setting_persists_by_project(self):
        settings, _mapping = self.popup._settings()
        key = storage_code_key(
            self.plugin.active_client.base_url,
            self.plugin.integration_state()["project_id"],
        )
        identity = facility_identity("WTL_PIPE_PS", "상수관로시설")
        write_storage_codes(settings, key, {identity: {
            "facility_id": identity, "facility_label": "상수관로시설",
            "standard_name": "WTL_PIPE_PS", "storage_field": "ftr_cde",
            "storage_code": "SA900", "code_label": "상수관로시설",
        }})
        reloaded = QSettings(settings.fileName(), QSettings.Format.IniFormat)
        self.assertEqual(read_storage_codes(reloaded, key)[identity]["storage_code"],
                         "SA900")

    def test_depth_calculation_failure_creates_null_not_zero(self):
        depth_layer = QgsVectorLayer(
            "Point?crs=EPSG:4326&field=id:string&field=FTR_CDE:string"
            "&field=pip_dep:double&field=project_id:string&field=worker_id:string"
            "&field=date:date&field=survey_no:string&field=survey_id:string"
            "&field=survey_source_id:string",
            "depth-null", "memory",
        )
        depth_layer.setCustomProperty("geoflow/standard_name", "WTL_PIPE_PS")
        depth_layer.setCustomProperty("geoflow/physical_name", "wtl_pipe_ps")
        self.layers.append(depth_layer)
        QgsProject.instance().addMapLayer(depth_layer)
        self.enable_exposed_depth_mode()
        for row in range(1, self.popup.featureTable.rowCount()):
            self.popup.featureTable.item(row, 0).setCheckState(
                Qt.CheckState.Unchecked
            )
        self.popup._depth_create_targets = lambda: {("A", "A1")}
        self.plugin.commit_layers_online = Mock(side_effect=lambda layers, **_kwargs: {
            "ok": all(layer.commitChanges(False) for layer in layers),
        })
        with patch(
            "geoflow_connector.services.depth.DepthService.calculate_survey_point",
            return_value={"ok": False, "reason": "no_nearby_h"},
        ):
            result = self.popup.start_selected()
        self.assertEqual(result["created"], 1)
        depth = next(depth_layer.getFeatures())
        self.assertTrue(QgsVariantUtils.isNull(depth["pip_dep"]))

    def test_j_valve_uses_central_storage_code_and_depth_is_atomic(self):
        valve = self.layers[0]
        valve.setCustomProperty("geoflow/standard_name", "WTL_VALV_PS")
        point = {
            **self.points[0], "raw_code": "je", "source_row_id": "J001",
            "raw_z": 22.585, "survey_no": "261017-035",
            "raw_data": {"survey_work_code": "L3"},
        }
        self.points = [point]
        self.popup.point_rows = [point]
        self.popup._saved_mappings = lambda: {
            "J": {
                "facility_id": facility_identity("WTL_VALV_PS", "제수변"),
                "facility_label": "제수변", "layer": "WTL_VALV_PS",
            }
        }
        self.popup._mapping_options = lambda: [
            ("SA100", "제수변", "WTL_VALV_PS"),
            ("SA200", "공기변", "WTL_VALV_PS"),
            ("SA900", "상수관로심도", "WTL_PIPE_PS"),
        ]
        self.popup._storage_codes = lambda: {
            facility_identity("WTL_VALV_PS", "제수변"): {
                "facility_label": "제수변", "standard_name": "WTL_VALV_PS",
                "storage_field": "ftr_cde", "storage_code": "SA100",
                "code_label": "제수변",
            }
        }
        self.popup._depth_create_targets = lambda: {("WTL_VALV_PS", "SA100")}
        depth_layer = QgsVectorLayer(
            "Point?crs=EPSG:4326&field=id:string&field=FTR_CDE:string"
            "&field=pip_dep:double&field=project_id:string&field=worker_id:string"
            "&field=date:date&field=survey_no:string&field=survey_id:string"
            "&field=survey_source_id:string",
            "depth-j", "memory",
        )
        depth_layer.setCustomProperty("geoflow/standard_name", "WTL_PIPE_PS")
        depth_layer.setCustomProperty("geoflow/physical_name", "wtl_pipe_ps")
        self.layers.append(depth_layer)
        QgsProject.instance().addMapLayer(depth_layer)
        self.enable_exposed_depth_mode([point])
        self.popup.render_features()
        atomic_payload = []

        def atomic_commit(layers, **kwargs):
            atomic_payload.append({
                str(layer.customProperty("geoflow/standard_name")): [
                    str(feature["FTR_CDE"]) for feature in layer.getFeatures()
                ] for layer in layers
            })
            return {
                "ok": all(layer.commitChanges(False) for layer in layers),
                "provider_commit_called": True,
            }

        self.plugin.commit_layers_online = Mock(side_effect=atomic_commit)
        with patch(
            "geoflow_connector.services.depth.DepthService.calculate_survey_point",
            return_value={"ok": True, "depth": 1.565, "distance_m": 1.0},
        ):
            result = self.popup.start_selected()
        self.assertEqual(result["created"], 1)
        self.assertEqual(self.plugin.commit_layers_online.call_count, 1)
        self.assertEqual(atomic_payload, [{
            "WTL_VALV_PS": ["SA100"], "WTL_PIPE_PS": ["SA900"],
        }])
        self.assertEqual(next(valve.getFeatures())["FTR_CDE"], "SA100")
        depth = next(depth_layer.getFeatures())
        self.assertEqual(depth["FTR_CDE"], "SA900")
        self.assertEqual(depth["pip_dep"], 1.565)
        self.assertEqual(depth["survey_no"], "261017-035")

    def test_j_valve_facility_only_creates_no_depth(self):
        valve = self.layers[0]
        valve.setCustomProperty("geoflow/standard_name", "WTL_VALV_PS")
        point = {
            **self.points[0], "raw_code": "je", "source_row_id": "J-ONLY",
            "raw_z": 22.585, "survey_no": "261017-036",
            "raw_data": {"survey_work_code": "L3"},
        }
        self.popup.point_rows = [point]
        identity = facility_identity("WTL_VALV_PS", "제수변")
        self.popup._saved_mappings = lambda: {"J": {
            "facility_id": identity, "facility_label": "제수변",
            "layer": "WTL_VALV_PS",
        }}
        self.popup._mapping_options = lambda: [
            ("SA100", "제수변", "WTL_VALV_PS"),
            ("SA900", "상수관로심도", "WTL_PIPE_PS"),
        ]
        self.popup._storage_codes = lambda: {identity: {
            "facility_id": identity, "facility_label": "제수변",
            "standard_name": "WTL_VALV_PS", "storage_field": "ftr_cde",
            "storage_code": "SA100", "code_label": "제수변",
        }}
        depth_layer = QgsVectorLayer(
            "Point?crs=EPSG:4326&field=id:string&field=FTR_CDE:string"
            "&field=pip_dep:double&field=survey_no:string",
            "depth-j-only", "memory",
        )
        depth_layer.setCustomProperty("geoflow/standard_name", "WTL_PIPE_PS")
        depth_layer.setCustomProperty("geoflow/physical_name", "wtl_pipe_ps")
        self.layers.append(depth_layer)
        QgsProject.instance().addMapLayer(depth_layer)
        self.popup.render_features()
        result = self.popup.start_selected()
        self.assertEqual(result["created"], 1)
        self.assertEqual(valve.featureCount(), 1)
        self.assertEqual(next(valve.getFeatures())["FTR_CDE"], "SA100")
        self.assertEqual(depth_layer.featureCount(), 0)

    def test_work_code_does_not_override_facility_depth_policy(self):
        self.points[0]["raw_data"] = {"survey_work_code": "L3"}
        self.points[1]["raw_data"] = {"survey_work_code": "GENERAL"}
        self.popup.creationModeCombo.setCurrentIndex(
            self.popup.creationModeCombo.findData(
                self.popup.CREATE_FACILITY_WITH_DEPTH
            )
        )
        self.popup.render_features()
        for row in range(2, self.popup.featureTable.rowCount()):
            self.popup.featureTable.item(row, 0).setCheckState(
                Qt.CheckState.Unchecked
            )
        self.plugin.commit_layers_online.reset_mock()
        self.popup._depth_create_targets = lambda: set()
        result = self.popup.start_selected()
        self.assertEqual(result["created"], 2)
        self.assertEqual(self.plugin.commit_layers_online.call_count, 1)


if __name__ == '__main__':
    unittest.main()
