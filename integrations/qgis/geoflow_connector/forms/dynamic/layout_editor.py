from __future__ import annotations

import json

from qgis.PyQt.QtCore import QEvent, QMimeData, QObject, QSettings, Qt, pyqtSignal
from qgis.PyQt.QtGui import QDrag
from qgis.PyQt.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFrame, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton, QScrollArea,
    QSpinBox, QSplitter, QStackedWidget, QTabWidget, QVBoxLayout, QWidget,
)

from .layout_model import (
    default_layout, normalize_layout, row_field_id, row_field_weight,
    unplaced_fields,
)
from .style import apply_form_style
from .widgets import create_widget


_FIELD_MIME = "application/x-geoflow-layout-field"
_FIELD_ROLE = Qt.ItemDataRole.UserRole


class LocalFormLayoutStore:
    """User-local layout storage; server definitions remain untouched."""

    KEY_PREFIX = "GeoFlowConnector/formLayouts/"

    def __init__(self, settings=None):
        self.settings = settings or QSettings()

    @classmethod
    def key(cls, layer):
        return cls.KEY_PREFIX + str(layer or "").upper()

    def load(self, layer, fields):
        raw = self.settings.value(self.key(layer), "", type=str)
        if not raw:
            return default_layout(layer, fields)
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            return default_layout(layer, fields)
        return normalize_layout(value, layer, fields) or default_layout(layer, fields)

    def save(self, layer, fields, layout):
        value = normalize_layout(layout, layer, fields)
        if value is None:
            raise ValueError("폼 배치 형식이 올바르지 않습니다.")
        self.settings.setValue(
            self.key(layer), json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        )
        self.settings.sync()
        return value

    def reset(self, layer):
        self.settings.remove(self.key(layer))
        self.settings.sync()


class _FieldList(QListWidget):
    fieldDropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def startDrag(self, actions):
        item = self.currentItem()
        if item is None:
            return
        mime = QMimeData()
        mime.setData(_FIELD_MIME, str(item.data(_FIELD_ROLE)).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(_FIELD_MIME):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(_FIELD_MIME):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasFormat(_FIELD_MIME):
            field_id = bytes(event.mimeData().data(_FIELD_MIME)).decode("utf-8")
            self.fieldDropped.emit(field_id)
            event.acceptProposedAction()
            return
        super().dropEvent(event)


class _FieldCard(QFrame):
    clicked = pyqtSignal(str)

    def __init__(self, field_id, parent=None):
        super().__init__(parent)
        self.field_id = str(field_id)
        self.setProperty("editorRole", "fieldCard")
        self._press_pos = None

    def mousePressEvent(self, event):
        self._press_pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        event.accept()
        self.clicked.emit(self.field_id)

    def mouseMoveEvent(self, event):
        if self._press_pos is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return super().mouseMoveEvent(event)
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        if (pos - self._press_pos).manhattanLength() < 8:
            return super().mouseMoveEvent(event)
        mime = QMimeData(); mime.setData(_FIELD_MIME, self.field_id.encode("utf-8"))
        drag = QDrag(self); drag.setMimeData(mime); drag.exec(Qt.DropAction.MoveAction)


class _DropRow(QFrame):
    selected = pyqtSignal(int, int, int)
    fieldDropped = pyqtSignal(str, int, int, int, int)

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.path = tuple(path)
        self.setObjectName("geoFormEditorRow")
        self.setAcceptDrops(True)
        self.setMinimumHeight(58)

    def mousePressEvent(self, event):
        event.accept()
        self.selected.emit(*self.path)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(_FIELD_MIME):
            self.setProperty("dropTarget", True)
            self.style().unpolish(self); self.style().polish(self)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.setProperty("dropTarget", False)
        self.style().unpolish(self); self.style().polish(self)

    def dropEvent(self, event):
        field_id = bytes(event.mimeData().data(_FIELD_MIME)).decode("utf-8")
        position = event.position().toPoint() if hasattr(event, "position") else event.pos()
        cards = self.findChildren(_FieldCard, options=Qt.FindChildOption.FindDirectChildrenOnly)
        insert_at = len(cards)
        for index, card in enumerate(cards):
            if position.x() < card.geometry().center().x():
                insert_at = index
                break
        self.setProperty("dropTarget", False)
        self.style().unpolish(self); self.style().polish(self)
        self.fieldDropped.emit(field_id, *self.path, insert_at)
        event.acceptProposedAction()


class _ClickGroup(QGroupBox):
    selected = pyqtSignal(int, int)

    def __init__(self, title, path, parent=None):
        super().__init__(title, parent)
        self.path = tuple(path)

    def mousePressEvent(self, event):
        event.accept()
        self.selected.emit(*self.path)


class _PreviewBlocker(QObject):
    def __init__(self, callback, parent=None):
        super().__init__(parent)
        self.callback = callback

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            self.callback()
            return True
        return event.type() in {
            QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick,
            QEvent.Type.Wheel, QEvent.Type.KeyPress, QEvent.Type.KeyRelease,
        }


class FormLayoutEditor(QDialog):
    """Preview-first editor for the existing Tab/Group/Row/Field model."""

    def __init__(self, layer, fields, layout, parent=None):
        super().__init__(parent)
        self.layer = str(layer or "").upper()
        self.fields = fields
        self.fields_by_id = {str(field["id"]): field for field in fields}
        self._layout_value = normalize_layout(layout, self.layer, fields) or default_layout(self.layer, fields)
        self._reset_requested = False
        self._selection = None
        self._blockers = []
        self.setWindowTitle(f"GeoFlow · {self.layer} 폼 배치 편집")
        self.resize(1220, 760)
        apply_form_style(self)

        outer = QVBoxLayout(self)
        guide = QLabel("필드를 드래그해 실제 폼과 같은 Preview에서 배치하세요. 필드 정의와 실제 객체 값은 변경되지 않습니다.")
        guide.setWordWrap(True); outer.addWidget(guide)
        splitter = QSplitter(self)
        splitter.addWidget(self._build_unplaced(splitter))
        splitter.addWidget(self._build_preview(splitter))
        splitter.addWidget(self._build_inspector(splitter))
        splitter.setSizes([230, 700, 270]); outer.addWidget(splitter, 1)
        footer = QHBoxLayout()
        reset = QPushButton("기본 배치로 되돌리기", self); reset.clicked.connect(self._request_reset)
        footer.addWidget(reset); footer.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel, parent=self)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("저장")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        footer.addWidget(buttons); outer.addLayout(footer)
        self._rebuild()

    @property
    def reset_requested(self):
        return self._reset_requested

    def value(self):
        return normalize_layout(self._layout_value, self.layer, self.fields) or default_layout(self.layer, self.fields)

    def _build_unplaced(self, parent):
        host = QWidget(parent); layout = QVBoxLayout(host)
        self.unplaced_label = QLabel("미배치 필드"); layout.addWidget(self.unplaced_label)
        self.unplaced = _FieldList(host); self.unplaced.setDragEnabled(True)
        self.unplaced.itemSelectionChanged.connect(self._select_unplaced)
        self.unplaced.fieldDropped.connect(self._unplace_field); layout.addWidget(self.unplaced, 1)
        hint = QLabel("필드를 가운데 Row로 드래그하거나 오른쪽 이동 대상을 선택하세요.")
        hint.setWordWrap(True); layout.addWidget(hint)
        return host

    def _build_preview(self, parent):
        host = QWidget(parent); layout = QVBoxLayout(host)
        title = QLabel("Form Preview"); title.setProperty("editorRole", "previewTitle"); layout.addWidget(title)
        self.preview_scroll = QScrollArea(host); self.preview_scroll.setWidgetResizable(True); layout.addWidget(self.preview_scroll, 1)
        return host

    def _build_inspector(self, parent):
        host = QWidget(parent); layout = QVBoxLayout(host); layout.addWidget(QLabel("선택 항목 설정"))
        self.inspector = QStackedWidget(host)
        self.empty_panel = QLabel("Group, Row 또는 Field를 선택하세요."); self.empty_panel.setWordWrap(True)
        self.inspector.addWidget(self.empty_panel)
        self.group_panel = QWidget(); group_layout = QVBoxLayout(self.group_panel)
        group_layout.addWidget(QLabel("그룹 이름")); self.group_name = QLineEdit(); group_layout.addWidget(self.group_name)
        rename = QPushButton("이름 적용"); rename.clicked.connect(self._rename_group); group_layout.addWidget(rename)
        self._add_move_buttons(group_layout, True)
        add_row = QPushButton("+ 행 추가"); add_row.clicked.connect(self._add_row); group_layout.addWidget(add_row)
        group_layout.addStretch(1); self.inspector.addWidget(self.group_panel)
        self.row_panel = QWidget(); row_layout = QVBoxLayout(self.row_panel)
        row_layout.addWidget(QLabel("행 설정")); self._add_move_buttons(row_layout, True)
        add_row_after = QPushButton("+ 행 추가"); add_row_after.clicked.connect(self._add_row); row_layout.addWidget(add_row_after)
        row_layout.addStretch(1)
        self.inspector.addWidget(self.row_panel)
        self.field_panel = QWidget(); field_layout = QVBoxLayout(self.field_panel)
        self.field_info = QLabel(); self.field_info.setWordWrap(True); field_layout.addWidget(self.field_info)
        field_layout.addWidget(QLabel("너비 비율 (0 = 자동)")); self.weight = QSpinBox(); self.weight.setRange(0, 20); self.weight.setSpecialValueText("자동"); field_layout.addWidget(self.weight)
        apply_weight = QPushButton("비율 적용"); apply_weight.clicked.connect(self._apply_weight); field_layout.addWidget(apply_weight)
        field_layout.addWidget(QLabel("이동 대상 Row")); self.target_rows = QComboBox(); field_layout.addWidget(self.target_rows)
        move = QPushButton("선택 Row로 이동"); move.clicked.connect(self._move_selected_field); field_layout.addWidget(move)
        self._add_move_buttons(field_layout, False)
        unplace = QPushButton("미배치로 이동"); unplace.clicked.connect(self._unplace_selected); field_layout.addWidget(unplace)
        field_layout.addStretch(1); self.inspector.addWidget(self.field_panel); layout.addWidget(self.inspector, 1)
        add_group = QPushButton("+ 그룹 추가", host); add_group.clicked.connect(self._add_group); layout.addWidget(add_group)
        return host

    def _add_move_buttons(self, layout, include_delete):
        row = QHBoxLayout(); up = QPushButton("위로"); down = QPushButton("아래로")
        up.clicked.connect(lambda: self._move_selected(-1)); down.clicked.connect(lambda: self._move_selected(1))
        row.addWidget(up); row.addWidget(down); layout.addLayout(row)
        if include_delete:
            delete = QPushButton("삭제"); delete.clicked.connect(self._delete_selected); layout.addWidget(delete)

    def _field_caption(self, field):
        return str(field.get("label") or field.get("name") or field.get("id"))

    def _physical_name(self, field):
        return str(field.get("field_name") or (field.get("storage") or {}).get("key") or field.get("field_identifier") or field.get("id"))

    def _rebuild(self):
        self._blockers.clear(); self._rebuild_unplaced(); self._rebuild_preview(); self._rebuild_targets(); self._show_selection()

    def _rebuild_unplaced(self):
        self.unplaced.clear()
        for field in unplaced_fields(self._layout_value, self.fields):
            self.unplaced.addItem(self._field_caption(field)); item = self.unplaced.item(self.unplaced.count() - 1)
            item.setData(_FIELD_ROLE, str(field["id"])); item.setToolTip(self._physical_name(field))
        self.unplaced_label.setText(f"미배치 필드 ({self.unplaced.count()})")

    def _rebuild_preview(self):
        root = QWidget(); root.setObjectName("GeoFlowDynamicForm"); root.setProperty("layoutEditorPreview", True); apply_form_style(root)
        outer = QVBoxLayout(root); tabs = QTabWidget(root)
        for ti, tab_spec in enumerate(self._layout_value.get("tabs", [])):
            tab = QWidget(); tab_layout = QVBoxLayout(tab)
            for gi, group_spec in enumerate(tab_spec.get("groups", [])):
                box = _ClickGroup(group_spec.get("title", "그룹"), (ti, gi), tab)
                box.setProperty("editorRole", "group"); box.setProperty("editorSelected", self._selection == ("group", ti, gi))
                box.selected.connect(lambda t, g: self._select(("group", t, g))); group_layout = QVBoxLayout(box)
                for ri, row_spec in enumerate(group_spec.get("rows", [])):
                    row = _DropRow((ti, gi, ri), box); row.setProperty("editorSelected", self._selection == ("row", ti, gi, ri))
                    row.selected.connect(lambda t, g, r: self._select(("row", t, g, r))); row.fieldDropped.connect(self._drop_field)
                    row_layout = QHBoxLayout(row); row_layout.setContentsMargins(7, 7, 7, 7); row_layout.setSpacing(10)
                    for field_spec in row_spec:
                        field_id = row_field_id(field_spec); field = self.fields_by_id[field_id]; card = self._preview_field(field, row)
                        card.path = (ti, gi, ri, field_id)
                        card.setProperty("editorSelected", self._selection == ("field", ti, gi, ri, field_id))
                        card.clicked.connect(lambda fid, t=ti, g=gi, r=ri: self._select(("field", t, g, r, fid)))
                        row_layout.addWidget(card, row_field_weight(field_spec))
                    if not row_spec:
                        empty = QLabel("여기에 필드를 놓으세요", row); empty.setAlignment(Qt.AlignmentFlag.AlignCenter); row_layout.addWidget(empty)
                    group_layout.addWidget(row)
                tab_layout.addWidget(box)
            tab_layout.addStretch(1); tabs.addTab(tab, str(tab_spec.get("title") or f"탭 {ti + 1}"))
        outer.addWidget(tabs); self.preview_scroll.setWidget(root)

    def _preview_field(self, field, parent):
        card = _FieldCard(field["id"], parent); card.setToolTip(self._physical_name(field))
        layout = QVBoxLayout(card); layout.setContentsMargins(5, 5, 5, 5); layout.setSpacing(4)
        label = QLabel(self._field_caption(field), card); label.setProperty("geoflowRole", "fieldLabel"); layout.addWidget(label)
        handle = create_widget(field, card)
        handle.set_value(None)
        layout.addWidget(handle.widget)
        blocker = _PreviewBlocker(lambda fid=str(field["id"]): self._select_field_id(fid), card); self._blockers.append(blocker)
        for widget in [handle.widget, *handle.widget.findChildren(QWidget)]:
            widget.installEventFilter(blocker); widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return card

    def _rebuild_targets(self):
        self.target_rows.clear()
        for ti, tab in enumerate(self._layout_value.get("tabs", [])):
            for gi, group in enumerate(tab.get("groups", [])):
                for ri, _row in enumerate(group.get("rows", [])):
                    self.target_rows.addItem(f"{tab['title']} / {group['title']} / 행 {ri + 1}", (ti, gi, ri))

    def _select(self, selection):
        self._selection = selection
        self._refresh_preview_selection()
        self._show_selection()

    @staticmethod
    def _set_selected(widget, selected):
        selected = bool(selected)
        if bool(widget.property("editorSelected")) == selected:
            return
        widget.setProperty("editorSelected", selected)
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()

    def _refresh_preview_selection(self):
        root = self.preview_scroll.widget()
        if root is None:
            return
        selection = self._selection
        for group in root.findChildren(_ClickGroup):
            self._set_selected(group, selection == ("group", *group.path))
        for row in root.findChildren(_DropRow):
            self._set_selected(row, selection == ("row", *row.path))
        for card in root.findChildren(_FieldCard):
            self._set_selected(card, selection == ("field", *card.path))

    def _select_field_id(self, field_id):
        location = self._find_field(field_id)
        if location: self._select(("field", *location, field_id))

    def _select_unplaced(self):
        item = self.unplaced.currentItem()
        if item is not None:
            self._selection = ("unplaced", str(item.data(_FIELD_ROLE))); field = self.fields_by_id[self._selection[1]]
            self._refresh_preview_selection()
            self.field_info.setText(self._field_details(field)); self.weight.setValue(0); self.inspector.setCurrentWidget(self.field_panel)

    def _show_selection(self):
        s = self._selection
        if not s: self.inspector.setCurrentWidget(self.empty_panel); return
        if s[0] == "group": self.group_name.setText(self._group(s).get("title", "")); self.inspector.setCurrentWidget(self.group_panel)
        elif s[0] == "row": self.inspector.setCurrentWidget(self.row_panel)
        elif s[0] == "field":
            field = self.fields_by_id[s[4]]; self.field_info.setText(self._field_details(field)); spec = self._row(s)[self._field_index(s[4])]
            self.weight.setValue(row_field_weight(spec) if isinstance(spec, dict) else 0); self.inspector.setCurrentWidget(self.field_panel)

    def _field_details(self, field):
        return (f"별칭: {self._field_caption(field)}\n필드명: {self._physical_name(field)}\nWidget: {field.get('widget_type')}\n"
                f"Required: {bool(field.get('required'))}\nReadonly: {bool(field.get('readonly'))}")

    def _group(self, selection=None):
        s = selection or self._selection; return self._layout_value["tabs"][s[1]]["groups"][s[2]]

    def _row(self, selection=None):
        s = selection or self._selection; return self._layout_value["tabs"][s[1]]["groups"][s[2]]["rows"][s[3]]

    def _find_field(self, field_id):
        for ti, tab in enumerate(self._layout_value.get("tabs", [])):
            for gi, group in enumerate(tab.get("groups", [])):
                for ri, row in enumerate(group.get("rows", [])):
                    if any(row_field_id(value) == str(field_id) for value in row): return ti, gi, ri
        return None

    def _field_index(self, field_id, row=None):
        row = row if row is not None else self._row(); return next(i for i, value in enumerate(row) if row_field_id(value) == str(field_id))

    def _drop_field(self, field_id, ti, gi, ri, insert_at):
        self._move_field_to(field_id, (ti, gi, ri), insert_at)

    def _move_field_to(self, field_id, target, insert_at=None):
        source = self._find_field(field_id); spec = str(field_id)
        if source:
            source_row = self._layout_value["tabs"][source[0]]["groups"][source[1]]["rows"][source[2]]
            source_index = self._field_index(field_id, source_row)
            spec = source_row.pop(source_index)
            if source == target and insert_at is not None and source_index < insert_at:
                insert_at -= 1
        target_row = self._layout_value["tabs"][target[0]]["groups"][target[1]]["rows"][target[2]]
        if insert_at is None:
            target_row.append(spec)
        else:
            target_row.insert(max(0, min(insert_at, len(target_row))), spec)
        self._reset_requested = False; self._selection = ("field", *target, str(field_id)); self._rebuild()

    def _unplace_field(self, field_id):
        source = self._find_field(field_id)
        if source:
            source_row = self._layout_value["tabs"][source[0]]["groups"][source[1]]["rows"][source[2]]
            source_row.pop(self._field_index(field_id, source_row))
            self._selection = ("unplaced", str(field_id)); self._reset_requested = False; self._rebuild()

    def _move_selected_field(self):
        if self._selection and self._selection[0] in {"field", "unplaced"} and self.target_rows.currentData() is not None:
            field_id = self._selection[4] if self._selection[0] == "field" else self._selection[1]
            self._move_field_to(field_id, self.target_rows.currentData())

    def _apply_weight(self):
        if not self._selection or self._selection[0] != "field": return
        row = self._row(); index = self._field_index(self._selection[4], row); field_id = self._selection[4]
        row[index] = field_id if self.weight.value() == 0 else {"field": field_id, "weight": self.weight.value()}
        self._reset_requested = False; self._rebuild()

    def _move_selected(self, offset):
        if not self._selection: return
        kind = self._selection[0]
        if kind == "group": container = self._layout_value["tabs"][self._selection[1]]["groups"]; index = self._selection[2]
        elif kind == "row": container = self._group()["rows"]; index = self._selection[3]
        elif kind == "field": container = self._row(); index = self._field_index(self._selection[4], container)
        else: return
        target = index + offset
        if 0 <= target < len(container):
            container[index], container[target] = container[target], container[index]
            if kind == "group": self._selection = (kind, self._selection[1], target)
            elif kind == "row": self._selection = (kind, self._selection[1], self._selection[2], target)
            self._reset_requested = False; self._rebuild()

    def _unplace_selected(self):
        if self._selection and self._selection[0] == "field":
            self._unplace_field(self._selection[4])

    def _rename_group(self):
        if self._selection and self._selection[0] == "group" and self.group_name.text().strip():
            self._group()["title"] = self.group_name.text().strip(); self._reset_requested = False; self._rebuild()

    def _add_group(self):
        if not self._layout_value["tabs"]: self._layout_value["tabs"].append({"title": "기본 정보", "groups": []})
        ti = self._selection[1] if self._selection and self._selection[0] in {"group", "row", "field"} else 0
        groups = self._layout_value["tabs"][ti]["groups"]; groups.append({"title": "새 그룹", "rows": [[]]})
        self._selection = ("group", ti, len(groups)-1); self._reset_requested = False; self._rebuild()

    def _add_row(self):
        if self._selection and self._selection[0] in {"group", "row"}:
            rows = self._group()["rows"]
            insert_at = self._selection[3] + 1 if self._selection[0] == "row" else len(rows)
            rows.insert(insert_at, []); self._selection = ("row", self._selection[1], self._selection[2], insert_at)
            self._reset_requested = False; self._rebuild()

    def _delete_selected(self):
        if not self._selection: return
        if self._selection[0] == "group": self._layout_value["tabs"][self._selection[1]]["groups"].pop(self._selection[2])
        elif self._selection[0] == "row": self._group()["rows"].pop(self._selection[3])
        else: return
        self._selection = None; self._reset_requested = False; self._rebuild()

    def _request_reset(self):
        answer = QMessageBox.question(self, "GeoFlow · 기본 배치 복원", "이 레이어의 사용자 배치를 기본 배치로 되돌릴까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Yes:
            self._layout_value = default_layout(self.layer, self.fields); self._selection = None; self._reset_requested = True; self._rebuild()
