import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
ARTIFACTS = ROOT / 'test_artifacts'
ARTIFACTS.mkdir(exist_ok=True)
import sys, tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path.cwd().parent))
from qgis.core import QgsApplication, QgsVectorLayer, QgsFeature, QgsGeometry, QgsProject, QgsVariantUtils
from qgis.PyQt.QtCore import Qt, QSettings, QPoint
from qgis.PyQt.QtGui import QFontDatabase, QFont
from qgis.PyQt.QtWidgets import QWidget, QLabel, QVBoxLayout
from qgis.PyQt.QtTest import QTest
from geoflow_connector.forms.dynamic.form import DynamicForm
from geoflow_connector.forms.dynamic.binding import DynamicFormBinding
from geoflow_connector.forms.dynamic.widgets import WorkStatusSwitch
from geoflow_connector.ui.form_actions import FormActionToolbar
from geoflow_connector.ui.form_host import Main
app=QgsApplication([],False);app.initQgis()
tmp=tempfile.TemporaryDirectory()
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,tmp.name)
for font in ('malgun.ttf','segoeui.ttf','arial.ttf','consola.ttf'):
 QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+font)
app.setFont(QFont('Malgun Gothic',9))
def field(name,kind,label):
 return dict(id=name,label=label,layer_standard_name='TEST',widget_type=kind,
  semantic_data_type=kind,storage=dict(kind='column',key=name),visible=True,readonly=False,
  required=False,display_order=0,layout={},reference_codes=[])
status=field('status','boolean','작업상태');status['reference_codes']=[
 dict(id='pending',value='P',label='미완료'),dict(id='done',value='D',label='완료')]
status['storage']['data_type']='varchar';status['required']=True
note=field('note','text','비고')
layer=QgsVectorLayer('Point?crs=EPSG:5186&field=id:string&field=status:string&field=note:string','시험 시설','memory')
QgsProject.instance().addMapLayer(layer)
features=[]
for i in range(2):
 f=QgsFeature(layer.fields());f['id']=str(i);f.setGeometry(QgsGeometry.fromWkt('POINT(200000 600000)'))
 features.append(layer.dataProvider().addFeatures([f])[1][0])
window=QWidget();layout=QVBoxLayout(window)
from geoflow_connector.ui.main_style import apply_main_style
apply_main_style(window)
form=DynamicForm({'fields':[status,note],'rules':[]},[status,note],window);layout.addWidget(form)
actions=FormActionToolbar(form);form.set_header_widget(actions);form.tabs.setCornerWidget(actions.tabActions,Qt.Corner.TopRightCorner)
page=SimpleNamespace(feature_id=features[0].id(),note=QLabel(),dirty=False,form=form,layer_id=layer.id(),update_dirty=lambda:None)
binding=DynamicFormBinding(page,layer,form,True);page.binding=binding
binding.load(layer.getFeature(page.feature_id),force=True)
switch=form.handles['status'].editor
assert isinstance(switch,WorkStatusSwitch) and switch.width()==36 and switch.height()==20
assert form.values()['status'] is None and not binding.has_actual_changes() and not layer.isModified()
assert switch._null and not switch.isChecked()
window.resize(430,440);window.show();app.processEvents()
actions.set_layer_title('시험 시설')
assert actions.photoButton.parentWidget() is actions.tabActions
assert actions.photoButton.x()<actions.saveButton.x()
assert actions.nearbyButton.x()<actions.depthBatchButton.x()<actions.directionBatchButton.x()
assert not hasattr(actions,'layoutButton') and not hasattr(actions,'referenceRefreshButton')
assert all(not b.icon().isNull() for b in (actions.photoButton,actions.saveButton,actions.directionBatchButton))
form.set_form_layout(form.form_layout);app.processEvents()
assert form.tabs.cornerWidget(Qt.Corner.TopRightCorner) is actions.tabActions
assert actions.saveButton.text()=='저장'
assert actions.previousButton.x()<6
for button in (actions.saveButton,actions.photoButton):
 assert button.visibleRegion().boundingRect().height()==button.height(), (button.height(),button.visibleRegion().boundingRect().height())
window.grab().save(str(ARTIFACTS / 'geoflow-compact-form.png'))
assert binding.save(),page.note.text()
assert layer.getFeature(page.feature_id)['status']=='P'
assert QgsVariantUtils.isNull(layer.getFeature(features[1].id())['status'])
assert not binding.has_actual_changes() and not switch._null and not switch.isChecked()
window.grab().save(str(ARTIFACTS / 'geoflow-workflow-pending.png'))
QTest.mouseClick(switch,Qt.MouseButton.LeftButton,pos=QPoint(30,10))
assert form.values()['status']=='D' and binding.has_actual_changes()
assert binding.save() and layer.getFeature(page.feature_id)['status']=='D' and not binding.has_actual_changes()
window.grab().save(str(ARTIFACTS / 'geoflow-workflow-done.png'))
QTest.keyClick(switch,Qt.Key.Key_Space)
assert form.values()['status']=='P' and binding.save()
assert layer.getFeature(page.feature_id)['status']=='P' and not binding.has_actual_changes()
# Cancellation restores NULL and does not dirty a feature merely because it was loaded.
binding.load(layer.getFeature(features[1].id()),force=True)
QTest.mouseClick(switch,Qt.MouseButton.LeftButton,pos=QPoint(30,10))
QTest.mouseClick(switch,Qt.MouseButton.LeftButton,pos=QPoint(30,10))
assert form.values()['status']=='P' and binding.has_actual_changes()
assert binding.discard() and form.values()['status'] is None and not binding.has_actual_changes()
# Permissions and failed commits do not claim a save or mutate other features.
binding.can_save=False;assert not binding.save()
assert QgsVariantUtils.isNull(layer.getFeature(features[1].id())['status'])
binding.can_save=True;binding.commit_callback=lambda *a,**kw:dict(ok=False)
assert not binding.save() and layer.dataProvider().getFeatures().__next__()['status']=='P'
assert binding.discard()
assert QgsVariantUtils.isNull(layer.getFeature(features[1].id())['status'])
# A stored true boolean, not a code column, must also preserve NULL until save.
bf=field('status','boolean','작업상태');bf['storage']['data_type']='boolean'
bl=QgsVectorLayer('Point?field=status:bool','boolean status','memory');f=QgsFeature(bl.fields());bl.dataProvider().addFeatures([f]);f=next(bl.getFeatures())
fm=DynamicForm({'fields':[bf],'rules':[]},[bf]);bp=SimpleNamespace(feature_id=f.id(),note=QLabel(),dirty=False)
bb=DynamicFormBinding(bp,bl,fm,True);bb.load(f,force=True)
assert not bb.has_actual_changes() and fm.values()['status'] is None
fm.handles['status'].editor.click();fm.handles['status'].editor.click()
assert bb.has_actual_changes() and bb.save() and bl.getFeature(f.id())['status']==False
bb.dispose();binding.dispose();window.close()
print('PASS: real Qt switch mouse/key input; NULL/P/D save/reload/discard/permissions/failure; unrelated NULL retained; Designer tab corner, order and form rebuild')
