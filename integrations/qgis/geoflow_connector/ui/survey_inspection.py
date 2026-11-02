"""Read-only Survey details and canvas navigation; never select/edit a layer."""
import json
import math

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (QApplication, QAbstractItemView, QDialog,
    QHBoxLayout, QVBoxLayout, QPushButton, QPlainTextEdit, QListWidget, QLabel)
from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsGeometry, QgsPointXY, QgsProject, QgsRectangle, QgsUnitTypes)
from .result_highlight import ResultHighlight

from ..services.survey_spatial import nearby_targets, overlap_distance_m, value
from ..services.settings import GeoFlowSettingsService


def finite_pair(x, y):
    if x is None or y is None or isinstance(x, bool) or isinstance(y, bool):
        return None
    try:
        pair = float(x), float(y)
        return pair if all(math.isfinite(v) for v in pair) else None
    except (ValueError, TypeError):
        return None


def location(row):
    """Canonical geometry first. Raw ordinates are deliberately not substituted."""
    pair = finite_pair(row.get('longitude'), row.get('latitude'))
    if pair and -180 <= pair[0] <= 180 and -90 <= pair[1] <= 90:
        return QgsGeometry.fromPointXY(QgsPointXY(*pair)), QgsCoordinateReferenceSystem('EPSG:4326')
    geom = row.get('geom') or row.get('geometry')
    crs = QgsCoordinateReferenceSystem(str(row.get('geometry_crs') or ''))
    if geom and crs.isValid():
        g = QgsGeometry.fromJson(json.dumps(geom).encode()) if isinstance(geom, dict) else QgsGeometry.fromWkt(str(geom))
        if not g.isNull() and not g.isEmpty() and all(math.isfinite(v) for p in g.vertices() for v in (p.x(), p.y())):
            return g, crs
    pair = finite_pair(row.get('x'), row.get('y'))
    crs = QgsCoordinateReferenceSystem(str(row.get('current_crs') or ''))
    if pair and crs.isValid():
        return QgsGeometry.fromPointXY(QgsPointXY(*pair)), crs
    raise ValueError('좌표 없음 또는 현재 좌표의 CRS 미확인 (원시 좌표는 현재 위치로 대체하지 않음)')


def detail(row, sources):
    source = next((r for r in sources if str(r.get('id')) == str(row.get('source_id'))), {})
    filename = row.get('original_file_name') or source.get('original_file_name')
    if row.get('source_state') == 'deleted':
        filename = (filename + ' · ' if filename else '') + '원본 삭제됨'
    try:
        geom, crs = location(row)
        available = f'가능 · {geom.asWkt(6)} · {crs.authid()}'
    except ValueError as exc:
        available = str(exc)
    fmt = lambda k: '좌표 없음' if row.get(k) is None else str(row[k])
    return '\n'.join([
        f"측량번호: {row.get('survey_no') or '번호 없음'} · 원본 행: {row.get('source_row_id') or '미확인'}",
        f"Survey UUID: {row.get('id', '')}",
        f"원본: {filename or '출처 미확인'} · Source UUID: {row.get('source_id') or '없음'}",
        f"측량일: {row.get('survey_date') or '미확인'} · 코드: {row.get('code') or row.get('raw_code') or '미확인'}",
        f"현재 X/Y/Z: {fmt('x')} / {fmt('y')} / {fmt('z')} · CRS: {row.get('current_crs') or '미확인'}",
        f"원시 X/Y/Z: {fmt('raw_x')} / {fmt('raw_y')} / {fmt('raw_z')} · CRS: {row.get('raw_crs') or '미확인'}",
        '보정 상태: 응답에 명시되지 않음', f'위치 확인: {available}'])


class SurveyInspection:
    def __init__(self, panel):
        self.panel = panel
        self.highlight = ResultHighlight(panel.plugin.iface.mapCanvas())
        self.bands = self.highlight.bands
        self.timer = QTimer(panel)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.clear)
        panel.finished.connect(self.clear)
        self.details = {}
        for table in (panel.pointsTable, panel.featureTable):
            table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            box = QPlainTextEdit(table.parentWidget())
            box.setReadOnly(True)
            box.setMaximumHeight(140)
            self.details[table] = box
            layout = table.parentWidget().layout()
            layout.insertWidget(layout.indexOf(table) + 1, box)
            actions = QHBoxLayout()
            for label, callback in (
                ('지도에서 보기', lambda _=False, t=table: self.show(self.selected(t))),
                ('Source 전체 보기', lambda: self.show(panel.point_rows, entire=True)),
                ('UUID 복사', lambda _=False, t=table: QApplication.clipboard().setText('\n'.join(str(r['id']) for r in self.selected(t)))),
                ('중복 위치 비교', lambda _=False, t=table: self.compare(t)),
                ('삭제 이력', self.history)):
                button = QPushButton(label, panel)
                button.clicked.connect(callback)
                actions.addWidget(button)
            layout.insertLayout(layout.indexOf(box), actions)
            table.itemSelectionChanged.connect(lambda t=table: self.update(t))
            table.cellDoubleClicked.connect(lambda _r, _c, t=table: self.show(self.selected(t)))

    def selected(self, table):
        return [table.item(i.row(), 1).data(Qt.ItemDataRole.UserRole)
                for i in table.selectionModel().selectedRows() if table.item(i.row(), 1)]

    def update(self, table):
        rows = self.selected(table)
        self.details[table].setPlainText('\n\n'.join(detail(r, self.panel.source_rows) for r in rows))

    def clear(self, *_):
        self.timer.stop()
        self.highlight.clear()

    def show(self, rows, entire=False, extra=()):
        canvas = self.panel.plugin.iface.mapCanvas()
        destination = canvas.mapSettings().destinationCrs()
        geometries, missing = [], 0
        for row in rows:
            try:
                geometries.append(location(row))
            except ValueError:
                missing += 1
        geometries.extend(extra)
        converted = []
        try:
            for geom, crs in geometries:
                transformed = QgsGeometry(geom)
                transformed.transform(QgsCoordinateTransform(crs, destination, QgsProject.instance()))
                if any(not math.isfinite(v) for p in transformed.vertices() for v in (p.x(), p.y())):
                    raise ValueError('좌표 변환 결과가 유효하지 않습니다.')
                converted.append(transformed)
        except Exception as exc:
            self.panel.statusLabel.setText(f'지도 이동 불가: {exc}')
            return
        if not converted:
            self.panel.statusLabel.setText('위치 확인 가능한 좌표 없음 · 선택 행을 확인하세요.')
            return
        extent = QgsRectangle(converted[0].boundingBox())
        for geom in converted[1:]:
            extent.combineExtentWith(geom.boundingBox())
        # Minimum visible span: 20 m in projected units, small explicit angular span otherwise.
        minimum = (0.0002 if destination.isGeographic() else
                   20 * QgsUnitTypes.fromUnitToUnitFactor(QgsUnitTypes.DistanceUnit.Meters, destination.mapUnits()))
        centre = extent.center()
        width, height = max(extent.width()*1.2, minimum), max(extent.height()*1.2, minimum)
        self.clear()
        for geom in converted:
            self.highlight.add(geom,destination,'review')
        canvas.setExtent(QgsRectangle(centre.x()-width/2, centre.y()-height/2, centre.x()+width/2, centre.y()+height/2))
        canvas.refresh()
        self.timer.start(5000)
        self.panel.statusLabel.setText(f'위치 {len(converted)}점 · 좌표 미확인 {missing}점'
            + (' · 조회 불완전: 전체 Source 범위 아님' if entire and getattr(self.panel, '_inventory_incomplete', False) else ''))

    def history(self):
        dialog = QDialog(self.panel)
        dialog.setWindowTitle('Source 삭제 이력 (현재 보존 측점 수와 별개)')
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit(dialog)
        text.setReadOnly(True)
        rows = getattr(self.panel, '_source_history', [])
        lines = [f"{r.get('original_file_name')} | {r['id']} | 삭제 {r.get('deleted_at')} | {r.get('delete_reason')} | 활성 {r.get('point_count')}점 / 논리 삭제 {r.get('deleted_point_count')}점" for r in rows]
        lines.insert(0, f'서버 삭제 이력 · Source {len(rows)}건' if getattr(self.panel, '_history_supported', False)
                     else '현재 서버는 삭제 이력 목록을 제공하지 않습니다. 아래 PC 기록은 전체 서버 이력이 아닙니다.')
        lines.append('이 PC의 과거 삭제 Source ID (현재 상태의 근거 아님):\n' + '\n'.join(sorted(self.panel._deleted_source_ids())))
        text.setPlainText('\n'.join(lines))
        layout.addWidget(text)
        dialog.resize(800, 350)
        dialog.show()

    def compare(self, table, rows=None):
        panel = self.panel
        selected = self.selected(table) if rows is None else rows
        candidates = [panel.featureTable.item(i, 1).data(Qt.ItemDataRole.UserRole)
                      for i in range(panel.featureTable.rowCount())
                      if panel.featureTable.item(i, 0).checkState() == Qt.CheckState.Checked]
        pairs, seen = [], set()
        radius = GeoFlowSettingsService(panel.plugin).get_default_nearby_radius()
        def targets(point):
            mapping = panel._point_mapping(point)
            standard = str(mapping.get('layer') or '').upper()
            code = panel._display_storage_code(mapping)
            result = {(standard, code)} if standard and code else set()
            if (panel._creation_mode() == panel.CREATE_FACILITY_WITH_DEPTH
                    and standard != 'WTL_PIPE_PS' and (standard, code) in panel._depth_create_targets()):
                result.add(('WTL_PIPE_PS', panel._depth_storage_code()))
            return result
        for first in selected:
            planned = targets(first)
            if not planned or not panel._valid_point_coordinates(first):
                continue
            for other in candidates:
                key = tuple(sorted((str(first['id']), str(other['id']))))
                if first['id'] == other['id'] or key in seen or not panel._valid_point_coordinates(other):
                    continue
                shared = planned & targets(other)
                if not shared:
                    continue
                metres = overlap_distance_m(panel.plugin, first, other)
                if metres is not None:
                    seen.add(key)
                    pairs.append((first, other, None, f"배치 내부 {first.get('survey_no') or first.get('source_row_id')} ↔ {other.get('survey_no') or other.get('source_row_id')} · {sorted(shared)} · {metres:.3f}m / 반경 {radius:.3f}m"))
            for layer in panel.plugin._managed_layers():
                standard = str(layer.customProperty('geoflow/standard_name', '')).upper()
                codes = [code for name, code in planned if name == standard]
                if not codes:
                    continue
                code = codes[0]
                for match in nearby_targets(panel.plugin, first, layer, code):
                    feature = match['feature']
                    uid = value(feature, 'id')
                    if uid:
                        pairs.append((first, None, (layer.id(), str(uid)), f"기존 GIS {first.get('survey_no') or first.get('source_row_id')} ↔ {uid} · {standard}/{code} · {match.get('distance_m', match.get('distance', '미확인'))}m / 반경 {radius:.3f}m"))
        dialog = QDialog(panel)
        dialog.setWindowTitle('중복 위치 비교 · 생성 체크는 직접 조정하세요')
        layout = QVBoxLayout(dialog)
        listing = QListWidget(dialog)
        listing.addItems([p[3] for p in pairs])
        layout.addWidget(listing)
        layout.addWidget(QLabel('배치 후보는 현재 조회 목록 기준입니다. 실제 생성 preflight의 기준·반경은 유지됩니다.', dialog))
        buttons = QHBoxLayout()
        def navigate(mode):
            index = listing.currentRow()
            if index < 0 or index >= len(pairs):
                return
            first, other, target, _ = pairs[index]
            rows = [first] if mode != 'other' else []
            extra = []
            if mode != 'first':
                if other:
                    rows.append(other)
                elif target:
                    layer = QgsProject.instance().mapLayer(target[0])
                    if layer:
                        matches = [f for f in layer.getFeatures() if str(value(f, 'id')) == target[1]]
                        if len(matches) == 1:
                            extra.append((matches[0].geometry(), layer.crs()))
                    if not extra:
                        panel.statusLabel.setText('상대 GIS 객체 UUID를 현재 레이어에서 확인할 수 없습니다.')
                        return
            self.show(rows, extra=extra)
        for label, mode in [('해당 측점 보기', 'first'), ('상대 보기', 'other'), ('두 점 함께 보기', 'both')]:
            button = QPushButton(label, dialog)
            button.clicked.connect(lambda _=False, m=mode: navigate(m))
            buttons.addWidget(button)
        layout.addLayout(buttons)
        if not pairs:
            listing.addItem('선택 측점의 중복 후보 없음 (조회 범위 내)')
        elif pairs:
            listing.setCurrentRow(0)
        dialog.resize(900, 320)
        self.comparison_dialog = dialog
        self.comparison_pairs = pairs
        dialog.show()
