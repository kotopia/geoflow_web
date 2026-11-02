"""Modeless single-feature preview and reviewed batch direction application."""
import math
from qgis.PyQt.QtCore import Qt, QSignalBlocker
from qgis.PyQt.QtGui import QColor, QPainter, QPen
from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QDoubleSpinBox, QDial,
    QPushButton, QLabel, QTableWidget, QTableWidgetItem, QMessageBox)
from qgis.core import (QgsGeometry, QgsPointXY, QgsCoordinateTransform, QgsProject,
    QgsVectorLayer, QgsFeature, QgsWkbTypes, QgsRectangle, QgsRuleBasedRenderer)
from qgis.gui import QgsMapTool, QgsRubberBand, QgsVertexMarker
from .result_highlight import ResultHighlight
from ..services.direction_math import normalize, bearing, to_storage, to_bearing, ANGLE_CRS
from qgis.core import QgsCoordinateReferenceSystem


class CadDial(QDial):
    """A full-circle dial whose visual and mouse axes match stored CAD angles."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(120, 120)
        self.setSingleStep(100)
        self.setPageStep(1500)
        self._dragging = False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = self.rect().center()
        radius = max(10, min(self.width(), self.height()) / 2 - 34)
        painter.setPen(QPen(self.palette().text().color(), 1))
        painter.drawEllipse(center, int(radius), int(radius))
        for degrees, label in ((0,'E 0'),(90,'N 90'),(180,'W 180'),(270,'S 270')):
            a = math.radians(degrees)
            x, y = center.x()+(radius+13)*math.cos(a), center.y()-(radius+13)*math.sin(a)
            painter.drawText(int(x)-20, int(y)-8, 40, 16, Qt.AlignmentFlag.AlignCenter, label)
        angle = math.radians(self.value()/100)
        from qgis.PyQt.QtCore import QPointF
        end = QPointF(center.x()+radius*math.cos(angle), center.y()-radius*math.sin(angle))
        painter.setPen(QPen(QColor('#1976d2'), 3))
        painter.drawLine(QPointF(center), end)
        painter.drawEllipse(end, 4, 4)

    def _pick(self, event):
        center = self.rect().center()
        dx, dy = event.pos().x()-center.x(), center.y()-event.pos().y()
        if dx or dy:
            self.setValue(round(normalize(math.degrees(math.atan2(dy, dx)))*100) % 36000)

    def mousePressEvent(self, event):
        self._dragging = event.button() == Qt.MouseButton.LeftButton
        if self._dragging: self._pick(event)

    def mouseMoveEvent(self, event):
        if self._dragging: self._pick(event)

    def mouseReleaseEvent(self, event):
        if self._dragging: self._pick(event)
        self._dragging = False


class RotationTool(QgsMapTool):
    def __init__(self, canvas, layer, feature, config, changed):
        super().__init__(canvas)
        self.layer, self.config, self.changed = layer, config, changed
        self.center = QgsCoordinateTransform(layer.crs(), canvas.mapSettings().destinationCrs(),
                                             QgsProject.instance()).transform(feature.geometry().asPoint())
        self.cad_to_map = QgsCoordinateTransform(QgsCoordinateReferenceSystem(ANGLE_CRS),
            canvas.mapSettings().destinationCrs(), QgsProject.instance())
        self.map_to_cad = QgsCoordinateTransform(canvas.mapSettings().destinationCrs(),
            QgsCoordinateReferenceSystem(ANGLE_CRS), QgsProject.instance())
        self.cad_center = self.map_to_cad.transform(self.center)
        self.band = QgsRubberBand(canvas, QgsWkbTypes.GeometryType.LineGeometry)
        self.band.setColor(QColor('#1976d2'))
        self.band.setWidth(3)
        self.dragging = False
        self.handle = QgsVertexMarker(canvas)
        self.handle.setIconType(QgsVertexMarker.ICON_CIRCLE)
        self.handle.setIconSize(12)
        self.handle.setColor(QColor('#1976d2'))

    def preview(self, value):
        angle = math.radians(to_bearing(value, self.config))
        length = self.canvas().mapUnitsPerPixel()*65
        probe = self.cad_to_map.transform(QgsPointXY(self.cad_center.x()+math.sin(angle),
                                                    self.cad_center.y()+math.cos(angle)))
        dx, dy = probe.x()-self.center.x(), probe.y()-self.center.y()
        scale = length / math.hypot(dx, dy)
        end = QgsPointXY(self.center.x()+dx*scale, self.center.y()+dy*scale)
        self.band.setToGeometry(QgsGeometry.fromPolylineXY([self.center,end]), None)
        self.handle.setCenter(end)
        self.end = end

    def canvasPressEvent(self, event):
        end = self.toCanvasCoordinates(self.end)
        self.dragging = (event.button() == Qt.MouseButton.LeftButton
                         and (event.pos()-end).manhattanLength() <= 20)
        if self.dragging:
            self.canvasMoveEvent(event)

    def canvasMoveEvent(self, event):
        if self.dragging:
            point = event.mapPoint()
            if point != self.center:
                point = self.map_to_cad.transform(point)
                self.changed(to_storage(bearing((self.cad_center.x(),self.cad_center.y()), (point.x(),point.y())), self.config))

    def canvasReleaseEvent(self, event):
        self.dragging = False

    def dispose(self):
        self.canvas().scene().removeItem(self.band)
        self.canvas().scene().removeItem(self.handle)


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
        self.dial = CadDial(self); self.dial.setRange(0,35999); self.dial.setWrapping(True)
        layout.addWidget(self.spin); layout.addWidget(self.dial)
        self.note = QLabel('미리보기는 서버와 편집 버퍼를 변경하지 않습니다.',self)
        layout.addWidget(self.note)
        actions = QHBoxLayout(); layout.addLayout(actions)
        for label, callback in (('180° 반전', self.flip), ('적용', self.apply), ('취소',self.reject)):
            button = QPushButton(label,self); button.clicked.connect(callback); actions.addWidget(button)
            if label == '180° 반전': button.setEnabled(self.config['allow_reverse'])
        self.canvas = controller.plugin.mapCanvas
        self.previous_tool = self.canvas.mapTool()
        feature = layer.getFeature(self.fid)
        self.tool = RotationTool(self.canvas, layer, feature, self.config, self.set_value)
        # An unregistered memory layer is visible only in this canvas during preview.
        self.overlay = QgsVectorLayer('Point?crs='+layer.crs().authid(), 'GeoFlow 방향 미리보기','memory')
        self.overlay.setCrs(layer.crs())
        self.overlay.dataProvider().addAttributes(list(layer.fields())); self.overlay.updateFields()
        self.preview_feature = QgsFeature(feature)
        self.overlay.dataProvider().addFeature(self.preview_feature)
        self.overlay.setRenderer(layer.renderer().clone())
        self.overlay.setCustomProperty('geoflow/definition_layer_id',layer.customProperty('geoflow/definition_layer_id',''))
        self.service.bind_renderer(self.overlay)
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
        self.spin.valueChanged.connect(self.set_value)
        self.dial.valueChanged.connect(lambda value:self.set_value(value/100))
        self.connections = [(controller.plugin.iface.currentLayerChanged,self.reject),
                            (layer.selectionChanged,self.selection_changed),
                            (self.canvas.mapToolSet,self.tool_changed),
                            (QgsProject.instance().cleared,self.reject)]
        for signal, slot in self.connections: signal.connect(slot)
        self.finished.connect(self.cleanup)
        old = page.form.values().get(self.field['id'])
        try: value = float(old)
        except (ValueError,TypeError): value = 0
        self.set_value(value)

    def set_value(self, value):
        value = self.service.storage_value(self.layer, self.field, value)
        with QSignalBlocker(self.spin), QSignalBlocker(self.dial):
            self.spin.setValue(value); self.dial.setValue(round(value*100)%36000)
        index = self.overlay.fields().indexFromName(self.field['storage']['key'])
        self.overlay.dataProvider().changeAttributeValues({self.preview_feature.id():{index:value}})
        self.overlay.triggerRepaint(); self.tool.preview(value)

    def flip(self): self.set_value(self.spin.value()+180)

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
        self.tool.dispose(); self.tool.deleteLater(); self.canvas.refresh()


class DirectionResults(QDialog):
    LABELS = {'ok':'계산 가능','no_reference':'기준선 없음','ambiguous':'후보 모호',
              'no_config':'설정 없음','error':'기하 또는 필드 오류'}
    def __init__(self, controller, layer, features, page=None):
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
        layout.addWidget(self.table)
        single = len(features)==1
        for feature in features:
            result = controller.direction.inspect(layer,feature)
            candidates = result['candidates'] if single and result['status']=='ambiguous' else [None]
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
        self.note = QLabel('EPSG:5186 · 동쪽 0°·반시계방향. 단일 계산은 후보 하나를 선택하고, 일괄 계산의 모호한 후보는 검토하세요.')
        layout.addWidget(self.note)
        button = QPushButton('선택 적용',self); button.clicked.connect(self.apply); layout.addWidget(button)
        changed = QPushButton('변경 객체 전체 보기',self)
        changed.clicked.connect(lambda:self.highlight.show(self.layer,self.changed_rows,zoom=True))
        layout.addWidget(changed)
        clear = QPushButton('강조 해제',self); clear.clicked.connect(self.highlight.clear); layout.addWidget(clear)
        close = QPushButton('닫기',self); close.clicked.connect(self.reject); layout.addWidget(close)
        self.finished.connect(self.cleanup)
        self.resize(850,400)

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
