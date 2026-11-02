# GeoFlow QGIS 플러그인 - 중앙 정의 기반 동적 속성폼
# 중앙 위젯·규칙은 유지하고 로컬 사용자 배치에 따라 화면만 다시 구성한다.
from __future__ import annotations

from qgis.PyQt.QtCore import QTimer, pyqtSignal
from qgis.PyQt.QtWidgets import QTabWidget, QWidget, QVBoxLayout

from .layout import LayoutRenderer
from .rules import allowed_code_ids, validate
from .style import apply_form_style
from .widgets import create_widget


class DynamicForm(QWidget):
    changed = pyqtSignal(str)
    behaviorChanged = pyqtSignal()
    layoutChanged = pyqtSignal()
    valuesLoaded = pyqtSignal()

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
        self._behavior_widgets = []
        self._header_widget = None
        self._field_actions = {}
        self._behavior_active = {}
        self._save_transforms = []
        self._save_null_providers = []
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
        current_tab = self.tabs.currentIndex()
        scroll_positions = [
            (page.horizontalScrollBar().value(), page.verticalScrollBar().value())
            for page in self._form_pages
        ]
        self.tabs.setUpdatesEnabled(False)
        # Rebuild only central form pages. Auxiliary pages such as Photos stay
        # attached to the same top-level tab host and are appended again last.
        for widget, _title, _visible, _index in self._auxiliary_tabs:
            index = self.tabs.indexOf(widget)
            if index >= 0:
                self.tabs.removeTab(index)
            widget.setParent(self.tabs)
        for handle in self.handles.values():
            handle.widget.setParent(self)
        for widgets in self._field_actions.values():
            for widget in widgets:
                widget.setParent(self)
        for page in self._form_pages:
            index = self.tabs.indexOf(page)
            if index >= 0:
                self.tabs.removeTab(index)
            page.deleteLater()
        self._form_pages = LayoutRenderer().populate_tabs(
            self.tabs, self.fields, self.handles, layer=self.layer, layout=form_layout,
            field_actions=self._field_actions,
        )
        for widget, title, visible, requested_index in self._auxiliary_tabs:
            if requested_index is None:
                index = self.tabs.addTab(widget, title)
            else:
                index = self.tabs.insertTab(
                    max(0, min(int(requested_index), self.tabs.count())),
                    widget, title,
                )
            self.tabs.setTabVisible(index, visible)
        def restore_view():
            if current_tab >= 0 and self.tabs.count():
                self.tabs.setCurrentIndex(min(current_tab, self.tabs.count() - 1))
            for page, (horizontal, vertical) in zip(
                    self._form_pages, scroll_positions):
                page.horizontalScrollBar().setValue(horizontal)
                page.verticalScrollBar().setValue(vertical)
        restore_view()
        self.tabs.setUpdatesEnabled(True)
        QTimer.singleShot(0, restore_view)
        self.layoutChanged.emit()

    def add_behavior_widget(self, widget):
        """Place a reusable behavior control above the central form tabs."""
        if widget not in self._behavior_widgets:
            self._behavior_widgets.append(widget)
            offset = 1 if self._header_widget is not None else 0
            self._root_layout.insertWidget(
                offset + len(self._behavior_widgets) - 1, widget
            )

    def set_header_widget(self, widget):
        """Install one stable header row above the central form tabs."""
        if self._header_widget is widget:
            return
        if self._header_widget is not None:
            self._root_layout.removeWidget(self._header_widget)
            self._header_widget.setParent(None)
        self._header_widget = widget
        if widget is not None:
            widget.setParent(self)
            self._root_layout.insertWidget(0, widget)

    def add_field_action(self, field_id, widget):
        """Decorate a dynamic field cell without changing the central definition."""
        if field_id not in self.handles:
            return False
        widgets = self._field_actions.setdefault(field_id, [])
        if widget not in widgets:
            widgets.append(widget)
            self.set_form_layout(self.form_layout)
        return True

    def move_field_action(self, field_id, widget):
        """Move an existing action beside another field and preserve all drafts."""
        if field_id not in self.handles:
            return False
        current_field_id = next(
            (key for key, widgets in self._field_actions.items() if widget in widgets),
            None,
        )
        if current_field_id == field_id:
            return True
        if current_field_id is not None:
            self._field_actions[current_field_id].remove(widget)
            if not self._field_actions[current_field_id]:
                del self._field_actions[current_field_id]
        self._field_actions.setdefault(field_id, []).append(widget)
        self.set_form_layout(self.form_layout)
        return True

    def register_save_behavior(self, transform, null_fields):
        """Register a non-destructive draft transform used only by save/validation."""
        self._save_transforms.append(transform)
        self._save_null_providers.append(null_fields)

    def set_field_behavior_active(self, field_id, active):
        if field_id not in self.handles:
            return
        self._behavior_active[field_id] = bool(active)
        self.handles[field_id].set_behavior_active(active)

    def save_values(self):
        values = self.values()
        for transform in self._save_transforms:
            values = transform(dict(values))
        return values

    def save_null_field_ids(self):
        result = set()
        for provider in self._save_null_providers:
            result.update(provider())
        return result

    def notify_behavior_changed(self):
        self.behaviorChanged.emit()

    def add_auxiliary_tab(self, widget, title, *, visible=True, index=None):
        """Attach a non-field page, optionally at its central definition index."""
        requested_index = None if index is None else int(index)
        self._auxiliary_tabs.append(
            (widget, str(title), bool(visible), requested_index)
        )
        if requested_index is None:
            index = self.tabs.addTab(widget, str(title))
        else:
            index = self.tabs.insertTab(
                max(0, min(requested_index, self.tabs.count())),
                widget, str(title),
            )
        self.tabs.setTabVisible(index, bool(visible))
        return index

    def set_auxiliary_tab_visible(self, widget, visible):
        visible = bool(visible)
        self._auxiliary_tabs = [
            (candidate, title, visible if candidate is widget else current, index)
            for candidate, title, current, index in self._auxiliary_tabs
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
        self.valuesLoaded.emit()

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
        values = self.save_values()
        validation_fields = []
        for field in self.fields:
            if self._behavior_active.get(field["id"], True):
                validation_fields.append(field)
            else:
                inactive = dict(field)
                inactive["visible"] = False
                validation_fields.append(inactive)
        errors = validate(self.definition, validation_fields, values)
        for handle in self.handles.values():
            handle.set_error(None)
        for message in errors:
            for field in self.fields:
                if message.startswith(field["label"] + " "):
                    self.handles[field["id"]].set_error(message)
                    break
        return errors
