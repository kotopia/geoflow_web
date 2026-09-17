"""Qt widget factory driven only by Final Form Definition metadata."""
from __future__ import annotations

from qgis.PyQt.QtCore import QDate, QDateTime
from qgis.PyQt.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDateTimeEdit, QDoubleSpinBox,
    QFileDialog, QHBoxLayout, QLineEdit, QPushButton, QSpinBox, QTextEdit,
    QWidget,
)


class WidgetHandle:
    def __init__(self, field, widget, *, editor=None):
        self.field = field
        self.widget = widget
        self.editor = editor or widget
        self._all_codes = list(field.get("reference_codes", []))

    def connect_changed(self, slot):
        widget = self.editor
        for name in ("textEdited", "textChanged", "valueChanged", "dateChanged",
                     "dateTimeChanged", "toggled", "currentIndexChanged"):
            signal = getattr(widget, name, None)
            if signal is not None:
                signal.connect(slot)
                return

    def set_readonly(self, value):
        value = bool(value)
        if hasattr(self.editor, "setReadOnly"):
            self.editor.setReadOnly(value)
        else:
            self.editor.setEnabled(not value)

    def set_value(self, value):
        widget = self.editor
        if isinstance(widget, QComboBox):
            index = widget.findData(None if value is None else str(value))
            widget.setCurrentIndex(index if index >= 0 else 0)
        elif isinstance(widget, QCheckBox):
            widget.setChecked(bool(value))
        elif isinstance(widget, QSpinBox):
            widget.setValue(int(value or 0))
        elif isinstance(widget, QDoubleSpinBox):
            widget.setValue(float(value or 0))
        elif isinstance(widget, QDateEdit):
            parsed = QDate.fromString(str(value or ""), "yyyy-MM-dd")
            widget.setDate(parsed if parsed.isValid() else widget.minimumDate())
        elif isinstance(widget, QDateTimeEdit):
            parsed = QDateTime.fromString(str(value or ""), "yyyy-MM-ddTHH:mm:ss")
            widget.setDateTime(parsed if parsed.isValid() else widget.minimumDateTime())
        elif isinstance(widget, (QLineEdit, QTextEdit)):
            setter = getattr(widget, "setPlainText", None) or widget.setText
            setter("" if value is None else str(value))

    def value(self):
        widget = self.editor
        if isinstance(widget, QComboBox):
            return widget.currentData()
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            return widget.value()
        if isinstance(widget, QDateEdit):
            if widget.date() == widget.minimumDate():
                return None
            return widget.date().toString("yyyy-MM-dd")
        if isinstance(widget, QDateTimeEdit):
            if widget.dateTime() == widget.minimumDateTime():
                return None
            return widget.dateTime().toString("yyyy-MM-ddTHH:mm:ss")
        if isinstance(widget, QTextEdit):
            return widget.toPlainText().strip() or None
        if isinstance(widget, QLineEdit):
            return widget.text().strip() or None
        return None

    def set_allowed_codes(self, allowed):
        if not isinstance(self.editor, QComboBox):
            return
        current = self.value()
        self.editor.blockSignals(True)
        try:
            self.editor.clear()
            self.editor.addItem("선택", None)
            for row in self._all_codes:
                if allowed is None or row["id"] in allowed:
                    self.editor.addItem(row["label"], row["value"])
            self.set_value(current)
        finally:
            self.editor.blockSignals(False)


def _photo_widget(parent):
    host = QWidget(parent)
    layout = QHBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    editor = QLineEdit(host)
    editor.setReadOnly(True)
    button = QPushButton("파일 선택", host)
    button.clicked.connect(lambda: editor.setText(QFileDialog.getOpenFileName(
        host, "사진 선택", "", "Images (*.png *.jpg *.jpeg *.webp)"
    )[0] or editor.text()))
    layout.addWidget(editor, 1)
    layout.addWidget(button)
    return host, editor


def create_widget(field: dict, parent=None) -> WidgetHandle:
    kind = field.get("widget_type") or field.get("semantic_data_type") or "text"
    codes = field.get("reference_codes", [])
    if kind in {"combo", "relation"} or codes:
        editor = QComboBox(parent)
        handle = WidgetHandle(field, editor)
        handle.set_allowed_codes(None)
    elif kind == "multiline":
        editor = QTextEdit(parent)
        editor.setMaximumHeight(96)
        handle = WidgetHandle(field, editor)
    elif kind == "integer":
        editor = QSpinBox(parent)
        editor.setRange(-2147483648, 2147483647)
        handle = WidgetHandle(field, editor)
    elif kind == "decimal":
        editor = QDoubleSpinBox(parent)
        editor.setDecimals(int(field.get("scale") or 6))
        editor.setRange(-1e15, 1e15)
        handle = WidgetHandle(field, editor)
    elif kind == "boolean":
        handle = WidgetHandle(field, QCheckBox(parent))
    elif kind == "date":
        editor = QDateEdit(parent)
        editor.setMinimumDate(QDate(1900, 1, 1))
        editor.setSpecialValueText("선택")
        editor.setCalendarPopup(True)
        editor.setDisplayFormat("yyyy-MM-dd")
        handle = WidgetHandle(field, editor)
    elif kind == "datetime":
        editor = QDateTimeEdit(parent)
        editor.setMinimumDateTime(QDateTime(QDate(1900, 1, 1), editor.minimumTime()))
        editor.setSpecialValueText("선택")
        editor.setCalendarPopup(True)
        editor.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        handle = WidgetHandle(field, editor)
    elif kind == "photo":
        host, editor = _photo_widget(parent)
        handle = WidgetHandle(field, host, editor=editor)
    else:
        editor = QLineEdit(parent)
        maximum = field.get("max_length")
        if maximum:
            editor.setMaxLength(int(maximum))
        handle = WidgetHandle(field, editor)
    handle.set_readonly(field.get("readonly") or kind == "hidden")
    handle.widget.setVisible(bool(field.get("visible", True)) and kind != "hidden")
    return handle
