"""Explicit local direction rules, isolated by server and project; no data writes."""
import copy
import hashlib
import json
from qgis.core import QgsWkbTypes
from .settings import GeoFlowSettingsService, SettingsValidationError
from .direction_math import validate_config, CAD_RULES

class DirectionPreferences:
    def __init__(self, plugin, settings_service=None):
        self.plugin = plugin
        self.service = settings_service or GeoFlowSettingsService(plugin)

    def key(self):
        client = getattr(getattr(self.plugin, '_definition_service', None), 'client', None)
        client = client or getattr(getattr(self.plugin, 'dialog', None), 'client', None)
        server = str(getattr(client, 'base_url', '') or '').rstrip('/')
        digest = hashlib.sha256(server.encode()).hexdigest()[:20]
        return self.service.key('direction/v1/' + digest)

    def load(self):
        raw = self.service.settings.value(self.key(), '')
        if not raw: return {'rules':{}, 'facilities':{}}
        try:
            result = json.loads(raw)
            if not isinstance(result.get('rules'),dict) or not isinstance(result.get('facilities'),dict): raise ValueError()
            return result
        except (ValueError,TypeError,AttributeError) as exc:
            raise SettingsValidationError('방향각 로컬 설정을 읽을 수 없습니다.') from exc

    def layers(self, geometry):
        return {str(layer.customProperty('geoflow/definition_layer_id','')):layer
                for layer in self.plugin._managed_layers()
                if layer.customProperty('geoflow/definition_layer_id','')
                and QgsWkbTypes.geometryType(layer.wkbType()) == geometry}

    def fields(self, layer):
        definition = getattr(getattr(self.plugin,'_definition_service',None),'definition',{}) or {}
        layer_id = str(layer.customProperty('geoflow/definition_layer_id',''))
        return [f for f in definition.get('fields',[]) if str(f.get('layer_id',''))==layer_id
                and f.get('id') and (f.get('storage') or {}).get('kind')=='column']

    @staticmethod
    def eligible(field, layer):
        index=layer.fields().indexFromName((field.get('storage') or {}).get('key',''))
        return (index>=0 and layer.fields()[index].isNumeric() and not field.get('readonly')
                and field.get('semantic_data_type') in ('integer','decimal'))

    @staticmethod
    def config(document, facility):
        rules=CAD_RULES
        return validate_config(dict(reference_layer_ids=facility['reference_layer_ids'],
            method='nearest',distance=facility['radius'],unit='m',offset=0,
            allow_reverse=True,ambiguity='review',zero_axis=rules.get('zero_axis'),
            positive_direction=rules.get('positive_direction'),symbol_offset=facility['symbol_offset'],
            axis_tolerance=1.0,tie_tolerance=min(0.01,float(facility['radius']))))

    def validate(self, document):
        result=copy.deepcopy(document)
        result['rules']=dict(CAD_RULES)
        points=self.layers(QgsWkbTypes.GeometryType.PointGeometry)
        lines=self.layers(QgsWkbTypes.GeometryType.LineGeometry)
        for layer_id, facility in result['facilities'].items():
            layer=points.get(layer_id)
            if layer is None: raise SettingsValidationError('현재 프로젝트에 없는 시설 레이어 설정입니다.')
            field=next((f for f in self.fields(layer) if str(f['id'])==facility.get('field_id')),None)
            if field is None or not self.eligible(field,layer):
                if field is None:
                    reason='기존 방향각 필드를 선택하지 않았거나 선택한 필드가 현재 정의에 없습니다.'
                else:
                    index=layer.fields().indexFromName(field['storage']['key'])
                    actual=layer.fields()[index].typeName() if index>=0 else '필드 없음'
                    reason=(field['storage']['key']+': 중앙 유형 '+str(field.get('semantic_data_type'))+
                            ', 실제 유형 '+actual+'. 쓰기 가능한 숫자 필드가 필요합니다.')
                error=SettingsValidationError(layer.name()+': '+reason+
                    ' 이 시설의 로컬 설정을 해제하면 다른 시설 설정을 저장할 수 있습니다.')
                error.direction_layer_id=layer_id
                raise error
            if not facility.get('reference_layer_ids') or any(i not in lines for i in facility['reference_layer_ids']):
                raise SettingsValidationError(layer.name()+': 현재 프로젝트의 기준선 레이어를 선택하세요.')
            try: self.config(result,facility)
            except (ValueError,TypeError,KeyError) as exc:
                raise SettingsValidationError(layer.name()+': 공통 각도 규칙·검색 반경·심볼 보정각을 확인하세요.') from exc
        return result

    def save(self, document):
        result=self.validate(document)
        self.service.settings.setValue(self.key(),json.dumps(result,ensure_ascii=False))
        self.service.settings.sync()

    def resolved(self, layer):
        document=self.load()
        facility=document['facilities'].get(str(layer.customProperty('geoflow/definition_layer_id','')))
        if facility is None:return None
        # Return copies; the server definition and its revision remain untouched.
        fields=[dict(f) for f in self.fields(layer) if str(f['id'])==facility.get('field_id')]
        for field in fields:
            field['direction']=self.config(document,facility)
            if not self.eligible(field,layer):
                field['direction_error']='로컬 방향각 대상의 중앙 숫자 필드 계약이 변경되었습니다. 환경설정을 다시 확인하세요.'
            field['capabilities']=['direction']
            field['direction_source']='local_project_settings'
        return fields
