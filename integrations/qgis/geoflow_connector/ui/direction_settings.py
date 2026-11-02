"""Bindings for the Designer-owned direction tab. Changes stay draft until Save."""
import copy
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QListWidgetItem
from qgis.core import QgsWkbTypes
from ..services.direction_preferences import DirectionPreferences
from ..services.settings import SettingsValidationError
from ..services.direction_math import CAD_RULES

class DirectionSettingsEditor:
    def __init__(self, dialog, plugin, settings_service):
        self.ui=dialog;self.plugin=plugin
        self.preferences=DirectionPreferences(plugin,settings_service)
        self.scope=self.preferences.key()
        self.draft=copy.deepcopy(self.preferences.load())
        self.points=self.preferences.layers(QgsWkbTypes.GeometryType.PointGeometry)
        self.lines=self.preferences.layers(QgsWkbTypes.GeometryType.LineGeometry)
        self.current=None
        for combo,values in ((dialog.directionZeroCombo,[('동쪽','east')]),
                             (dialog.directionPositiveCombo,[('반시계 방향','counterclockwise')])):
            for text,value in values:combo.addItem(text,value)
            combo.setEnabled(False)
            combo.setToolTip('운영 저장 기준: EPSG:5186, 동쪽 0°·반시계방향. 기존 저장값은 변환하지 않습니다.')
        for combo,key in ((dialog.directionZeroCombo,'zero_axis'),(dialog.directionPositiveCombo,'positive_direction')):
            combo.setCurrentIndex(combo.findData(CAD_RULES[key]))
        for layer_id,layer in self.points.items():dialog.directionFacilityCombo.addItem(layer.name(),layer_id)
        for layer_id in self.draft['facilities']:
            if layer_id not in self.points:dialog.directionFacilityCombo.addItem('현재 프로젝트에 없는 시설 ('+layer_id+')',layer_id)
        for layer_id,layer in self.lines.items():
            item=QListWidgetItem(layer.name(),dialog.directionReferenceList)
            item.setData(Qt.ItemDataRole.UserRole,layer_id)
            item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
        dialog.directionFacilityCombo.currentIndexChanged.connect(self.select_facility)
        dialog.directionUseCheck.toggled.connect(self.update_state)
        self.select_facility()

    def capture(self):
        if self.current is None:return
        ui=self.ui
        if not ui.directionUseCheck.isChecked():
            self.draft['facilities'].pop(self.current,None);return
        refs=[]
        for i in range(ui.directionReferenceList.count()):
            item=ui.directionReferenceList.item(i)
            if item.checkState()==Qt.CheckState.Checked:refs.append(item.data(Qt.ItemDataRole.UserRole))
        self.draft['facilities'][self.current]=dict(field_id=ui.directionFieldCombo.currentData(),
            reference_layer_ids=refs,radius=ui.directionRadiusSpin.value(),symbol_offset=ui.directionOffsetSpin.value())

    def select_facility(self,*args):
        self.capture();ui=self.ui;self.current=ui.directionFacilityCombo.currentData()
        layer=self.points.get(self.current);saved=self.draft['facilities'].get(self.current)
        ui.directionFieldCombo.clear()
        self._eligible_count=0
        self._field_issues=[]
        ui.directionFieldCombo.setPlaceholderText('기존 방향각 필드를 선택하세요')
        if layer is not None:
            for field in self.preferences.fields(layer):
                key=field['storage']['key']
                label=str(field.get('label') or field.get('field_name') or field['id'])
                if self.preferences.eligible(field,layer):
                    ui.directionFieldCombo.addItem(label+' ('+key+')',str(field['id']))
                    self._eligible_count+=1
                else:
                    from ..services.direction import LEGACY_DIRECTION_FIELD_LAYERS
                    known=(LEGACY_DIRECTION_FIELD_LAYERS.get(str(field['id']))==self.current
                           or field.get('direction') is not None
                           or 'direction' in (field.get('capabilities') or []))
                    if known or (saved and saved.get('field_id')==str(field['id'])):
                        index=layer.fields().indexFromName(key)
                        actual=layer.fields()[index].typeName() if index>=0 else '필드 없음'
                        issue=key+': 중앙 '+str(field.get('semantic_data_type'))+' / 실제 '+actual
                        self._field_issues.append(issue)
                        ui.directionFieldCombo.addItem(label+' ('+issue+', 사용 불가)',str(field['id']))
                        item=ui.directionFieldCombo.model().item(ui.directionFieldCombo.count()-1)
                        item.setEnabled(False)
                        item.setToolTip('숫자 필드 계약을 확인해야 합니다. 기존 값이나 타입은 자동 변경하지 않습니다.')
        ui.directionFieldCombo.setCurrentIndex(-1)
        if saved:ui.directionFieldCombo.setCurrentIndex(ui.directionFieldCombo.findData(saved['field_id']))
        ui.directionRadiusSpin.setValue(saved['radius'] if saved else 2)
        ui.directionOffsetSpin.setValue(saved['symbol_offset'] if saved else 0)
        refs=saved['reference_layer_ids'] if saved else []
        for i in range(ui.directionReferenceList.count()):
            item=ui.directionReferenceList.item(i)
            item.setCheckState(Qt.CheckState.Checked if item.data(Qt.ItemDataRole.UserRole) in refs else Qt.CheckState.Unchecked)
        ui.directionUseCheck.setChecked(saved is not None)
        self.update_state()

    def update_state(self,*args):
        ui=self.ui;enabled=ui.directionUseCheck.isChecked() and self.current in self.points
        for widget in (ui.directionFieldCombo,ui.directionReferenceList,ui.directionRadiusSpin,ui.directionOffsetSpin):widget.setEnabled(enabled)
        ui.directionUseCheck.setEnabled(self.current is not None and (self._eligible_count>0 or ui.directionUseCheck.isChecked()))
        if self.current not in self.points:message='현재 프로젝트의 시설 레이어가 없습니다.'
        elif self._eligible_count==0:message='이 시설에는 사용 가능한 중앙 숫자 필드가 없습니다. '+('; '.join(self._field_issues))+'. 로컬 설정을 사용하지 않는 시설은 다른 시설의 저장을 막지 않습니다.'
        elif not enabled:message='이 시설은 중앙 설정을 사용합니다. 로컬 설정을 사용하려면 체크 후 필드와 기준선을 선택하세요.'
        else:message='선택한 기존 숫자 필드에만 적용합니다. 설정 저장 후 자동계산·직접 회전 버튼이 갱신됩니다.'
        ui.directionStatus.setText(message)

    def focus_error(self,error):
        layer_id=getattr(error,'direction_layer_id',None)
        if layer_id is not None:
            self.ui.settingsTabs.setCurrentWidget(self.ui.directionTab)
            index=self.ui.directionFacilityCombo.findData(layer_id)
            if index>=0:self.ui.directionFacilityCombo.setCurrentIndex(index)
            self.ui.directionStatus.setText(str(error))
            self.ui.directionFieldCombo.setFocus()

    def document(self):
        if self.preferences.key()!=self.scope:
            raise SettingsValidationError('프로젝트 또는 서버가 변경되었습니다. 환경설정을 다시 여세요.')
        self.capture()
        self.draft['rules']=dict(zero_axis=self.ui.directionZeroCombo.currentData(),
                                positive_direction=self.ui.directionPositiveCombo.currentData())
        return self.preferences.validate(self.draft)
