"""Real QGIS spatial depth lookup, no relationships and no server requests."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from qgis_survey_popup_runtime import APP, PROJECT
from qgis.core import QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY, QgsProject, Qgis
from qgis.PyQt.QtCore import QSettings
from geoflow_connector.services.depth import DepthService
from geoflow_connector.services.settings import GeoFlowSettingsService


class SpatialDepthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.survey = QgsVectorLayer(
            'Point?crs=EPSG:4326&field=id:string&field=code:string&field=raw_z:double'
            '&field=survey_no:string&field=project_id:string&field=is_deleted:integer', 'survey', 'memory')
        self.target = QgsVectorLayer(
            'Point?crs=EPSG:4326&field=id:string&field=pip_dep:double&field=survey_no:string'
            '&field=project_id:string', 'depth', 'memory')
        for layer, standard in ((self.survey, 'SURVEY'), (self.target, 'WTL_PIPE_PS')):
            layer.setCustomProperty('geoflow/standard_name', standard)
            QgsProject.instance().addMapLayer(layer)
        self.plugin = SimpleNamespace(active_context={'project_id': PROJECT}, active_client=Mock(),
                                      _managed_layers=lambda: [self.survey, self.target])
        self.settings = GeoFlowSettingsService(self.plugin, QSettings(
            str(Path(self.temp.name) / 'settings.ini'), QSettings.Format.IniFormat))
        self.settings.save_nearby(default_radius_m=10, depth_radius_m=10,
                                  manhole_radius_m=5, nearest_first=True)
        self.service = DepthService(self.plugin, settings=self.settings)
        self.add(self.survey, 'source', 127, code='T', raw_z=10, survey_no='S1')
        self.add(self.survey, 'height', 127.00001, code='H', raw_z=12)
        self.feature = self.add(self.target, 'direct', 127.00002)

    def add(self, layer, identifier, longitude, **attributes):
        feature = QgsFeature(layer.fields())
        feature['id'] = identifier
        feature['project_id'] = attributes.pop('project_id', PROJECT)
        for name, val in attributes.items(): feature[name] = val
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(longitude, 36)))
        layer.dataProvider().addFeature(feature)
        return feature

    def tearDown(self):
        self.assertEqual(self.plugin.active_client.mock_calls, [])
        for layer in (self.survey, self.target): QgsProject.instance().removeMapLayer(layer.id())
        self.temp.cleanup()

    def test_direct_depth_uses_nearest_source_and_h_without_cache(self):
        result = self.service.calculate_feature(self.feature)
        self.assertTrue(result['ok'])
        self.assertEqual(result['source_id'], 'source')
        self.assertEqual(result['depth'], 2)
        restarted = DepthService(self.plugin, settings=self.settings)
        self.assertEqual(restarted.calculate_feature(self.feature)['depth'], 2)

    def test_management_number_precedes_nearest(self):
        self.add(self.survey, 'number-source', 127.00006, code='J', raw_z=9, survey_no='S2')
        self.feature['survey_no'] = 'S2'
        result = self.service.calculate_feature(self.feature)
        self.assertEqual(result['source_id'], 'number-source')
        self.assertEqual(result['depth'], 3)

    def test_unmatched_number_falls_back_to_spatial(self):
        self.feature['survey_no'] = 'missing'
        self.assertEqual(self.service.calculate_feature(self.feature)['source_id'], 'source')

    def test_other_project_deleted_and_road_are_excluded(self):
        self.add(self.survey, 'foreign', 127.00002, code='T', raw_z=1, project_id='other')
        self.add(self.survey, 'deleted', 127.00002, code='T', raw_z=1, is_deleted=1)
        self.add(self.survey, 'road', 127.00002, code='DO', raw_z=1)
        self.add(self.survey, 'foreign-height', 127, code='H', raw_z=100, project_id='other')
        self.assertEqual(self.service.calculate_feature(self.feature)['depth'], 2)
        result = self.service.prepare_batch().calculate_survey_point({'id': 'source'})
        self.assertEqual(result['depth'], 2)

    def test_project_radius_is_live_and_failure_is_spatial(self):
        self.settings.save_nearby(default_radius_m=10, depth_radius_m=.1,
                                  manhole_radius_m=5, nearest_first=True)
        self.assertEqual(self.service.calculate_feature(self.feature)['reason'], 'no_nearby_survey')

    def test_missing_source_z(self):
        self.add(self.survey, 'missing-z', 127.00002, code='T', survey_no='bad')
        self.feature['survey_no'] = 'bad'
        self.assertEqual(self.service.calculate_feature(self.feature)['reason'], 'source_z_missing')

    def test_invalid_source_z_returns_reason_instead_of_exception(self):
        result = self.service.prepare_batch().calculate_survey_point({
            'id': 'new-survey', 'code': 'T', 'raw_z': 'invalid',
            'longitude': 127, 'latitude': 36,
        })
        self.assertEqual(result['reason'], 'invalid_source_z')


if __name__ == '__main__':
    print('QGIS runtime: ' + Qgis.QGIS_VERSION)
    unittest.main()
