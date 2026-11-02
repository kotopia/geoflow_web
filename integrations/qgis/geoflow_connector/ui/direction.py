"""Modeless single-feature preview and reviewed batch direction application."""
import math
from qgis.PyQt.QtCore import Qt, QSignalBlocker
from qgis.PyQt.QtGui import QCursor, QIcon
from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QDoubleSpinBox,
    QPushButton, QLabel, QTableWidget, QTableWidgetItem, QCheckBox, QAbstractItemView)
from qgis.core import (QgsGeometry, QgsPointXY, QgsCoordinateTransform, QgsProject,
    QgsVectorLayer, QgsFeature, QgsRuleBasedRenderer)
from qgis.gui import QgsMapTool
from .result_highlight import ResultHighlight
from ..services.direction_math import normalize


class RotationTool(QgsMapTool):
    """Drag the enlarged symbol around its fixed screen center, without a dial."""
    def __init__(self, canvas, layer, feature, config, changed, *, sense=1, hit_radius=40, cancelled=None):
        super().__init__(canvas)
        self.layer, self.config, self.changed = layer, config, changed
        self.center = QgsCoordinateTransform(layer.crs(), canvas.mapSettings().destinationCrs(),
                                             QgsProject.instance()).transform(feature.geometry().asPoint())
        self.sense, self.hit_radius, self.cancelled = sense, hit_radius, cancelled
        self.dragging = False
        self.value = 0
        self.rotation_cursor = QCursor(QIcon(':/geoflow/tabler/rotate.svg').pixmap(28, 28), 14, 14)
        self.setCursor(self.rotation_cursor)

    def preview(self, value):
        self.value = normalize(value)

    def _pointer_angle(self, pos):
        center = self.toCanvasCoordinates(self.center)
        dx, dy = pos.x()-center.x(), pos.y()-center.y()
        if math.hypot(dx, dy) < 4:
            return None
        return math.degrees(math.atan2(dy, dx))

    def canvasPressEvent(self, event):
        center = self.toCanvasCoordinates(self.center)
        distance = math.hypot(event.pos().x()-center.x(), event.pos().y()-center.y())
        if event.button() != Qt.MouseButton.LeftButton or distance > self.hit_radius:
            return
        self.dragging = True
        self.last_pointer = self._pointer_angle(event.pos())
        self.drag_value = self.value
        self.setCursor(self.rotation_cursor)

    def canvasMoveEvent(self, event):
        if not self.dragging:
            return
        pointer = self._pointer_angle(event.pos())
        if pointer is None:
            return
        if self.last_pointer is not None:
            delta = (pointer-self.last_pointer+180) % 360-180
            self.drag_value = normalize(self.drag_value+delta/self.sense)
            self.changed(self.drag_value)
        self.last_pointer = pointer

    def canvasReleaseEvent(self, event):
        if self.dragging:
            self.canvasMoveEvent(event)
        self.dragging = False
        self.setCursor(self.rotation_cursor)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self.cancelled:
            self.cancelled()
        else:
            super().keyPressEvent(event)

    def dispose(self):
        self.dragging = False


class RotationDialog(QDialog):
    def __init__(self, controller, layer, page):
        super().__init__(controller.plugin.iface.mainWindow())
        self.controller, self.layer, self.page = controller, layer, page
        self.service = controller.direction
        self.field, self.config = self.service.settings(layer, manual=True)
        self.fid = page.feature_id
        self.result = self.service.manual_result(layer, layer.getFeature(self.fid))
        if not self.result.get('fingerprint'):
            raise ValueError(self.result.get('reason', '기하 오류'))
        self.closed = False
        self.setWindowTitle('방향 조정 · 적용 후 기존 저장 사용')
        layout = QVBoxLayout(self)
        self.spin = QDoubleSpinBox(self)
        decimals = self.service.storage_decimals(layer, self.field)
        decimals = 8 if decimals is None else decimals
        self.spin.setDecimals(decimals); self.spin.setRange(0,360-10**(-decimals)); self.spin.setWrapping(True)
        self.spin.setKeyboardTracking(True); self.spin.setSuffix('°')
        layout.addWidget(self.spin)
        self.note = QLabel('지도에서 3배 확대된 심볼을 드래그하세요. Esc: 취소',self)
        layout.addWidget(self.note)
        actions = QHBoxLayout(); layout.addLayout(actions)
        for label, callback in (('180° 반전', self.flip), ('적용', self.apply), ('취소',self.reject)):
            button = QPushButton(label,self); button.clicked.connect(callback); actions.addWidget(button)
            if label == '180° 반전': button.setEnabled(self.config['allow_reverse'])
        self.canvas = controller.plugin.mapCanvas
        self.previous_tool = self.canvas.mapTool()
        feature = layer.getFeature(self.fid)
        # An unregistered memory layer is visible only in this canvas during preview.
        self.overlay = QgsVectorLayer('Point?crs='+layer.crs().authid(), 'GeoFlow 방향 미리보기','memory')
        self.overlay.setCrs(layer.crs())
        self.overlay.dataProvider().addAttributes(list(layer.fields())); self.overlay.updateFields()
        self.preview_feature = QgsFeature(feature)
        self.overlay.dataProvider().addFeature(self.preview_feature)
        self.overlay.setRenderer(self.service.preview_renderer(layer, feature))
        self.overlay.setCustomProperty('geoflow/definition_layer_id',layer.customProperty('geoflow/definition_layer_id',''))
        self.service.bind_renderer(self.overlay)
        from qgis.core import QgsProperty, QgsRenderContext, QgsExpressionContextUtils
        context = QgsRenderContext.fromMapSettings(self.canvas.mapSettings())
        context.expressionContext().appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(self.overlay))
        context.expressionContext().setFeature(self.preview_feature)
        hit_radius = 18
        for symbol in self.overlay.renderer().symbols(context):
            if not hasattr(symbol, 'setSize'):
                continue
            size = symbol.dataDefinedSize()
            if size.isActive():
                symbol.setDataDefinedSize(QgsProperty.fromExpression('3 * ('+size.asExpression()+')'))
            else:
                symbol.setSize(symbol.size()*3)
            pixels = context.convertToPainterUnits(symbol.size(context),symbol.sizeUnit(),symbol.sizeMapUnitScale())
            hit_radius = max(hit_radius, pixels/2+12)
        self.tool = RotationTool(self.canvas, layer, feature, self.config, self.set_value,
            sense=self.service.rotation_sense(self.overlay,self.preview_feature),
            hit_radius=hit_radius, cancelled=self.reject)
        self.original_renderer = layer.renderer().clone()
        filtered = QgsRuleBasedRenderer.convertFromRenderer(layer.renderer())
        if filtered is None:
            raise ValueError('이 렌더러는 회전 미리보기를 지원하지 않습니다.')
        original_filter = filtered.rootRule().filterExpression()
        filtered.rootRule().setFilterExpression(('$id != '+str(self.fid)) + (' AND ('+original_filter+')' if original_filter else ''))
        layer.setRenderer(filtered)
        self.preview_renderer = layer.renderer()
        layer.triggerRepaint()
        self.canvas.setLayers([self.overlay]+self.canvas.layers())
        self.canvas.setMapTool(self.tool)
        self.canvas.setCenter(self.tool.center)
        self.canvas.refresh()
        self.spin.valueChanged.connect(self.set_value)
        self.connections = [(controller.plugin.iface.currentLayerChanged,self.active_layer_changed),
                            (layer.selectionChanged,self.selection_changed),
                            (self.canvas.mapToolSet,self.tool_changed),
                            (self.canvas.destinationCrsChanged,self.reject),
                            (QgsProject.instance().cleared,self.reject)]
        for signal, slot in self.connections: signal.connect(slot)
        self.finished.connect(self.cleanup)
        old = page.form.values().get(self.field['id'])
        try: value = float(old)
        except (ValueError,TypeError): value = 0
        self.set_value(value)

    def set_value(self, value):
        value = self.service.storage_value(self.layer, self.field, value)
        with QSignalBlocker(self.spin):
            self.spin.setValue(value)
        index = self.overlay.fields().indexFromName(self.field['storage']['key'])
        self.overlay.dataProvider().changeAttributeValues({self.preview_feature.id():{index:value}})
        self.overlay.triggerRepaint(); self.tool.preview(value)

    def flip(self): self.set_value(self.spin.value()+180)

    def active_layer_changed(self, layer):
        # A transient legend reset is not a request to cancel rotation.
        if layer is not None and layer is not self.layer:
            self.reject()

    def selection_changed(self,*args):
        if self.layer.selectedFeatureIds() != [self.fid]: self.reject()

    def tool_changed(self, tool,*args):
        if tool is not self.tool: self.reject()

    def apply(self):
        try:
            if self.page.feature_id != self.fid: raise ValueError('객체가 변경되었습니다.')
            angle = self.spin.value()
            old = self.page.form.values().get(self.field['id'])
            try: unchanged = float(old) == angle
            except (ValueError,TypeError): unchanged = False
            if not unchanged:
                self.restore_renderer()
                self.service.apply(self.layer,[dict(self.result,angle=angle)],self.page, track=False)
            self.accept()
        except Exception as exc:
            self.note.setText(str(exc))

    def restore_renderer(self):
        try:
            if self.layer.renderer() is self.preview_renderer:
                self.layer.setRenderer(self.original_renderer.clone())
                self.layer.triggerRepaint()
        except RuntimeError:
            pass

    def cleanup(self,*args):
        if self.closed: return
        self.closed = True
        self.restore_renderer()
        for signal,slot in self.connections:
            try: signal.disconnect(slot)
            except (RuntimeError,TypeError): pass
        if self.canvas.mapTool() is self.tool:
            self.canvas.unsetMapTool(self.tool)
            if self.previous_tool is not None: self.canvas.setMapTool(self.previous_tool)
        self.canvas.setLayers([x for x in self.canvas.layers() if x is not self.overlay])
        self.tool.dispose(); self.tool.deleteLater()
        plugin = self.controller.plugin
        from qgis.PyQt import sip
        if (not sip.isdeleted(self.layer) and plugin.integration_state().get('ready')
                and plugin.iface.activeLayer() is None
                and QgsProject.instance().mapLayer(self.layer.id()) is self.layer
                and any(item is self.layer for item in plugin._managed_layers())):
            plugin.iface.setActiveLayer(self.layer)
        self.canvas.refresh()


class DirectionResults(QDialog):
    LABELS = {'ok':'계산 가능','no_reference':'기준선 없음','ambiguous':'후보 모호',
              'no_config':'설정 없음','error':'기하 또는 필드 오류'}
    def __init__(self, controller, layer, features, page=None, *, results=None):
        super().__init__(controller.plugin.iface.mainWindow())
        self.controller,self.layer,self.page = controller,layer,page
        self.rows = []
        self.changed_rows = []
        self.highlight = ResultHighlight(controller.plugin.mapCanvas)
        self.bands = self.highlight.bands
        self.setWindowTitle('방향각 계산 결과 · 행 선택으로 위치 확인')
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0,6,self)
        self.table.setHorizontalHeaderLabels(['적용','객체','기존 각도','계산 각도','기준선','결과 사유'])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)
        single = len(features)==1
        results = results if results is not None else [controller.direction.inspect(layer, f) for f in features]
        for feature, result in zip(features, results):
            candidates = result['candidates'] if single and result['status']=='ambiguous' and not result.get('review_only') else [None]
            for candidate in candidates:
                row = dict(result)
                if candidate:
                    row.update(angle=candidate['angle'], chosen=candidate)
                self.rows.append(row)
                index = self.table.rowCount(); self.table.insertRow(index)
                check = QTableWidgetItem()
                allowed = result['status']=='ok' or candidate is not None
                check.setFlags(Qt.ItemFlag.ItemIsEnabled | (Qt.ItemFlag.ItemIsUserCheckable if allowed else Qt.ItemFlag.NoItemFlags))
                check.setCheckState(Qt.CheckState.Checked if result['status']=='ok' else Qt.CheckState.Unchecked)
                self.table.setItem(index,0,check)
                reference = candidate or result.get('chosen') or (result['candidates'][0] if result['candidates'] else {})
                for col,value in enumerate((result.get('identity',feature.id()),result.get('old',''),
                    row.get('angle',''),reference.get('reference_label',reference.get('reference','')),result.get('reason',self.LABELS[result['status']])),1):
                    self.table.setItem(index,col,QTableWidgetItem(str(value)))
        self.table.currentCellChanged.connect(self.locate)
        self.reviewOnly = QCheckBox('실패·검토 대상만 보기 (선택한 성공 항목은 적용 대상에 유지)', self)
        self.reviewOnly.toggled.connect(self.filter_rows)
        layout.addWidget(self.reviewOnly)
        success = sum(r['status'] == 'ok' for r in results)
        layout.addWidget(QLabel(f'선택 {len(features)}개 · 계산 성공 {success}개 · 실패·검토 {len(features)-success}개. 아직 저장하지 않았습니다.', self))
        self.note = QLabel('EPSG:5186 · 최장 선분 우선 · 동일 길이는 객체 ID 순서. 적용 전 기준선을 확인하세요.')
        layout.addWidget(self.note)
        button = QPushButton('선택 적용',self); button.clicked.connect(self.apply); layout.addWidget(button)
        changed = QPushButton('변경 객체 전체 보기',self)
        changed.clicked.connect(lambda:self.highlight.show(self.layer,self.changed_rows,zoom=True))
        layout.addWidget(changed)
        clear = QPushButton('강조 해제',self); clear.clicked.connect(self.highlight.clear); layout.addWidget(clear)
        close = QPushButton('닫기',self); close.clicked.connect(self.reject); layout.addWidget(close)
        self.finished.connect(self.cleanup)
        self.resize(850,400)
        if self.rows: self.table.setCurrentCell(0, 1)

    def filter_rows(self, review_only):
        visible = []
        for index, row in enumerate(self.rows):
            hidden = review_only and row['status'] == 'ok'
            self.table.setRowHidden(index, hidden)
            if not hidden: visible.append(index)
        if visible: self.table.setCurrentCell(visible[0], 1)
        else: self.highlight.clear()

    def locate(self,row,*args):
        self.cleanup()
        if not 0 <= row < len(self.rows): return
        result = self.rows[row]
        canvas = self.controller.plugin.mapCanvas
        geometry = self.layer.getFeature(result['fid']).geometry()
        transform = QgsCoordinateTransform(self.layer.crs(),canvas.mapSettings().destinationCrs(),QgsProject.instance())
        geometry.transform(transform)
        candidates = [result['chosen']] if result.get('chosen') else result['candidates']
        geometries = [self.highlight.add(self.layer.getFeature(result['fid']).geometry(),self.layer.crs(),
                                        'review' if result['status'] in ('ok','ambiguous') else 'failed')]
        for candidate in candidates:
            line = QgsGeometry.fromPolylineXY([QgsPointXY(*xy) for xy in candidate['map_line']])
            geometries.append(self.highlight.add(line,self.layer.crs(),'review'))
        self.highlight.zoom([g for g in geometries if g is not None])

    def cleanup(self,*args):
        self.highlight.clear()

    def apply(self):
        selected = [row for i,row in enumerate(self.rows) if self.table.item(i,0).checkState()==Qt.CheckState.Checked]
        if not selected: return
        if len({r['fid'] for r in selected}) != len(selected):
            self.note.setText('객체마다 후보 하나만 선택하세요.'); return
        try:
            applied = self.controller.direction.apply(self.layer,selected,self.page)
            self.changed_rows = [dict(r,status='changed') for r in applied]
            self.highlight.show(self.layer,self.changed_rows,zoom=True)
            self.note.setText('편집 버퍼에 적용했습니다. 기존 저장 기능으로 저장하세요.')
            for i in range(self.table.rowCount()):
                self.table.item(i,0).setCheckState(Qt.CheckState.Unchecked)
        except Exception as exc: self.note.setText(str(exc))
