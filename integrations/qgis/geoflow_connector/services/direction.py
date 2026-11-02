"""Project-scoped QGIS adapter. Calculations never write or contact a server."""
import hashlib
import json
import weakref
try:
    from qgis.PyQt.QtGui import QUndoCommand
except ImportError:
    from qgis.PyQt.QtWidgets import QUndoCommand
from qgis.core import (QgsProject, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsGeometry, QgsPointXY, QgsFeatureRequest, QgsRectangle, QgsWkbTypes,
    QgsProperty, QgsRenderContext)
from .direction_math import (calculate, validate_config, validate_rotation, normalize,
                             operational_config, quantize_angle, ANGLE_CRS)


# Explicit identities verified from the central definitions of C26070/C26048.
# Compatibility with servers predating capabilities; no field-name inference,
# angle defaults, type coercion or writes to the server definition.
LEGACY_DIRECTION_FIELD_LAYERS = {
    '63b76009-fc28-4a7c-b2cf-1fba61e04d2f': '5f9610bf-b555-4e4c-94b9-2c9097aa6030',
    '502ef46b-9287-4da9-81c2-c085f3ae2090': 'c42fc2ed-f09b-42d2-bd82-ff27f208677f',
}


class FormAngleCommand(QUndoCommand):
    """Restore a pre-existing form draft after the layer attribute undo completes."""
    def __init__(self, page, field_id, after):
        super().__init__('GeoFlow 방향각 폼')
        def reference(value):
            try: return weakref.ref(value)
            except TypeError: return lambda: value  # lightweight test adapters
        self.form, self.binding = reference(page.form), reference(page.binding)
        self.field_id = field_id
        self.feature_id = page.feature_id
        self.before = page.form.values().get(field_id)
        self.after = after

    def set_value(self, value):
        form, binding = self.form(), self.binding()
        if form is None or binding is None or getattr(binding, 'feature_id', self.feature_id) != self.feature_id:
            return
        try:
            values = form.values(); values[self.field_id] = value
            form.load_values(values); binding.has_actual_changes()
        except RuntimeError:
            pass  # form already destroyed; layer undo remains valid

    def undo(self):
        self.set_value(self.before)
    def redo(self): self.set_value(self.after)


class DirectionService:
    def __init__(self, plugin):
        self.plugin = plugin
        self.project = QgsProject.instance()

    def targets(self, layer):
        if layer is None: return []
        from .direction_preferences import DirectionPreferences
        local = DirectionPreferences(self.plugin).resolved(layer)
        if local is not None: return local
        layer_id = str(layer.customProperty('geoflow/definition_layer_id', ''))
        definition = getattr(getattr(self.plugin, '_definition_service', None), 'definition', {}) or {}
        return [f for f in definition.get('fields', []) if str(f.get('layer_id','')) == layer_id
                and (f.get('direction') is not None or 'direction' in (f.get('capabilities') or [])
                     or ('capabilities' not in f and LEGACY_DIRECTION_FIELD_LAYERS.get(str(f.get('id',''))) == layer_id))]

    def settings(self, layer, *, manual=False):
        fields = self.targets(layer)
        if len(fields) != 1:
            raise ValueError('중앙 UUID에 연결된 방향각 기능 정의가 없거나 여러 개입니다.')
        field = fields[0]
        if field.get('direction_error'): raise ValueError(field['direction_error'])
        storage = field.get('storage') or {}
        index = layer.fields().indexFromName(storage.get('key') or '')
        if (storage.get('kind') != 'column' or index < 0 or not layer.fields()[index].isNumeric()
                or field.get('readonly') or QgsWkbTypes.geometryType(layer.wkbType()) != QgsWkbTypes.GeometryType.PointGeometry):
            raise ValueError('방향각 대상 필드·점 기하·읽기 전용 설정을 확인하세요.')
        if field.get('direction') is None:
            raise ValueError('방향각 규칙 미설정: 0° 방향·증가 방향·심볼 보정각을 확인해야 합니다. 기존 값은 변경하지 않습니다.')
        return field, (validate_rotation if manual else validate_config)(operational_config(field.get('direction')))

    def storage_decimals(self, layer, field):
        from qgis.PyQt.QtCore import QMetaType
        actual = layer.fields()[layer.fields().indexFromName(field['storage']['key'])]
        if actual.type() in (QMetaType.Type.Int, QMetaType.Type.UInt,
                             QMetaType.Type.LongLong, QMetaType.Type.ULongLong):
            return 0
        limits = [int(field['scale'])] if field.get('scale') is not None else []
        if field.get('semantic_data_type') == 'integer': limits.append(0)
        if actual.precision() > 0: limits.append(actual.precision())
        return min(limits) if limits else None

    def storage_value(self, layer, field, value):
        return quantize_angle(value, self.storage_decimals(layer, field))

    def manual_result(self, layer, feature):
        field, config = self.settings(layer, manual=True)
        geom = feature.geometry()
        if not feature.isValid() or geom.isEmpty() or geom.isMultipart():
            raise ValueError('유효한 단일 점 객체가 필요합니다.')
        key = field['storage']['key']
        identity = str(feature['id']) if 'id' in feature.fields().names() else str(feature.id())
        payload = (layer.id(),layer.crs().toWkt(),bytes(geom.asWkb()).hex(),field['id'],key,identity,config)
        return dict(manual=True,fid=feature.id(),field_id=field['id'],key=key,old=feature[key],
                    identity=identity,fingerprint=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest())

    def _references(self, config):
        # These layers were materialized from this project's Final Layer Plan.
        refs = set(config['reference_layer_ids'])
        return [layer for layer in self.plugin._managed_layers()
                if str(layer.customProperty('geoflow/definition_layer_id', '')) in refs
                and QgsWkbTypes.geometryType(layer.wkbType()) == QgsWkbTypes.GeometryType.LineGeometry]

    def inspect(self, layer, feature):
        try:
            field, config = self.settings(layer)
        except (ValueError, TypeError) as exc:
            return dict(status='no_config', reason=str(exc), fid=feature.id(), candidates=[])
        key = field['storage']['key']
        base = dict(fid=feature.id(), field_id=field['id'], key=key, old=feature[key],
                    identity=str(feature['id']) if 'id' in feature.fields().names() else str(feature.id()),
                    candidates=[])
        try:
            geom = feature.geometry()
            if geom.isEmpty() or geom.isMultipart() or not feature.isValid():
                raise ValueError('단일 점 기하가 필요합니다.')
            wgs = QgsCoordinateReferenceSystem('EPSG:4326')
            center = QgsCoordinateTransform(layer.crs(), wgs, self.project).transform(geom.asPoint())
            metric = QgsCoordinateReferenceSystem()
            if not metric.createFromProj('+proj=aeqd +lat_0=%.12f +lon_0=%.12f +datum=WGS84 +units=m +no_defs' % (center.y(), center.x())):
                raise ValueError('미터 좌표계 생성 실패')
            point = QgsCoordinateTransform(layer.crs(), metric, self.project).transform(geom.asPoint())
            xy = (point.x(), point.y())
            radius = config['distance']
            box = QgsRectangle(point.x()-radius, point.y()-radius, point.x()+radius, point.y()+radius)
            lines, evidence = [], []
            reference_metadata = {}
            angle_points = {}
            for ref in self._references(config):
                forward = QgsCoordinateTransform(ref.crs(), metric, self.project)
                cad_transform = QgsCoordinateTransform(ref.crs(), QgsCoordinateReferenceSystem(ANGLE_CRS), self.project)
                backward = QgsCoordinateTransform(metric, ref.crs(), self.project)
                search = backward.transformBoundingBox(box)
                for item in ref.getFeatures(QgsFeatureRequest().setFilterRect(search)):
                    evidence.append((ref.id(), item.id(), bytes(item.geometry().asWkb()).hex(), str(item['id']) if 'id' in item.fields().names() else str(item.id())))
                    line = QgsGeometry(item.geometry())
                    line.transform(forward)
                    parts = line.asMultiPolyline() if line.isMultipart() else [line.asPolyline()]
                    reference=ref.id()+':'+str(item.id())
                    cad_line = QgsGeometry(item.geometry())
                    cad_line.transform(cad_transform)
                    cad_parts = cad_line.asMultiPolyline() if cad_line.isMultipart() else [cad_line.asPolyline()]
                    for part, cad_part in zip(parts, cad_parts):
                        for vertex, cad_vertex in zip(part, cad_part):
                            angle_points[(reference, (vertex.x(), vertex.y()))] = (cad_vertex.x(), cad_vertex.y())
                    feature_uuid=str(item['id']) if 'id' in item.fields().names() else ''
                    reference_metadata[reference]=dict(feature_uuid=feature_uuid,
                        layer_uuid=str(ref.customProperty('geoflow/definition_layer_id','')),
                        reference_label=ref.name()+' / '+(feature_uuid or 'UUID 없음'))
                    lines.append((reference, [[(v.x(),v.y()) for v in part] for part in parts]))
            def angle_xy(reference, xy):
                return angle_points[(reference, xy)]
            result = calculate(xy, lines, config, reference_metadata, angle_transform=angle_xy)
            result['angle_crs'] = ANGLE_CRS
            for candidate in result['candidates']:
                tx = QgsCoordinateTransform(metric, layer.crs(), self.project)
                candidate['map_line'] = [(p.x(),p.y()) for p in
                    (tx.transform(QgsPointXY(*candidate['a'])), tx.transform(QgsPointXY(*candidate['b'])))]
            # Exclude target angle: applying a result must not invalidate its own evidence.
            target_attrs = (base['identity'], field['id'], key, field.get('semantic_data_type'), field.get('scale'))
            payload = (layer.id(), layer.crs().toWkt(), bytes(geom.asWkb()).hex(), target_attrs,
                       config, ANGLE_CRS, sorted(evidence), [(r.id(), r.crs().toWkt()) for r in self._references(config)])
            digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
            return dict(base, **result, fingerprint=digest)
        except Exception as exc:
            return dict(base, status='error', reason=str(exc))

    def verify(self, layer, result):
        fresh = (self.manual_result if result.get('manual') else self.inspect)(layer, layer.getFeature(result['fid']))
        if not result.get('fingerprint') or fresh.get('fingerprint') != result['fingerprint']:
            raise ValueError('대상 또는 기준선/설정이 변경되었습니다. 방향각을 다시 계산하세요.')
        return fresh

    def bind_renderer(self, layer):
        field, config = self.settings(layer, manual=True)
        key = field['storage']['key'].replace('"', '""')
        # Rotate in display coordinates, keeping CAD grid axes separate from
        # the canvas CRS. A one-metre CAD vector supplies local grid convergence.
        expression = ("with_variable('cad_p', transform($geometry, @layer_crs, 'EPSG:5186'), "
            "((degrees(azimuth(transform(@cad_p, 'EPSG:5186', coalesce(@map_crs,@layer_crs)), "
            "transform(project(@cad_p, 1, radians(90-coalesce(\"%s\",0))), "
            "'EPSG:5186', coalesce(@map_crs,@layer_crs)))) + %s) %% 360 + 360) %% 360)"
            % (key, config['symbol_offset']))
        renderer = layer.renderer().clone()
        for symbol in renderer.symbols(QgsRenderContext()):
            if hasattr(symbol, 'setDataDefinedAngle'):
                symbol.setDataDefinedAngle(QgsProperty.fromExpression(expression))
        layer.setRenderer(renderer)
        layer.triggerRepaint()

    def apply(self, layer, results, page=None, *, track=True):
        if (not self.plugin.integration_state().get('can_write') or layer.readOnly()
                or not any(item is layer for item in self.plugin._managed_layers())):
            raise ValueError('편집 권한이 없습니다.')
        for result in results:
            self.verify(layer, result)
            current = layer.getFeature(result['fid'])
            if str(current[result['key']]) != str(result['old']):
                raise ValueError('기존 각도가 변경되었습니다. 다시 계산하세요.')
        field, _ = self.settings(layer, manual=True)
        results = [dict(result, angle=self.storage_value(layer, field, result['angle'])) for result in results]
        def same_value(result):
            try: return float(layer.getFeature(result['fid'])[result['key']]) == result['angle']
            except (ValueError, TypeError): return False
        results = [result for result in results if not same_value(result)]
        if not results:
            return []
        if not layer.isEditable() and not layer.startEditing():
            raise ValueError('편집을 시작할 수 없습니다.')
        stack = layer.undoStack()
        stack.beginMacro('GeoFlow direction')
        for result in results:
            if page is not None and page.feature_id == result['fid']:
                command = FormAngleCommand(page, result['field_id'], result['angle'])
                # QGIS owns the C++ command; retain the Python override while it is in the stack.
                from qgis.PyQt import sip
                commands = [c for c in getattr(layer, '_geoflow_form_commands', []) if not sip.isdeleted(c)]
                commands.append(command)
                layer._geoflow_form_commands = commands
                stack.push(command)
        layer.beginEditCommand('GeoFlow direction attributes')
        try:
            for result in results:
                index = layer.fields().indexFromName(result['key'])
                if not layer.changeAttributeValue(result['fid'], index, result['angle']):
                    raise ValueError('방향각 적용 실패')
            layer.endEditCommand()
            stack.endMacro()
        except Exception:
            layer.destroyEditCommand()
            stack.endMacro()
            failed = stack.command(stack.index()-1)
            stack.undo()
            failed.setObsolete(True)
            raise
        # Keep unrelated draft form fields. The layer buffer owns undo/redo.
        if page is not None and page.feature_id in {r['fid'] for r in results}:
            self.sync_form(page, layer)
        self.bind_renderer(layer)
        pending = getattr(self.plugin, '_direction_pending', {})
        for result in results:
            if track:
                pending[(layer.id(), result['fid'])] = dict(result)
        self.plugin._direction_pending = pending
        return results

    def sync_form(self, page, layer):
        field, _ = self.settings(layer, manual=True)
        feature = layer.getFeature(page.feature_id)
        if feature.isValid():
            values = page.form.values()
            values[field['id']] = feature[field['storage']['key']]
            page.form.load_values(values)
            page.binding.has_actual_changes()
            page.update_dirty()


def validate_pending(plugin, layer):
    service = DirectionService(plugin)
    pending = getattr(plugin, '_direction_pending', {})
    for (layer_id, fid), result in list(pending.items()):
        if layer_id != layer.id():
            continue
        buffer = layer.editBuffer()
        index = layer.fields().indexFromName(result['key'])
        if buffer is None or index not in buffer.changedAttributeValues().get(fid, {}):
            pending.pop((layer_id, fid), None)
            continue
        feature = layer.getFeature(fid)
        if not feature.isValid() or str(feature[result['key']]) != str(result['angle']):
            pending.pop((layer_id, fid), None)  # deleted, undone or manually replaced
            continue
        service.verify(layer, result)
