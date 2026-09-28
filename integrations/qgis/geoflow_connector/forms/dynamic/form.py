# GeoFlow QGIS 플러그인 - 중앙 정의 기반 동적 속성폼
# 중앙 위젯·규칙은 유지하고 로컬 사용자 배치에 따라 화면만 다시 구성한다.
from __future__ import annotations

from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import QTabWidget, QWidget, QVBoxLayout

from .layout import LayoutRenderer
from .rules import allowed_code_ids, validate
from .style import apply_form_style
from .widgets import create_widget


class DynamicForm(QWidget):
    changed = pyqtSignal(str)

    def __init__(self, definition, fields, parent=None, *, layer="", form_layout=None):
        super().__init__(parent)
        self.definition = definition
        self.fields = fields
        self.layer = str(layer or "").upper()
        self.form_layout = form_layout
        apply_form_style(self)
        self.handles = {field["id"]: create_widget(field, self) for field in fields}
        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget(self)
        self._root_layout.addWidget(self.tabs)
        self._form_pages = []
        self._auxiliary_tabs = []
        self.set_form_layout(form_layout)
        for field_id, handle in self.handles.items():
            handle.connect_changed(lambda *args, key=field_id: self._changed(key))
        self.apply_rules()

    # ============================================================
    # 입력값을 보존한 화면 배치 재구성
    # ============================================================
    def set_form_layout(self, form_layout):
        self.form_layout = form_layout
        # Rebuild only central form pages. Auxiliary pages such as Photos stay
        # attached to the same top-level tab host and are appended again last.
        for widget, _title, _visible in self._auxiliary_tabs:
            index = self.tabs.indexOf(widget)
            if index >= 0:
                self.tabs.removeTab(index)
            widget.setParent(self.tabs)
        for handle in self.handles.values():
            handle.widget.setParent(self)
        for page in self._form_pages:
            index = self.tabs.indexOf(page)
            if index >= 0:
                self.tabs.removeTab(index)
            page.deleteLater()
        self._form_pages = LayoutRenderer().populate_tabs(
            self.tabs, self.fields, self.handles, layer=self.layer, layout=form_layout
        )
        for widget, title, visible in self._auxiliary_tabs:
            index = self.tabs.addTab(widget, title)
            self.tabs.setTabVisible(index, visible)

    def add_auxiliary_tab(self, widget, title, *, visible=True):
        """Append a non-form page after every centrally defined form tab."""
        self._auxiliary_tabs.append((widget, str(title), bool(visible)))
        index = self.tabs.addTab(widget, str(title))
        self.tabs.setTabVisible(index, bool(visible))
        return index

    def set_auxiliary_tab_visible(self, widget, visible):
        visible = bool(visible)
        self._auxiliary_tabs = [
            (candidate, title, visible if candidate is widget else current)
            for candidate, title, current in self._auxiliary_tabs
        ]
        index = self.tabs.indexOf(widget)
        if index >= 0:
            self.tabs.setTabVisible(index, visible)

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

    def set_worker_reference_codes(self, codes):
        for handle in self.handles.values():
            if handle.field.get("worker_reference"):
                handle.set_reference_codes(codes)

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
