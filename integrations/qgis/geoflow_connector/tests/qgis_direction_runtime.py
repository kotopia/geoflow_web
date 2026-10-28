"""Isolated real QGIS tests. No login, operational project or network access."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from qgis.core import (QgsApplication,QgsProject,QgsVectorLayer,QgsFeature,QgsGeometry,
    QgsPointXY,QgsRectangle,QgsCoordinateReferenceSystem,QgsCoordinateTransform,QgsRenderContext)
from qgis.PyQt.QtCore import Qt,QPoint,QEvent,QTimer
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QMainWindow,QToolButton,QMenu,QLabel
from qgis.gui import QgsMapCanvas,QgsMapMouseEvent
from geoflow_connector.services.direction_math import *
from geoflow_connector.services.direction import DirectionService,validate_pending
from geoflow_connector.layers.identify import IdentifyGeometry
from geoflow_connector.ui.direction import RotationDialog,DirectionResults
APP=QgsApplication.instance() or QgsApplication([],False)
APP.initQgis()


def config(method='connected'):
    return validate_config(dict(reference_layer_ids=[str(uuid4())],method=method,distance=1,
        unit='m',offset=0,allow_reverse=True,ambiguity='review',zero_axis='north',
        positive_direction='clockwise',symbol_offset=0,axis_tolerance=1,tie_tolerance=0.01))


class MathTests(unittest.TestCase):
    def test_endpoints_and_duplicates(self):
        c=config(); line=[('pipe', [[(0,0),(0,0),(10,0),(10,10)]])]
        self.assertEqual(calculate((0,0),line,c)['angle'],90)
        self.assertEqual(calculate((10,10),line,c)['angle'],180)
        self.assertEqual(calculate((10,0),line,c)['status'],'ambiguous')
        self.assertEqual(calculate((5,0),line,c)['status'],'no_reference')
    def test_straight_junction_multipart_and_zero(self):
        c=config(); line=[('p', [[(0,0),(5,0),(10,0)],[(20,20),(20,20)]])]
        self.assertEqual(calculate((5,0),line,c)['angle'],90)
        self.assertEqual(calculate((0,0),line+[('q',[[(0,0),(0,10)]])],c)['status'],'ambiguous')
    def test_nearest_local_segment_and_ties(self):
        c=config('nearest'); c['offset']=90
        result=calculate((10.5,5),[('road',[[(0,0),(10,0),(10,10)]])],c)
        self.assertEqual(result['angle'],90)
        self.assertEqual(calculate((0,0),[('a',[[(-2,1),(2,1)]]),('b',[[(-2,-1),(2,-1)]])],c)['status'],'ambiguous')
    def test_conversions_and_validation(self):
        c=config(); c.update(zero_axis='east',positive_direction='counterclockwise',offset=90)
        for angle in (0,90,180,359.9): self.assertAlmostEqual(to_bearing(to_storage(angle,c),c),angle)
        self.assertEqual(normalize(-1),359)
        for key,value in [('distance',float('nan')),('unit','degrees'),('allow_reverse','yes')]:
            bad=dict(c); bad[key]=value
            with self.assertRaises(ValueError): validate_config(bad)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.window=QMainWindow(); self.canvas=QgsMapCanvas()
        self.canvas.resize(500,500)
        self.layer=self.make_layer('Point','assets')
        self.ref=self.make_layer('LineString','references')
        self.cfg=config(); self.cfg['reference_layer_ids']=[self.ref.customProperty('geoflow/definition_layer_id')]
        self.field=dict(id=str(uuid4()),layer_id=self.layer.customProperty('geoflow/definition_layer_id'),
                        storage={'kind':'column','key':'ang_dir'},direction=self.cfg)
        self.plugin=SimpleNamespace(_managed_layers=lambda:[self.layer,self.ref],
            _definition_service=SimpleNamespace(definition={'fields':[self.field]}),
            integration_state=lambda:{'can_write':True},mapCanvas=self.canvas,
            iface=SimpleNamespace(mainWindow=lambda:self.window,currentLayerChanged=self.canvas.currentLayerChanged))
        self.service=DirectionService(self.plugin)
        self.feature=self.add(self.layer,'Point (0 0)',0)
        self.line=self.add(self.ref,'LineString (0 0, 10 0)',0)
        self.canvas.setDestinationCrs(self.layer.crs());self.canvas.setLayers([self.layer,self.ref])
        self.canvas.setExtent(QgsRectangle(-5,-5,15,15)); self.canvas.show();APP.processEvents()
    def make_layer(self,kind,name):
        layer=QgsVectorLayer(kind+'?crs=EPSG:3857&field=id:string&field=ang_dir:double&field=note:string',name,'memory')
        layer.setCustomProperty('geoflow/definition_layer_id',str(uuid4()))
        QgsProject.instance().addMapLayer(layer);return layer
    def add(self,layer,wkt,angle):
        f=QgsFeature(layer.fields());f['id']=str(uuid4());f['ang_dir']=angle;f['note']='baseline'
        f.setGeometry(QgsGeometry.fromWkt(wkt));layer.dataProvider().addFeature(f);layer.updateExtents();return f
    def tearDown(self):
        self.canvas.setLayers([]);self.canvas.close();QgsProject.instance().removeAllMapLayers()
    def test_apply_undo_and_stale(self):
        result=self.service.inspect(self.layer,self.feature)
        self.assertEqual(result['status'],'ok',result)
        self.service.apply(self.layer,[result])
        self.assertEqual(self.layer.getFeature(self.feature.id())['ang_dir'],90)
        validate_pending(self.plugin,self.layer)
        self.ref.startEditing();self.ref.changeGeometry(self.line.id(),QgsGeometry.fromWkt('LineString (0 0,0 10)'))
        with self.assertRaises(ValueError):validate_pending(self.plugin,self.layer)
        self.layer.undoStack().undo();self.assertEqual(self.layer.getFeature(self.feature.id())['ang_dir'],0)
    def test_mixed_crs(self):
        tx=QgsCoordinateTransform(self.ref.crs(),QgsCoordinateReferenceSystem('EPSG:4326'),QgsProject.instance())
        geom=QgsGeometry(self.line.geometry());geom.transform(tx)
        self.ref.dataProvider().changeGeometryValues({self.line.id():geom});self.ref.setCrs(QgsCoordinateReferenceSystem('EPSG:4326'))
        result=self.service.inspect(self.layer,self.feature)
        self.assertEqual(result['status'],'ok',result);self.assertAlmostEqual(result['angle'],90,places=5)
    def test_batch_failure_preserves_values_and_stale_target(self):
        other=self.add(self.layer,'Point (100 100)',73)
        self.assertEqual(self.service.inspect(self.layer,other)['status'],'no_reference')
        result=self.service.inspect(self.layer,self.feature)
        self.layer.startEditing();self.layer.changeGeometry(self.feature.id(),QgsGeometry.fromWkt('Point (2 2)'))
        with self.assertRaises(ValueError):self.service.apply(self.layer,[result])
        self.assertEqual(self.layer.getFeature(other.id())['ang_dir'],73)
    def test_selection_modifiers_and_area(self):
        other=self.add(self.layer,'Point (2 2)',0)
        tool=IdentifyGeometry(self.canvas,layer_provider=lambda:{self.layer.id():self.layer},active_layer=lambda:self.layer,notify=print)
        tool.select_ids(self.layer,[self.feature.id()],Qt.KeyboardModifier.NoModifier)
        tool.select_ids(self.layer,[other.id()],Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(self.layer.selectedFeatureCount(),2)
        tool.select_ids(self.layer,[other.id()],Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.layer.selectedFeatureIds(),[self.feature.id()])
        tool.mode='area';self.canvas.setMapTool(tool)
        transform=self.canvas.getCoordinateTransform()
        a=transform.transform(QgsPointXY(-1,-1));b=transform.transform(QgsPointXY(3,3))
        press=QgsMapMouseEvent(self.canvas,QEvent.Type.MouseButtonPress,QPoint(round(a.x()),round(a.y())),Qt.MouseButton.LeftButton,Qt.MouseButton.LeftButton)
        release=QgsMapMouseEvent(self.canvas,QEvent.Type.MouseButtonRelease,QPoint(round(b.x()),round(b.y())),Qt.MouseButton.LeftButton,Qt.MouseButton.NoButton)
        tool.canvasPressEvent(press);tool.canvasReleaseEvent(release)
        self.assertEqual(self.layer.selectedFeatureCount(),2)
        tool.canvasPressEvent(press);tool.cancel_drag();self.assertIsNone(tool._start)
        self.canvas.unsetMapTool(tool);tool.dispose()
    def test_actual_dynamic_form_draft_and_undo(self):
        from geoflow_connector.forms.dynamic.form import DynamicForm
        from geoflow_connector.forms.dynamic.binding import DynamicFormBinding
        fields=[]
        for field_id,key,kind in ((self.field['id'],'ang_dir','decimal'),('note','note','text')):
            fields.append(dict(id=field_id,label=key,widget_type=kind,semantic_data_type=kind,
                visible=True,required=False,readonly=False,display_order=1,layout={},reference_codes=[],
                storage={'kind':'column','key':key}))
        form=DynamicForm({'fields':fields,'rules':[]},fields)
        page=SimpleNamespace(form=form,note=QLabel(),dirty=False,feature_id=self.feature.id(),update_dirty=lambda:None)
        page.binding=DynamicFormBinding(page,self.layer,form,True)
        page.binding.load(self.feature,force=True)
        form.load_values({self.field['id']:20,'note':'unsaved note'})
        result=self.service.inspect(self.layer,self.feature)
        self.service.apply(self.layer,[result],page)
        self.assertEqual(float(form.values()[self.field['id']]),90)
        self.assertEqual(form.values()['note'],'unsaved note')
        self.layer.undoStack().undo()
        self.assertEqual(float(form.values()[self.field['id']]),20)
        self.assertEqual(form.values()['note'],'unsaved note')
        self.layer.undoStack().redo()
        self.assertEqual(float(form.values()[self.field['id']]),90)
        page.binding.feature_id=999
        form.load_values({self.field['id']:55,'note':'other feature'})
        self.layer.undoStack().undo()
        self.assertEqual(float(form.values()[self.field['id']]),55)
        page.binding.dispose()
    def test_noop_does_not_start_editing(self):
        result=self.service.inspect(self.layer,self.feature);result['angle']=0
        self.service.apply(self.layer,[result]);self.assertFalse(self.layer.isEditable())

    def test_area_in_different_canvas_crs_and_escape(self):
        self.add(self.layer,'Point (2 2)',0)
        self.canvas.setDestinationCrs(QgsCoordinateReferenceSystem('EPSG:4326'))
        self.canvas.setExtent(QgsRectangle(-0.0001,-0.0001,0.0001,0.0001));APP.processEvents()
        tool=IdentifyGeometry(self.canvas,layer_provider=lambda:{self.layer.id():self.layer},active_layer=lambda:self.layer)
        tool.mode='area';self.canvas.setMapTool(tool)
        def event(kind,point,buttons):
            return QgsMapMouseEvent(self.canvas,kind,point,Qt.MouseButton.LeftButton,buttons)
        tool.canvasPressEvent(event(QEvent.Type.MouseButtonPress,QPoint(50,50),Qt.MouseButton.LeftButton))
        tool.canvasReleaseEvent(event(QEvent.Type.MouseButtonRelease,QPoint(450,450),Qt.MouseButton.NoButton))
        self.assertEqual(self.layer.selectedFeatureCount(),2)
        tool.canvasPressEvent(event(QEvent.Type.MouseButtonPress,QPoint(50,50),Qt.MouseButton.LeftButton))
        QTest.keyClick(self.canvas,Qt.Key.Key_Escape)
        self.assertIsNone(tool._start)
        self.canvas.unsetMapTool(tool);tool.dispose()
    def test_delayed_popup_does_not_trigger_short_click(self):
        button=QToolButton();menu=QMenu(button);menu.addAction('single');menu.addAction('area')
        button.setMenu(menu);button.setPopupMode(QToolButton.ToolButtonPopupMode.DelayedPopup)
        clicks=[];shown=[];button.clicked.connect(lambda:clicks.append(True));menu.aboutToShow.connect(lambda:shown.append(True))
        menu.aboutToShow.connect(lambda:QTimer.singleShot(20,menu.close))
        button.show();APP.processEvents()
        QTest.mouseClick(button,Qt.MouseButton.LeftButton);self.assertEqual(len(clicks),1)
        QTest.mousePress(button,Qt.MouseButton.LeftButton);QTest.qWait(1000);QTest.mouseRelease(button,Qt.MouseButton.LeftButton)
        self.assertTrue(shown);self.assertEqual(len(clicks),1);button.close()

    def test_preview_sync_cancel_and_apply(self):
        values={self.field['id']:0,'other':'draft'}
        form=SimpleNamespace(values=lambda:dict(values),load_values=lambda data:values.update(data))
        page=SimpleNamespace(feature_id=self.feature.id(),form=form,binding=SimpleNamespace(has_actual_changes=lambda:None),update_dirty=lambda:None)
        controller=SimpleNamespace(plugin=self.plugin,direction=self.service)
        self.layer.selectByIds([self.feature.id()])
        dialog=RotationDialog(controller,self.layer,page);dialog.show();APP.processEvents()
        dialog.spin.setFocus();dialog.spin.selectAll();QTest.keyClicks(dialog.spin,'45')
        self.assertEqual(dialog.overlay.getFeature(dialog.preview_feature.id())['ang_dir'],45)
        dialog.spin.setValue(90);self.assertEqual(dialog.dial.value(),9000)
        self.assertEqual(dialog.overlay.getFeature(dialog.preview_feature.id())['ang_dir'],90)
        self.assertFalse(self.layer.isEditable());dialog.reject()
        self.assertEqual(values[self.field['id']],0);self.assertEqual(values['other'],'draft')
        self.assertNotIn(dialog.overlay,self.canvas.layers())
        dialog=RotationDialog(controller,self.layer,page);dialog.dial.setValue(18000);dialog.apply()
        self.assertEqual(self.layer.getFeature(self.feature.id())['ang_dir'],180)
        self.assertEqual(values['other'],'draft')
        self.layer.undoStack().undo();self.assertEqual(self.layer.getFeature(self.feature.id())['ang_dir'],0)

if __name__=='__main__':unittest.main(verbosity=2)
