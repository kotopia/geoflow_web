"""Form controls for one output field and its existing operation contract."""
import json
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal

from qgis.PyQt.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QSpinBox, QVBoxLayout, QScrollArea, QWidget,
)
from qgis.core import QgsCoordinateReferenceSystem
from qgis.gui import QgsProjectionSelectionWidget

from .catalog import TYPES, validate_field, validate_operation

METHODS = {
    "COPY": "원본 필드값 사용", "KEEP": "기존 값 유지",
    "CONSTANT": "직접 입력한 고정값", "LENGTH": "도형 길이 계산",
    "AREA": "도형 면적 계산", "ANGLE": "도형 방향각 계산",
    "CODE_MAP": "코드 변환", "START_REFERENCE": "시점 참조",
    "END_REFERENCE": "종점 참조", "SPATIAL_LOOKUP": "공간검색",
    "CONDITION": "조건별 값",
    "AGGREGATE": "저장 숫자 참조 집계 (심도)",
}


def constant_value(text, kind):
    if kind in {"SMALLINT", "INTEGER", "BIGINT"}:
        return int(text)
    if kind in {"NUMERIC", "DECIMAL"}:
        if not Decimal(text).is_finite():
            raise ValueError("유한한 숫자를 입력하세요.")
        return text
    if kind in {"REAL", "DOUBLE"}:
        value = json.loads(text)
        if type(value) not in {int, float}:
            raise ValueError("숫자를 입력하세요.")
        return value
    if kind == "BOOLEAN":
        if text.lower() not in {"true", "false"}:
            raise ValueError("BOOLEAN 값은 true 또는 false로 입력하세요.")
        return text.lower() == "true"
    # ISO strings are serialized in Profiles, then converted at execution time.
    if kind == "DATE":
        date.fromisoformat(text)
    if kind in {"DATETIME", "TIMESTAMP"}:
        datetime.fromisoformat(text)
    return text


class FieldEditor(QDialog):
    def __init__(self, parent, key, rule, field, source_names, operations):
        super().__init__(parent)
        self.setWindowTitle("출력 필드 설정")
        self.resize(560, 600)
        self.key, self.original_rule, self.original_field = key, deepcopy(rule), deepcopy(field)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        scroll.setWidget(content)
        outer.addWidget(scroll)
        layout = QVBoxLayout(content)
        form = QFormLayout()
        layout.addLayout(form)
        self.semantic = QLineEdit(key)
        self.semantic.setReadOnly(bool(key))
        self.display = QLineEdit(field.get("display_name", ""))
        self.target = QLineEdit(field.get("physical_name", ""))
        self.kind = QComboBox()
        self.kind.addItems(sorted(TYPES - {"GEOMETRY"}))
        self.kind.setCurrentText(field.get("data_type", "VARCHAR"))
        self.size, self.scale = QSpinBox(), QSpinBox()
        self.size.setRange(1, 2147483647)
        self.size.setValue(field.get("precision", field.get("length", 10)))
        self.scale.setRange(0, 1000)
        self.scale.setValue(field.get("scale", 0))
        self.nullable, self.required = QCheckBox(), QCheckBox()
        self.nullable.setChecked(field.get("nullable", True))
        self.required.setChecked(field.get("required", False))
        self.method, self.source = QComboBox(), QComboBox()
        for name in operations:
            self.method.addItem(METHODS.get(name, name), name)
        self.method.setCurrentIndex(self.method.findData(rule.get("operation", "CONSTANT")))
        self.source.setEditable(True)
        self.source.addItems(source_names)
        params = rule.get("params", {})
        self.source.setCurrentText(params.get("source_field", field.get("physical_name", "")))
        value = params.get("value", "")
        self.value = QLineEdit(json.dumps(value) if type(value) in {bool, int, float} else str(value))
        self.null_value = QCheckBox("고정값을 NULL로 생성")
        self.null_value.setChecked(value is None)
        self.crs = QgsProjectionSelectionWidget(self)
        self.crs.setCrs(QgsCoordinateReferenceSystem(params.get("crs", "")))
        self.unit = QComboBox()
        self.unit.addItems(["m", "km", "m2", "ha"])
        self.unit.setCurrentText(params.get("unit", "m"))
        self.parameters = QPlainTextEdit(json.dumps(params, ensure_ascii=False, indent=2))
        self.parameters.setMaximumHeight(120)
        for label, control in [
            ("기준 의미 ID", self.semantic), ("표시명", self.display),
            ("출력 필드명", self.target), ("자료형", self.kind),
            ("길이 / 전체 자릿수(precision)", self.size), ("소수 자릿수(scale)", self.scale),
            ("NULL 허용", self.nullable), ("필수값", self.required),
            ("값 생성 방법", self.method), ("입력 레이어의 원본 필드", self.source),
            ("직접 입력값", self.value), ("", self.null_value),
            ("계산 좌표계 · 미터 단위 투영", self.crs), ("계산 단위", self.unit),
            ("참조·코드·조건 연산 매개변수", self.parameters),
        ]:
            form.addRow(label, control)
        from .operation_editor import ReferenceSettings, AggregateSettings
        from qgis.core import QgsApplication
        from pathlib import Path
        directory = getattr(getattr(parent, 'provider', None), 'directory', Path(QgsApplication.qgisSettingsDirPath()) / 'geoflow_qc_structure')
        self.code_settings = ReferenceSettings(self, params, directory)
        self.aggregate_settings = AggregateSettings(self, params)
        layout.addWidget(self.code_settings)
        layout.addWidget(self.aggregate_settings)
        layout.addWidget(QLabel("출력 필드는 원본에 없어도 됩니다. 설정한 필드만 별도 결과 레이어에 생성합니다."))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.submit)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self.method.currentIndexChanged.connect(self.update_controls)
        self.kind.currentTextChanged.connect(self.update_controls)
        self.null_value.toggled.connect(self.update_controls)
        self.update_controls()

    def update_controls(self, *_):
        op, kind = self.method.currentData(), self.kind.currentText()
        self.source.setEnabled(op in {"COPY", "KEEP", "CODE_MAP"})
        self.code_settings.setVisible(op == "CODE_MAP")
        self.aggregate_settings.setVisible(op == "AGGREGATE")
        self.null_value.setEnabled(op == "CONSTANT")
        self.value.setEnabled(op == "CONSTANT" and not self.null_value.isChecked())
        self.crs.setEnabled(op in {"LENGTH", "AREA", "ANGLE", "AGGREGATE"})
        self.unit.setEnabled(op in {"LENGTH", "AREA"})
        self.parameters.setEnabled(op not in {"COPY", "KEEP", "CONSTANT", "LENGTH", "AREA", "CODE_MAP", "AGGREGATE"})
        self.size.setEnabled(kind in {"CHAR", "VARCHAR", "NUMERIC", "DECIMAL"})
        self.scale.setEnabled(kind in {"NUMERIC", "DECIMAL"})

    def submit(self):
        try:
            kind = self.kind.currentText()
            field = dict(self.original_field, semantic_key=self.semantic.text().strip(),
                         physical_name=self.target.text().strip(), display_name=self.display.text().strip(),
                         data_type=kind, nullable=self.nullable.isChecked(), required=self.required.isChecked())
            for key in ("length", "precision", "scale"):
                field.pop(key, None)
            if kind in {"CHAR", "VARCHAR"}:
                field["length"] = self.size.value()
            if kind in {"NUMERIC", "DECIMAL"}:
                field.update(precision=self.size.value(), scale=self.scale.value())
            validate_field(field)
            op = self.method.currentData()
            if op in {"COPY", "KEEP"}:
                params = {"source_field": self.source.currentText()}
            elif op == "CONSTANT":
                params = {"value": None if self.null_value.isChecked() else constant_value(self.value.text(), kind)}
            elif op in {"LENGTH", "AREA"}:
                params = {"crs": self.crs.crs().authid(), "unit": self.unit.currentText()}
            elif op == "CODE_MAP":
                params = self.code_settings.parameters(self.source.currentText())
            elif op == "AGGREGATE":
                params = self.aggregate_settings.parameters(self.crs.crs().authid())
            else:
                params = json.loads(self.parameters.toPlainText())
                if op == "ANGLE":
                    params["crs"] = self.crs.crs().authid()
            validate_operation(op, params)
            self.result_key = field["semantic_key"]
            self.result_rule = dict(self.original_rule, operation=op, params=params,
                                    target=field["physical_name"], field=field)
            self.accept()
        except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
            QMessageBox.warning(self, "출력 필드 설정", str(exc))
