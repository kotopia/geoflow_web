import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
ARTIFACTS = ROOT / 'test_artifacts'
ARTIFACTS.mkdir(exist_ok=True)
import sys,tempfile,copy
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
sys.path.insert(0,str(Path.cwd().parent))
from qgis.core import *
from qgis.PyQt.QtCore import QSettings,Qt,QObject,pyqtSignal
from qgis.PyQt.QtWidgets import QMainWindow
from qgis.gui import QgsMapCanvas
app=QgsApplication([],False);app.initQgis()
tmp=tempfile.TemporaryDirectory();QSettings.setDefaultFormat(QSettings.Format.IniFormat);QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,tmp.name)
from geoflow_connector.services.direction import DirectionService
from geoflow_connector.services.direction_preferences import DirectionPreferences
from geoflow_connector.ui.settings_dialog import GeoFlowSettingsDialog
from geoflow_connector.ui.direction import RotationDialog,DirectionResults
from geoflow_connector.services.settings import SettingsValidationError
project=QgsProject.instance();window=QMainWindow();canvas=QgsMapCanvas();canvas.setDestinationCrs(QgsCoordinateReferenceSystem('EPSG:5186'));canvas.resize(500,500)
p=QgsVectorLayer('Point?crs=EPSG:5186&field=id:string&field=rotation:double&field=kind:string','시설','memory')
l=QgsVectorLayer('LineString?crs=EPSG:5186&field=id:string&field=bore:double','관로','memory')
pid,lid,aid,kid,did=[str(uuid4()) for _ in range(5)]
for layer,key in [(p,pid),(l,lid)]:layer.setCustomProperty('geoflow/definition_layer_id',key);project.addMapLayer(layer)
def add(layer,wkt,values):
 f=QgsFeature(layer.fields());f.setAttributes(values);f.setGeometry(QgsGeometry.fromWkt(wkt));return layer.dataProvider().addFeatures([f])[1][0]
f=add(p,'POINT(200000 600000)',[str(uuid4()),20,'REDUCER'])
big=add(l,'LINESTRING(199990 600000,200000 600000)',[str(uuid4()),300])
small=add(l,'LINESTRING(200000 600004,200000 600000)',[str(uuid4()),100])
fields=[dict(id=aid,layer_id=pid,label='방향',semantic_data_type='decimal',storage=dict(kind='column',key='rotation')),
 dict(id=kid,layer_id=pid,label='시설 구분',semantic_data_type='text',storage=dict(kind='column',key='kind')),
 dict(id=did,layer_id=lid,label='관경',semantic_data_type='decimal',storage=dict(kind='column',key='bore'),readonly=True)]
class Iface(QObject):
 currentLayerChanged=pyqtSignal(object)
 def mainWindow(self):return window
 def activeLayer(self):return p
 def setActiveLayer(self,layer):self.currentLayerChanged.emit(layer)
plugin=SimpleNamespace(active_context={'project_id':'diameter-test'},_definition_service=SimpleNamespace(definition={'fields':fields},client=SimpleNamespace(base_url='https://example.invalid')),
 _managed_layers=lambda:[p,l],iface=Iface(),mapCanvas=canvas,integration_state=lambda:dict(ready=True,can_write=True),work=SimpleNamespace(pages={},adapter=SimpleNamespace(selected_layer_id=lambda:p.id())),edit_tools=None)
prefs=DirectionPreferences(plugin);svc=DirectionService(plugin)
from qgis.PyQt.QtGui import QFontDatabase
for font in ('malgun.ttf','segoeui.ttf','arial.ttf','consola.ttf'):
 QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+font)
ui=GeoFlowSettingsDialog(plugin);ui.directionUseCheck.setChecked(True);ui.directionFieldCombo.setCurrentIndex(ui.directionFieldCombo.findData(aid));ui.directionReferenceList.item(0).setCheckState(Qt.CheckState.Checked)
ui.directionRadiusSpin.setValue(.1);ui.directionOnLineCheck.setChecked(True);assert not ui.directionRadiusSpin.isEnabled()
ui.directionDiameterCheck.setChecked(True);ui.directionFilterCombo.setCurrentIndex(ui.directionFilterCombo.findData(kid));ui.directionFilterValue.setText('REDUCER')
combo=ui.directionDiameterTable.cellWidget(0,1);combo.setCurrentIndex(combo.findData(did))
from qgis.PyQt.QtGui import QFontDatabase,QFont
QFontDatabase.addApplicationFont('C:/Windows/Fonts/malgun.ttf');app.setFont(QFont('Malgun Gothic',9))
ui.resize(760,850);ui.settingsTabs.setCurrentWidget(ui.directionTab);ui.show();app.processEvents()
ui.grab().save(str(ARTIFACTS / 'geoflow-diameter-settings.png'))
doc=ui.direction_editor.document();prefs.save(doc)
assert doc['facilities'][pid]['diameter_rule']['reference_fields']=={lid:did}
ui.reject();ui=GeoFlowSettingsDialog(plugin);assert ui.directionOnLineCheck.isChecked() and ui.directionDiameterCheck.isChecked();assert ui.directionFilterValue.text()=='REDUCER';ui.reject()
r=svc.inspect(p,f);assert r['status']=='ok' and r['angle']==90,r
# Pipe vertex order does not affect the reducer's small-bore heading.
l.dataProvider().changeGeometryValues({small.id():QgsGeometry.fromWkt('LINESTRING(200000 600000,200000 600004)')})
assert svc.inspect(p,f)['angle']==90
other=QgsFeature(f);other['kind']='VALVE';assert svc.inspect(p,other)['angle']==0
# Exact-line check rejects offset features, tolerance mode accepts without moving them.
offset=QgsFeature(f);offset.setGeometry(QgsGeometry.fromWkt('POINT(200000.0005 600000)'))
assert svc.inspect(p,offset)['status']=='no_reference'
doc['facilities'][pid]['require_on_line']=False;prefs.save(doc)
assert svc.inspect(p,offset)['status']=='ok'
assert offset.geometry().asPoint().x()==200000.0005
# Attribute changes invalidate previously calculated evidence.
r=svc.inspect(p,f);l.dataProvider().changeAttributeValues({small.id():{1:150}})
try:svc.verify(p,r);raise AssertionError('stale diameter accepted')
except ValueError:pass
l.dataProvider().changeAttributeValues({small.id():{1:300}})
r=svc.inspect(p,f);assert r['status']=='ambiguous' and r['review_only']
dialog=DirectionResults(SimpleNamespace(plugin=plugin,direction=svc),p,[f]);assert len(dialog.rows)==1;assert not dialog.table.item(0,0).flags() & Qt.ItemFlag.ItemIsUserCheckable;dialog.reject()
l.dataProvider().changeAttributeValues({small.id():{1:None}});assert svc.inspect(p,f)['review_only']
l.dataProvider().changeAttributeValues({small.id():{1:100}})
# Two simultaneously matching rule symbols, including a source FID filter.
root=QgsRuleBasedRenderer.Rule(None)
for name,angle in [('triangle',0),('arrow',30)]:
 sym=QgsMarkerSymbol.createSimple({'name':name,'angle':str(angle),'size':'3'});sym.setDataDefinedAngle(QgsProperty.fromField('rotation'))
 rule=QgsRuleBasedRenderer.Rule(sym);rule.setFilterExpression('$id = '+str(f.id()));root.appendChild(rule)
p.setRenderer(QgsRuleBasedRenderer(root));svc.bind_renderer(p)
assert svc.rotation_sense(p,f)==1
preview=svc.preview_renderer(p,f);assert len(preview.rootRule().children())==2
canvas.setLayers([p,l]);canvas.setExtent(QgsRectangle(199990,599990,200010,600010));p.selectByIds([f.id()])
values={aid:20};page=SimpleNamespace(feature_id=f.id(),form=SimpleNamespace(values=lambda:dict(values),load_values=lambda d:values.update(d)),binding=SimpleNamespace(has_actual_changes=lambda:None),update_dirty=lambda:None)
rotation=RotationDialog(SimpleNamespace(plugin=plugin,direction=svc),p,page)
assert len(rotation.overlay.renderer().rootRule().children())==2
rotation.set_value(85);rotation.reject();assert p.getFeature(f.id())['rotation']==20 and not p.isModified()
assert len(p.renderer().rootRule().children())==2
print('PASS: Designer save/reopen, exact/tolerance no geometry change, explicit field UUIDs, reducer reversal/subtype/equal/missing/stale guards, single review lock, multi-rule/FID preview and cancel')

# Exercise the controller entry point with the actual calculator and edit buffer.
from unittest.mock import Mock,patch
from geoflow_connector.ui.edit_tools import EditToolsController
page.layer_id=p.id()
ctl=SimpleNamespace(plugin=plugin,direction=svc,_layer_by_id=lambda _:p,refresh=Mock(),_set_message=Mock())
with patch('geoflow_connector.ui.direction.DirectionResults') as popup:
 EditToolsController.calculate_direction(ctl,page=page)
 assert not popup.called and p.getFeature(f.id())['rotation']==90 and p.isModified()
 EditToolsController.calculate_direction(ctl,page=page)
 assert not popup.called and '같습니다' in ctl._set_message.call_args.args[0]
p.rollBack()
missing=add(p,'POINT(200100 600100)',[str(uuid4()),37,'REDUCER'])
p.selectByIds([missing.id()]);page.feature_id=missing.id()
opened=[]
def inspect_popup(dialog):
 opened.append(dialog)
 return 0
with patch.object(DirectionResults,'exec',inspect_popup):
 EditToolsController.calculate_direction(ctl,page=page)
assert len(opened)==1 and opened[0].rows[0]['status']=='no_reference'
assert not p.isModified() and abs(canvas.center().x()-200100)<1
opened.pop().reject()
p.selectByIds([f.id(),missing.id()]);page.feature_id=f.id()
selected=p.selectedFeatureIds()
with patch.object(DirectionResults,'exec',inspect_popup):
 EditToolsController.calculate_direction(ctl,page=page)
dialog=opened.pop()
assert len(dialog.rows)==2 and not p.isModified()
dialog.reviewOnly.setChecked(True)
assert sum(dialog.table.isRowHidden(i) for i in range(2))==1
assert p.selectedFeatureIds()==selected
dialog.apply()
assert p.getFeature(f.id())['rotation']==90 and p.getFeature(missing.id())['rotation']==37
assert p.selectedFeatureIds()==selected
dialog.reject();p.rollBack()
print('PASS: single success/no-change no popup, failure popup and auto-location; batch review filter, explicit apply, failed value/selection preserved')
