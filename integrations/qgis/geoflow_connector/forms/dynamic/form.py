"""Dynamic form view assembled from one normalized central definition."""
from __future__ import annotations

from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import QWidget, QVBoxLayout

from .layout import LayoutRenderer
from .rules import allowed_code_ids, validate
from .style import apply_form_style
from .widgets import create_widget


class DynamicForm(QWidget):
    changed = pyqtSignal(str)

    def __init__(self, definition, fields, parent=None):
        super().__init__(parent)
        self.definition = definition
        self.fields = fields
        apply_form_style(self)
        self.handles = {field["id"]: create_widget(field, self) for field in fields}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(LayoutRenderer().render(fields, self.handles, self))
        for field_id, handle in self.handles.items():
            handle.connect_changed(lambda *args, key=field_id: self._changed(key))
        self.apply_rules()

    def _changed(self, field_id):
        self.handles[field_id].set_error(None)
        self.apply_rules()
        self.changed.emit(field_id)

    def values(self):
        return {field_id: handle.value() for field_id, handle in self.handles.items()}

    def load_values(self, values):
        self.blockSignals(True)
        try:
            for field_id, handle in self.handles.items():
                handle.set_value(values.get(field_id))
            self.apply_rules()
        finally:
            self.blockSignals(False)

    def apply_rules(self):
        values = self.values()
        for field in self.fields:
            self.handles[field["id"]].set_allowed_codes(
                allowed_code_ids(self.definition, field["id"], values)
            )

    def validation_errors(self):
        errors = validate(self.definition, self.fields, self.values())
        for handle in self.handles.values():
            handle.set_error(None)
        for message in errors:
            for field in self.fields:
                if message.startswith(field["label"] + " "):
                    self.handles[field["id"]].set_error(message)
                    break
        return errors
