import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
ARTIFACTS = ROOT / 'test_artifacts'
ARTIFACTS.mkdir(exist_ok=True)
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtWidgets import QWidget,QLabel,QPushButton,QMessageBox
from qgis.core import QgsApplication,QgsProject,QgsVectorLayer,QgsFeature,QgsGeometry
from geoflow_connector.forms.dynamic.form import DynamicForm
from geoflow_connector.forms.dynamic.binding import DynamicFormBinding
from geoflow_connector.services.direction import DirectionService
from geoflow_connector.ui.form_host import Main
app=QgsApplication([],False);app.initQgis()
layer=QgsVectorLayer('Point?field=id:string&field=angle:double','valve','memory')
QgsProject.instance().addMapLayer(layer);layer.setCustomProperty('geoflow/definition_layer_id','layer-test')
features=[]
for i in range(2):
 f=QgsFeature(layer.fields());f['id']='id-'+str(i);f['angle']=0;f.setGeometry(QgsGeometry.fromWkt('POINT(%d 0)'%i));layer.dataProvider().addFeature(f);features.append(f)
field=dict(id='angle-field',layer_id='layer-test',layer_standard_name='WTL_VALV_PS',semantic_data_type='decimal',
 widget_type='decimal',label='Angle',visible=True,required=False,readonly=False,display_order=0,layout={},reference_codes=[],
 storage={'kind':'column','key':'angle'},direction=dict(zero_axis='north',positive_direction='clockwise',symbol_offset=0,allow_reverse=True))
plugin=SimpleNamespace(_definition_service=SimpleNamespace(definition={'fields':[field]}),
 _managed_layers=lambda:[layer],integration_state=lambda:{'can_write':True,'ready':True},active_context={'project_id':'navigation-test'},
 iface=SimpleNamespace(messageBar=lambda:SimpleNamespace(pushWarning=Mock())),edit_tools=None)
form=DynamicForm({'fields':[field],'rules':[]},[field])
page=SimpleNamespace(note=QLabel(),dirty=False,layer_id=layer.id(),feature_id=features[0].id(),form=form,update_dirty=lambda:None)
page.photos=SimpleNamespace(has_pending_changes=lambda:False,commit_pending=lambda:{'ok':True},discard_pending=lambda **kw:None,refresh_policy=lambda:None)
page.binding=DynamicFormBinding(page,layer,form,True,commit_callback=lambda layer,**kw:{'ok':layer.commitChanges(False)})
page.binding.load(layer.getFeature(page.feature_id),force=True)
class Host(Main):
 def __init__(self):
  QWidget.__init__(self);self.plugin=plugin;self.pages={layer.id():page};self.formStack=SimpleNamespace(currentWidget=lambda:page)
  self.save_button=QPushButton();self.previous_values=SimpleNamespace(capture=lambda page:None)
host=Host();service=DirectionService(plugin)
def apply_angles(first,second=None):
 rows=[dict(service.manual_result(layer,layer.getFeature(page.feature_id)),angle=first)]
 if second is not None:rows.append(dict(service.manual_result(layer,layer.getFeature(features[1].id())),angle=second))
 service.apply(layer,rows,page,track=False)
 assert page.binding.has_actual_changes()
original_exec=QMessageBox.exec
prompts=[];nested=[]
def choose(label):
 def execute(dialog):
  prompts.append(label)
  def click():
   nested.append(host._guard_object_transition(None,None))
   next(b for b in dialog.buttons() if b.text()==label).click()
  QTimer.singleShot(0,click)
  return original_exec(dialog)
 return execute
# Reproduce the reported 0 -> 180 rotation staged in the QGIS buffer.
apply_angles(180)
assert page.binding._feature_values(layer.getFeature(page.feature_id)) != page.binding.source_original
with patch.object(QMessageBox,'exec',choose('저장 후 이동')):
 assert host._guard_object_transition(None,None)
 assert host._guard_object_transition(None,None)
assert prompts==['저장 후 이동'] and nested==[False]
assert not page.dirty and not layer.isModified() and layer.getFeature(page.feature_id)['angle']==180
# Batch edits: discard this feature while retaining the second feature's value/geometry.
apply_angles(270,90)
layer.changeGeometry(features[1].id(),QgsGeometry.fromWkt('POINT(9 9)'))
with patch.object(QMessageBox,'exec',choose('변경 취소 후 이동')):
 assert host._guard_object_transition(None,None)
 assert host._guard_object_transition(None,None)
assert len(prompts)==2 and not page.dirty
assert layer.getFeature(page.feature_id)['angle']==180
assert layer.getFeature(features[1].id())['angle']==90
assert layer.getFeature(features[1].id()).geometry().asPoint().x()==9
assert layer.isModified()
layer.rollBack();page.binding.load(layer.getFeature(page.feature_id),force=True)
# A failed commit stays dirty and returns a visible reason, not a false success.
apply_angles(120);page.binding.commit_callback=lambda *a,**kw:{'ok':False}
with patch.object(QMessageBox,'exec',choose('저장 후 이동')):assert not host._guard_object_transition(None,None)
assert page.binding.has_actual_changes() and layer.isModified()
with patch.object(QMessageBox,'exec',choose('변경 취소 후 이동')):assert host._guard_object_transition(None,None)
assert not page.dirty and not layer.isModified()
# Real provider mutation is still rejected, even if a local edit buffer also exists.
page.binding.load(layer.getFeature(page.feature_id),force=True)
layer.dataProvider().changeAttributeValues({page.feature_id:{1:45}})
form.load_values({'angle-field':60});assert not page.binding.save()
assert layer.getFeature(page.feature_id)['angle']==45
print('Actual QGIS rotation -> Save/Discard navigation: one prompt; reentry blocked; unrelated batch edits retained; commit failure and external-provider conflict retained: OK')
page.binding.dispose();host.close();QgsProject.instance().clear()
