"""Explicit code conversion and shared numeric reference aggregation forms."""
import json
from copy import deepcopy
from qgis.PyQt.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
                                QLineEdit, QWidget)
from qgis.core import QgsProject, QgsVectorLayer
from .references import CodeBooks, validate_book


class ReferenceSettings(QWidget):
    def __init__(self, parent, params, directory):
        super().__init__(parent)
        form = QFormLayout(self)
        self.book = QComboBox()
        books = CodeBooks(directory).revisions()
        if params.get('book') and params['book'] not in books:
            books.append(params['book'])
        for book in books:
            self.book.addItem(f"{book['agency']} / {book['business']} / {book['kind']} / {book['id']} r{book['revision']} / {book['mapping_id']}", book)
        if params.get('book'):
            self.book.setCurrentIndex(next(i for i, b in enumerate(books) if b == params['book']))
        self.policy = QComboBox()
        for label, value in [('오류 처리', 'error'), ('원본 유지', 'keep'), ('NULL', 'null'), ('지정값', 'value')]:
            self.policy.addItem(label, value)
        self.policy.setCurrentIndex(self.policy.findData(params.get('unregistered', 'error')))
        self.value = QLineEdit(json.dumps(params.get('unregistered_value'), ensure_ascii=False))
        self.trim, self.casefold = QCheckBox('앞뒤 공백 제거'), QCheckBox('대소문자 무시')
        self.trim.setChecked(params.get('trim', False))
        self.casefold.setChecked(params.get('casefold', False))
        for label, control in [('출력 코드표·리비전·입력 대응표', self.book), ('미등록값', self.policy),
                               ('지정값 (JSON)', self.value), ('정규화', self.trim), ('', self.casefold)]:
            form.addRow(label, control)

    def parameters(self, source):
        book = self.book.currentData()
        if not book:
            raise ValueError('참조코드 관리에서 코드표를 등록하세요.')
        validate_book(book, self.trim.isChecked(), self.casefold.isChecked())
        return dict(source_field=source, book=deepcopy(book), unregistered=self.policy.currentData(),
                    unregistered_value=json.loads(self.value.text()), trim=self.trim.isChecked(), casefold=self.casefold.isChecked())


class AggregateSettings(QWidget):
    def __init__(self, parent, params):
        super().__init__(parent)
        form = QFormLayout(self)
        self.layers, self.field = QComboBox(), QComboBox()
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and layer.isValid() and layer.isSpatial():
                self.layers.addItem(f'{layer.name()} · {layer.id()}', layer.id())
        self.layers.setCurrentIndex(self.layers.findData(params.get('reference_layer', '')))
        self.layers.currentIndexChanged.connect(self.refresh_fields)
        self.refresh_fields()
        self.field.setCurrentIndex(self.field.findText(params.get('reference_field', '')))
        self.radius = QDoubleSpinBox()
        self.radius.setDecimals(4)
        self.radius.setRange(0, 1000000)
        self.radius.setValue(params.get('radius', 0))
        self.scope, self.policy, self.unit, self.stat = QComboBox(), QComboBox(), QComboBox(), QComboBox()
        for label, value in [('레이어 전체 (현재 subset 적용)', 'all'), ('현재 선택된 심도 객체', 'selected')]:
            self.scope.addItem(label, value)
        for label, value in [('단일 관로만 허용', 'unique'), ('유일한 최근접 관로 (동률 오류)', 'nearest')]:
            self.policy.addItem(label, value)
        for label, value in [('심도 수치 산술평균', 'mean'), ('심도 수치 최솟값', 'minimum'), ('심도 수치 최댓값', 'maximum')]:
            self.stat.addItem(label, value)
        self.unit.addItems(['m', 'cm', 'mm'])
        self.unit.setCurrentText(params.get('unit', 'm'))
        for control, key, default in [(self.scope, 'scope', 'all'), (self.policy, 'selection_policy', 'unique'), (self.stat, 'statistic', 'mean')]:
            control.setCurrentIndex(control.findData(params.get(key, default)))
        self.filter = QLineEdit(json.dumps(params.get('candidate_filter', {}), ensure_ascii=False))
        self.target_filter = QLineEdit(json.dumps(params.get('target_filter', {}), ensure_ascii=False))
        for label, control in [('저장 심도 원본 레이어', self.layers), ('저장 숫자 필드', self.field),
                               ('허용거리 (m)', self.radius), ('원본 범위', self.scope), ('후보 선정 정책', self.policy),
                               ('심도 원본·출력 단위 (변환 없음)', self.unit), ('집계', self.stat),
                               ('심도 필드=값 조건 (JSON)', self.filter), ('관로 필드=값 조건 (JSON)', self.target_filter)]:
            form.addRow(label, control)

    def refresh_fields(self):
        self.field.clear()
        layer = QgsProject.instance().mapLayer(self.layers.currentData() or '')
        if layer:
            self.field.addItems([f.name() for f in layer.fields() if f.isNumeric()])

    def parameters(self, crs):
        layer = QgsProject.instance().mapLayer(self.layers.currentData() or '')
        if layer is None:
            raise ValueError('저장 심도 원본 레이어를 지정하세요.')
        import hashlib
        binding = dict(definition_layer_id=str(layer.customProperty('geoflow/definition_layer_id', '')),
                       provider=layer.providerType(), source_sha256=hashlib.sha256(layer.source().encode()).hexdigest())
        return dict(reference_layer=self.layers.currentData(), reference_field=self.field.currentText(), crs=crs, reference_binding=binding,
                    radius=self.radius.value(), scope=self.scope.currentData(), selection_policy=self.policy.currentData(),
                    statistic=self.stat.currentData(), unit=self.unit.currentText(), candidate_filter=json.loads(self.filter.text()),
                    target_filter=json.loads(self.target_filter.text()))
