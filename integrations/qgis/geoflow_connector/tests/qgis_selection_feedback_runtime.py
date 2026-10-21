"""Real QGIS identify, ellipsoidal boundaries, and timed Dynamic Form feedback."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from qgis_survey_popup_runtime import APP, PROJECT
from qgis.PyQt.QtCore import QSettings, Qt, QPoint, QEvent
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtGui import QFont, QFontDatabase
from qgis.core import (Qgis, QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY,
                       QgsProject, QgsDistanceArea, QgsCoordinateReferenceSystem, QgsRectangle)
from qgis.gui import QgsMapCanvas, QgsMapMouseEvent
from geoflow_connector.layers.identify import IdentifyGeometry
from geoflow_connector.services.settings import GeoFlowSettingsService
from geoflow_connector.services.nearby import NearbySearchService
from geoflow_connector.services.depth import DepthService
from geoflow_connector.services.survey_spatial import nearby_targets, points_overlap
from geoflow_connector.forms.dynamic.form import DynamicForm
from geoflow_connector.ui.inline_message import InlineMessage, depth_feedback, show_depth_feedback
from geoflow_connector.ui.edit_tools import EditToolsController

QFontDatabase.addApplicationFont('C:/Windows/Fonts/malgun.ttf')
QFontDatabase.addApplicationFont('C:/Windows/Fonts/seguisym.ttf')
APP.setFont(QFont('Malgun Gothic', 9))

class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.layers = []
        self.survey = self.layer('SURVEY')
        self.depth = self.layer('WTL_PIPE_PS')
        self.valve = self.layer('WTL_VALV_PS')
        self.logs = []
        self.plugin = SimpleNamespace(active_context={'project_id': PROJECT},
                                      _managed_layers=lambda: self.layers, log=self.logs.append)
        self.settings = GeoFlowSettingsService(self.plugin, QSettings(
            str(Path(self.temp.name)/'settings.ini'), QSettings.Format.IniFormat))
        self.service = DepthService(self.plugin, settings=self.settings)
        self.origin = QgsPointXY(127, 36)
        self.distance = QgsDistanceArea()
        self.distance.setSourceCrs(QgsCoordinateReferenceSystem('EPSG:4326'), QgsProject.instance().transformContext())
        self.distance.setEllipsoid('WGS84')

    def layer(self, name):
        layer = QgsVectorLayer('Point?crs=EPSG:4326&field=id:string&field=code:string&field=raw_z:double&field=pip_dep:double&field=survey_no:string&field=project_id:string&field=ftr_cde:string', name, 'memory')
        layer.setCustomProperty('geoflow/standard_name', name)
        QgsProject.instance().addMapLayer(layer)
        self.layers.append(layer)
        return layer

    def point(self, metres):
        return self.distance.computeSpheroidProject(self.origin, metres, 1.5707963267948966)

    def add(self, layer, metres=0, **attrs):
        f = QgsFeature(layer.fields())
        f['id'] = str(layer.featureCount()+1)
        f['project_id'] = PROJECT
        for k,v in attrs.items(): f[k] = v
        f.setGeometry(QgsGeometry.fromPointXY(self.point(metres)))
        layer.dataProvider().addFeature(f)
        return f

    def tearDown(self):
        for layer in self.layers: QgsProject.instance().removeMapLayer(layer.id())
        self.temp.cleanup()

    def test_active_only_real_hit_test(self):
        for layer in self.layers: self.add(layer)
        canvas = QgsMapCanvas()
        canvas.resize(400,400)
        canvas.setDestinationCrs(QgsCoordinateReferenceSystem('EPSG:4326'))
        canvas.setLayers([self.depth, self.valve, self.survey])
        canvas.setExtent(QgsRectangle(126.9999,35.9999,127.0001,36.0001))
        canvas.show(); APP.processEvents()
        active = [self.survey]
        seen, missing, notices = [], [], []
        tool = IdentifyGeometry(canvas, layer_provider=lambda: {l.id():l for l in self.layers},
                                active_layer=lambda: active[0], notify=notices.append)
        tool.geomIdentified.connect(lambda layer,feature,event: seen.append(layer.id()))
        tool.noFeatureIdentified.connect(lambda: missing.append(True))
        xy = canvas.getCoordinateTransform().transform(127,36)
        event = QgsMapMouseEvent(canvas,QEvent.Type.MouseButtonRelease,QPoint(round(xy.x()),round(xy.y())),Qt.MouseButton.LeftButton)
        for layer in (self.survey,self.valve,self.depth,self.survey):
            active[0] = layer; tool.canvasReleaseEvent(event)
            self.assertEqual(seen[-1],layer.id())
        for invalid in (None, QgsVectorLayer('Point?crs=EPSG:4326','external','memory')):
            active[0] = invalid; tool.canvasReleaseEvent(event)
        self.assertEqual(len(seen),4); self.assertEqual(missing,[]); self.assertEqual(len(notices),2)
        # Active layer is deliberately absent from the visible-layer list.
        canvas.setLayers([self.depth,self.valve]); active[0]=self.survey
        tool.canvasReleaseEvent(event); self.assertEqual(seen[-1],self.survey.id())
        self.assertEqual(len(seen),5)
        self.survey.dataProvider().truncate()
        tool.canvasReleaseEvent(event)
        self.assertEqual(len(seen),5); self.assertEqual(len(missing),1)
        canvas.close()

    def test_source_and_height_boundaries(self):
        target = self.add(self.depth)
        for metres, expected in ((1.99,True),(2.0,True),(2.01,False)):
            with self.subTest(metres=metres):
                self.survey.dataProvider().truncate()
                source = self.add(self.survey,metres,code='T',raw_z=10)
                self.add(self.survey,metres,code='H',raw_z=12)
                self.assertEqual(self.service.calculate_feature(target)['ok'],expected)
                self.survey.dataProvider().truncate()
                source = self.add(self.survey,0,code='T',raw_z=10)
                self.add(self.survey,metres,code='H',raw_z=12)
                direct = self.service.calculate_feature(target)
                batch = DepthService(self.plugin,settings=self.settings).prepare_batch().calculate_survey_point({'id':str(source['id'])})
                self.assertEqual(direct['ok'],expected); self.assertEqual(batch['ok'],expected)
                if not expected: self.assertEqual(direct['reason'],'no_height_candidate')

    def test_creation_and_duplicate_boundaries(self):
        origin = {'longitude':127,'latitude':36}
        with patch('geoflow_connector.services.survey_spatial.GeoFlowSettingsService',return_value=self.settings):
            for metres, expected in ((1.99,True),(2,True),(2.01,False)):
                self.valve.dataProvider().truncate()
                self.add(self.valve,metres,ftr_cde='VALVE')
                self.assertEqual(bool(nearby_targets(self.plugin,origin,self.valve,'VALVE')),expected)
                p=self.point(metres)
                self.assertEqual(points_overlap(self.plugin,origin,{'longitude':p.x(),'latitude':p.y()}),expected)

    def test_number_still_obeys_radius_and_overrides(self):
        target = self.add(self.depth,survey_no='S')
        self.add(self.survey,3,code='T',raw_z=10,survey_no='S')
        self.add(self.survey,3,code='H',raw_z=12)
        self.assertEqual(self.service.calculate_feature(target)['reason'],'no_nearby_survey')
        self.settings.save_nearby(default_radius_m=4,depth_radius_m=4,manhole_radius_m=4,nearest_first=True)
        self.assertEqual(self.service.calculate_feature(target)['depth'],2)

    def test_invalid_z_service_and_radius_feedback(self):
        target = self.add(self.depth)
        self.add(self.survey,0,code='T',raw_z=float('nan'))
        result = self.service.calculate_feature(target)
        self.assertFalse(result['ok'])
        self.assertIn(result['reason'], ('invalid_source_z', 'source_z_missing'))
        self.assertIn('Z값', depth_feedback(result,2)[0])
        self.assertIn('반경 5.0m', depth_feedback({'reason':'no_height_candidate'},5)[0])
        self.assertTrue(any('[DEPTH_SEARCH]' in line for line in self.logs))

    def test_real_form_action_and_feedback(self):
        target = self.add(self.depth)
        field={'id':'depth','label':'심도','field_name':'pip_dep','visible':True,'readonly':False,
               'widget_type':'number','storage':{'kind':'column','key':'pip_dep'}}
        form=DynamicForm({},[field],layer='WTL_PIPE_PS')
        page=SimpleNamespace(form=form,layer_id=self.depth.id(),feature_id=target.id(),
                             binding=SimpleNamespace(has_actual_changes=lambda:True))
        controller=SimpleNamespace(_layer_by_id=lambda _:self.depth,
            _current_form_feature=lambda *_:target,depth=self.service,refresh=lambda:None,_log=self.logs.append)
        form.resize(520,260)
        form.show()
        EditToolsController.calculate_current_depth(controller,page)
        self.assertIn('반경 2.0m',page.depth_message.text())
        self.assertIn('측량점이 없습니다',page.depth_message.text())
        source=self.add(self.survey,0,code='T',raw_z=10)
        EditToolsController.calculate_current_depth(controller,page)
        self.assertIn('표고 기준점(H)',page.depth_message.text())
        self.add(self.survey,1,code='H',raw_z=12)
        EditToolsController.calculate_current_depth(controller,page)
        self.assertEqual(float(form.values()['depth']),2)
        self.assertIn('2.000m',page.depth_message.text())
        self.assertTrue(page.depth_message.isVisible())
        APP.processEvents()
        form.grab().save(str(Path(__file__).resolve().parents[1]/"test_artifacts/depth-feedback-success.png"))
        message=page.depth_message
        QTest.qWait(1500)
        show_depth_feedback(page,{'ok':False,'reason':'invalid_source_z'},2)
        self.assertIs(message,page.depth_message)
        APP.processEvents()
        form.grab().save(str(Path(__file__).resolve().parents[1]/'test_artifacts/depth-feedback-error.png'))
        QTest.qWait(1500); self.assertTrue(message.isVisible())
        QTest.qWait(1500); self.assertFalse(message.isVisible())
        self.assertEqual(len(form.findChildren(InlineMessage)),1)
        self.assertIn('Z값',depth_feedback({'reason':'invalid_source_z'},2)[0])
        self.assertEqual(depth_feedback({'reason':'calculation_failed'},2)[1],'error')
        form.close()

if __name__=='__main__':
    print('QGIS_RUNTIME='+Qgis.QGIS_VERSION)
    unittest.main()
