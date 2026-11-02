import sys,tempfile,copy,json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from qgis.core import QgsApplication,QgsProject,QgsVectorLayer,QgsFeature,QgsGeometry,QgsPointXY
from qgis.PyQt.QtCore import QSettings,Qt
from qgis.PyQt.QtWidgets import QMainWindow
app=QgsApplication([],False);app.initQgis()
from qgis.PyQt.QtGui import QFont,QFontDatabase
QFontDatabase.addApplicationFont('C:/Windows/Fonts/malgun.ttf');app.setFont(QFont('Malgun Gothic',9))
tmp=tempfile.TemporaryDirectory()
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,tmp.name)
from geoflow_connector.ui.settings_dialog import GeoFlowSettingsDialog
from geoflow_connector.services.direction_preferences import DirectionPreferences
from geoflow_connector.services.direction import DirectionService
from geoflow_connector.services.settings import SettingsValidationError
project=QgsProject.instance();window=QMainWindow()
point=QgsVectorLayer('Point?crs=EPSG:5186&field=id:string&field=angle:double','Facility','memory')
line=QgsVectorLayer('LineString?crs=EPSG:5186&field=id:string','Water pipe','memory')
point_id,line_id,field_id=[str(uuid4()) for _ in range(3)]
for layer,uid in ((point,point_id),(line,line_id)):
 layer.setCustomProperty('geoflow/definition_layer_id',uid);project.addMapLayer(layer)
def add(layer,geom,name):
 f=QgsFeature(layer.fields());f['id']=name;f.setGeometry(QgsGeometry.fromWkt(geom));layer.dataProvider().addFeature(f);return f
middle=add(point,'POINT(5 0)','middle');near=add(point,'POINT(5 0.2)','near');far=add(point,'POINT(5 2)','far')
add(line,'LINESTRING(0 0,10 0)','main')
field=dict(id=field_id,layer_id=point_id,layer_standard_name='FACILITY',label='Angle',
 field_name='angle',storage={'kind':'column','key':'angle'},semantic_data_type='decimal',readonly=False)
client=SimpleNamespace(base_url='https://example.invalid')
plugin=SimpleNamespace(active_context={'project_id':'test-project'},
 _definition_service=SimpleNamespace(definition={'fields':[field]},client=client),
 _managed_layers=lambda:[point,line],iface=SimpleNamespace(mainWindow=lambda:window),
 integration_state=lambda:{'ready':True,'can_write':True,'project_name':'Test'},
 work=SimpleNamespace(pages={}),edit_tools=None)
preferences=DirectionPreferences(plugin);original=copy.deepcopy(field)
dialog=GeoFlowSettingsDialog(plugin);dialog.show();app.processEvents()
assert dialog.directionFacilityCombo.count()==1
assert dialog.directionZeroCombo.currentData() == 'east'
assert dialog.directionFieldCombo.currentIndex()==-1
assert preferences.load()['facilities']=={}
dialog.directionUseCheck.setChecked(True)
dialog.directionZeroCombo.setCurrentIndex(dialog.directionZeroCombo.findData('east'))
dialog.directionPositiveCombo.setCurrentIndex(dialog.directionPositiveCombo.findData('counterclockwise'))
dialog.directionFieldCombo.setCurrentIndex(0)
dialog.directionReferenceList.item(0).setCheckState(Qt.CheckState.Checked)
dialog.directionRadiusSpin.setValue(0.5)
dialog.directionOffsetSpin.setValue(90)
dialog.settingsTabs.setCurrentWidget(dialog.directionTab);dialog.resize(680,740);app.processEvents()
draft=dialog.direction_editor.document();assert draft['facilities'][point_id]['field_id']==field_id
assert preferences.load()['facilities']=={}
dialog.save();assert dialog.result()==dialog.DialogCode.Accepted
assert preferences.load()['facilities'][point_id]['radius']==0.5
assert field==original and not point.isEditable()
service=DirectionService(plugin)
for f in (middle,near):
 r=service.inspect(point,f);assert r['status']=='ok',r;assert min(r['angle'],360-r['angle'])<0.01,r
assert service.inspect(point,far)['status']=='no_reference'
r=service.inspect(point,near)
service.apply(point,[r],track=False)
assert point.getFeature(near.id())['angle']==0
point.undoStack().undo();point.rollBack()
assert not point.isModified() and not point.isEditable()
# Crossing lines remain reviewable rather than selecting an arbitrary line.
add(line,'LINESTRING(5 -5,5 5)','cross')
assert service.inspect(point,middle)['status']=='ambiguous'
manual=service.manual_result(point,far);assert manual['manual']
reopened=GeoFlowSettingsDialog(plugin)
assert reopened.directionRadiusSpin.value()==0.5
reopened.directionRadiusSpin.setValue(9);reopened.reject()
assert preferences.load()['facilities'][point_id]['radius']==0.5
# Removing all references and using nonnumeric fields cannot be saved.
bad=copy.deepcopy(draft);bad['facilities'][point_id]['reference_layer_ids']=[]
try:preferences.save(bad);raise AssertionError('missing references accepted')
except SettingsValidationError:pass
field['semantic_data_type']='text'
try:preferences.save(draft);raise AssertionError('text field accepted')
except SettingsValidationError:pass
try:service.settings(point,manual=True);raise AssertionError('changed central type accepted')
except ValueError:pass
field['semantic_data_type']='integer'
assert isinstance(service.inspect(point,near)['angle'],float)
assert isinstance(service.storage_value(point,field,12.5),int)
field['semantic_data_type']='decimal'
plugin.active_context['project_id']='another-project';assert preferences.load()['facilities']=={}
try:reopened.direction_editor.document();raise AssertionError('stale project accepted')
except SettingsValidationError:pass
plugin.active_context['project_id']='test-project';client.base_url='https://other.invalid';assert preferences.load()['facilities']=={}
client.base_url='https://example.invalid'
# Existing calculation review is invalidated by rule changes.
r=service.inspect(point,near);draft['facilities'][point_id]['radius']=0.25;preferences.save(draft)
try:service.verify(point,r);raise AssertionError('stale calculation accepted')
except ValueError:pass
assert not point.isModified() and not point.isEditable()
# Actual reported case: a known Other facility with a central/physical text angle.
other=QgsVectorLayer('Point?crs=EPSG:5186&field=ang_dir:string','Other facility','memory')
other_id='c42fc2ed-f09b-42d2-bd82-ff27f208677f'
other_field='502ef46b-9287-4da9-81c2-c085f3ae2090'
other.setCustomProperty('geoflow/definition_layer_id',other_id);project.addMapLayer(other)
plugin._managed_layers=lambda:[point,line,other]
plugin._definition_service.definition['fields'].append(dict(id=other_field,layer_id=other_id,
 label='Angle',storage={'kind':'column','key':'ang_dir'},semantic_data_type='text',readonly=False))
ui=GeoFlowSettingsDialog(plugin)
ui.directionFacilityCombo.setCurrentIndex(ui.directionFacilityCombo.findData(other_id))
assert not ui.directionUseCheck.isEnabled() and not ui.directionUseCheck.isChecked()
assert ui.directionFieldCombo.count()==1 and not ui.directionFieldCombo.model().item(0).isEnabled()
assert 'text' in ui.directionStatus.text()
ui.save();assert ui.result()==ui.DialogCode.Accepted
assert set(preferences.load()['facilities'])=={point_id}
# Previously saved invalid rules stay visible and removable, never silently dropped.
broken=preferences.load();broken['facilities'][other_id]=dict(field_id=other_field,reference_layer_ids=[line_id],radius=1,symbol_offset=0)
preferences.service.settings.setValue(preferences.key(),json.dumps(broken));preferences.service.settings.sync()
ui=GeoFlowSettingsDialog(plugin)
try:ui.direction_editor.document();raise AssertionError('invalid rules silently discarded')
except SettingsValidationError as exc:ui.direction_editor.focus_error(exc)
assert ui.directionFacilityCombo.currentData()==other_id
assert ui.directionUseCheck.isChecked() and ui.directionUseCheck.isEnabled()
ui.directionUseCheck.setChecked(False);ui.save();assert ui.result()==ui.DialogCode.Accepted
assert set(preferences.load()['facilities'])=={point_id}
print('Text-angle facility: unavailable controls visible, valid facilities save, legacy invalid configuration removable: OK')
print('Direction settings UI save/cancel/reopen; midpoint/radius/crossing; manual independence; server/project isolation; invalid fields/references; stale-result guard: OK')
project.clear();window.close()
