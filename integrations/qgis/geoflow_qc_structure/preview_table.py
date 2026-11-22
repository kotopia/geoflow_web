"""Object rows with a frozen feature-ID header and cell-level provenance."""
import json
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QAbstractItemView, QTableWidget, QTableWidgetItem


def display(value):
    if value is None:
        return 'NULL'
    if value == '':
        return '""'
    return str(value)


class ObjectTable(QTableWidget):
    def __init__(self):
        super().__init__(0, 0)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.ids = []
        self.details = {}

    def populate(self, output, fields, changes, findings, spatial, only_errors=False):
        errors = {(f.feature_id, f.field) for f in findings if f.severity == 'ERROR'}
        errors.update((r[0], r[1]) for r in changes if r[-1].startswith('ERROR'))
        by_cell = {(r[0], r[1]): r for r in changes}
        selected = [r for r in output if not only_errors or any(fid == r[0] for fid, _ in errors)]
        names = [f['physical_name'] for f in fields]
        self.clear()
        self.setColumnCount(len(names))
        self.setHorizontalHeaderLabels(names)
        self.setRowCount(len(selected))
        self.ids = [r[0] for r in selected]
        # The vertical header is a permanently frozen identifier column, independent of horizontal scrolling.
        self.setVerticalHeaderLabels([f'FID {fid}' for fid in self.ids])
        self.verticalHeader().setToolTip('입력 객체 식별자 · 가로 스크롤 시 고정')
        self.details = {}
        for i, (fid, attrs, _) in enumerate(selected):
            for j, name in enumerate(names):
                change = by_cell.get((fid, name))
                related = [f for f in findings if f.feature_id == fid and f.field in (None, name)]
                item = QTableWidgetItem(display(attrs.get(name)))
                error = (fid, name) in errors or (fid, None) in errors
                if error:
                    item.setBackground(QColor('#ffd6d6'))
                elif change and change[-1] == 'READY':
                    item.setBackground(QColor('#fff1b8'))
                parts = [f'FID: {fid} / {name}']
                if change:
                    parts += [f'원본: {display(change[2])}', f'계산 결과: {display(change[3])}',
                              f'Operation: {change[4]} / Rule: {change[5]}', f'상태: {change[6]}']
                parts += [f'QC {f.severity}: {f.message}' for f in related]
                for group in spatial.aggregates.values():
                    for result in group.values():
                        if result['target_id'] == fid:
                            parts.append(json.dumps(result, ensure_ascii=False, indent=2, default=str))
                detail = '\n'.join(parts)
                item.setToolTip(detail)
                self.details[i, j] = detail
                self.setItem(i, j, item)
        self.resizeColumnsToContents()


def dependency_snapshot(project, profile, directory):
    """Detect even reference changes that coincidentally produce the same answer."""
    import hashlib
    from pathlib import Path
    from .ui_values import scalar
    ids = set()
    for rule in list(profile.get('field_rules', {}).values()) + list(profile.get('qc_rules', {}).values()):
        lid = rule.get('params', {}).get('reference_layer')
        if lid:
            ids.add(lid)
    snapshots = []
    for lid in sorted(ids):
        layer = project.mapLayer(lid)
        if layer is None:
            raise ValueError('참조 레이어가 제거되었습니다. Preview를 다시 실행하세요.')
        rows = sorted((f.id(), [scalar(v) for v in f.attributes()], bytes(f.geometry().asWkb()).hex()) for f in layer.getFeatures())
        state = [lid, layer.crs().toWkt(), layer.subsetString(), sorted(layer.selectedFeatureIds()),
                 [(f.name(), f.typeName(), f.length(), f.precision()) for f in layer.fields()], rows]
        snapshots.append(hashlib.sha256(json.dumps(state, default=str, ensure_ascii=False).encode()).hexdigest())
    paths = list(Path(directory).glob('codebooks/*.json')) + list(Path(directory).glob('profiles/*.json'))
    if (Path(directory) / 'fields.json').exists():
        paths.append(Path(directory) / 'fields.json')
    for path in sorted(paths):
        snapshots.append((str(path.relative_to(directory)), hashlib.sha256(path.read_bytes()).hexdigest()))
    return snapshots
