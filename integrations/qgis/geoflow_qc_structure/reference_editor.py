"""Local code-book editor and explicit Excel column import preview (GDAL/OGR)."""
import json
from qgis.PyQt.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)
from .references import CodeBooks, import_rows, validate_book


class ReferenceEditor(QDialog):
    def __init__(self, parent, directory):
        super().__init__(parent)
        self.store = CodeBooks(directory)
        self.setWindowTitle('참조코드 관리 · 새 리비전 저장')
        self.resize(850, 600)
        layout = QVBoxLayout(self)
        self.books = QComboBox()
        layout.addWidget(self.books)
        form = QFormLayout()
        layout.addLayout(form)
        self.controls = {}
        for key, label in [('id', '코드표 ID'), ('agency', '발주처'), ('business', '업무'),
                           ('kind', '코드 종류'), ('mapping_id', '입력값 대응표 ID')]:
            self.controls[key] = QLineEdit()
            form.addRow(label, self.controls[key])
        layout.addWidget(QLabel('별칭은 JSON 배열로 입력합니다. 예: ["PE", "Poly"] · NULL 별칭은 [null]\n'
                               '문자열 유사도로 연결하지 않습니다. Excel 가져오기 후 표를 확인하고 저장하세요.'))
        self.grid = QTableWidget(0, 4)
        self.grid.setHorizontalHeaderLabels(['출력 코드', '명칭', '공통 의미 / 안정 ID', '입력값·별칭 (JSON 배열)'])
        layout.addWidget(self.grid)
        bar = QHBoxLayout()
        layout.addLayout(bar)
        for label, callback in [('행 추가', self.add), ('행 삭제', self.remove), ('Excel 가져오기', self.import_excel),
                                ('검증', self.validate), ('새 리비전 저장', self.save)]:
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, cb=callback: self.call(cb))
            bar.addWidget(button)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.books.currentIndexChanged.connect(self.load)
        self.reload()

    def call(self, callback):
        try:
            callback()
        except Exception as exc:
            self.message.setText(str(exc))
            QMessageBox.warning(self, '참조코드', str(exc))

    def reload(self):
        self.books.blockSignals(True)
        self.books.clear()
        self.books.addItem('새 코드표', None)
        for book in self.store.revisions():
            self.books.addItem(f"{book['agency']} / {book['business']} / {book['kind']} / {book['id']} r{book['revision']} / {book['mapping_id']}", book)
        self.books.blockSignals(False)

    def load(self):
        book = self.books.currentData() or {}
        for key, control in self.controls.items():
            control.setText(book.get(key, ''))
        self.populate(book.get('entries', []))

    def populate(self, entries):
        self.grid.setRowCount(0)
        for entry in entries:
            row = self.grid.rowCount()
            self.grid.insertRow(row)
            for col, key in enumerate(('code', 'name', 'meaning', 'aliases')):
                value = json.dumps(entry[key], ensure_ascii=False) if key == 'aliases' else entry[key]
                self.grid.setItem(row, col, QTableWidgetItem(value))
        self.grid.resizeColumnsToContents()

    def add(self):
        row = self.grid.rowCount()
        self.grid.insertRow(row)
        self.grid.setItem(row, 3, QTableWidgetItem('[]'))

    def remove(self):
        if self.grid.currentRow() >= 0:
            self.grid.removeRow(self.grid.currentRow())

    def book(self):
        result = {key: control.text().strip() for key, control in self.controls.items()}
        result['entries'] = []
        for row in range(self.grid.rowCount()):
            values = [self.grid.item(row, c).text() if self.grid.item(row, c) else '' for c in range(4)]
            result['entries'].append(dict(code=values[0], name=values[1], meaning=values[2], aliases=json.loads(values[3])))
        return result

    def validate(self):
        book = self.book()
        validate_book(book)
        self.message.setText(f"검증 통과 · {len(book['entries'])}개 · 저장 전 가져오기 결과를 검토하세요.")
        return book

    def save(self):
        book = self.store.save(self.validate())
        self.reload()
        self.message.setText(f"{book['id']} r{book['revision']} 저장됨 · 기존 Profile은 고정된 이전 리비전을 유지합니다.")

    def import_excel(self):
        from osgeo import gdal
        path, _ = QFileDialog.getOpenFileName(self, 'Excel 파일', '', 'Excel (*.xlsx *.xls)')
        if not path:
            return
        if path.lower().endswith('.xlsx'):
            dataset = gdal.OpenEx(path, gdal.OF_VECTOR | gdal.OF_READONLY, open_options=['HEADERS=FORCE', 'FIELD_TYPES=STRING'])
        else:
            # Thread-local options are restored; do not alter the user's global GDAL settings.
            with gdal.config_options({'OGR_XLS_HEADERS': 'FORCE', 'OGR_XLS_FIELD_TYPES': 'STRING'}):
                dataset = gdal.OpenEx(path, gdal.OF_VECTOR | gdal.OF_READONLY)
        if dataset is None:
            raise ValueError('현재 QGIS GDAL에서 읽을 수 없는 Excel 형식입니다. XLSX로 저장해 주세요.')
        names = [dataset.GetLayerByIndex(i).GetName() for i in range(dataset.GetLayerCount())]
        sheet, ok = QInputDialog.getItem(self, 'Excel 시트', '시트 선택', names, 0, False)
        if not ok:
            return
        layer = dataset.GetLayerByName(sheet)
        columns = [layer.GetLayerDefn().GetFieldDefn(i).GetName() for i in range(layer.GetLayerDefn().GetFieldCount())]
        dialog = QDialog(self)
        dialog.setWindowTitle('Excel 열 대응')
        layout = QFormLayout(dialog)
        controls = {}
        for key, label in [('code', '코드'), ('name', '명칭'), ('meaning', '공통 의미'), ('aliases', '별칭 JSON 배열')]:
            control = QComboBox()
            control.addItems(columns)
            controls[key] = control
            layout.addRow(label, control)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        mapping = {key: control.currentIndex() for key, control in controls.items()}
        if len(set(mapping.values())) != len(mapping):
            raise ValueError('각 의미에 서로 다른 열을 지정하세요.')
        entries = import_rows([[f.GetField(i) for i in range(len(columns))] for f in layer], mapping)
        self.populate(entries)
        self.message.setText('가져오기 미리보기 · 아직 저장되지 않았습니다. 중복·충돌·누락을 검증한 뒤 저장하세요.')
