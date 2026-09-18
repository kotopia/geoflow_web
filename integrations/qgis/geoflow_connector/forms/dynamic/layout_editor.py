# GeoFlow QGIS 플러그인 - 로컬 속성폼 배치 편집기
# 레이어별 그룹·행·필드 배치를 편집하고 QGIS 사용자 설정에만 저장한다.
from __future__ import annotations

import json

from qgis.PyQt.QtCore import QSettings, QSignalBlocker, Qt
from qgis.PyQt.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QInputDialog, QLabel,
    QListWidget, QMessageBox, QPushButton, QSplitter, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .layout_model import default_layout, normalize_layout, unplaced_fields
from .style import apply_form_style


_ROLE_KIND = Qt.ItemDataRole.UserRole
_ROLE_FIELD_ID = Qt.ItemDataRole.UserRole + 1
_KIND_TAB, _KIND_GROUP, _KIND_ROW, _KIND_FIELD = "tab", "group", "row", "field"


# ============================================================
# QGIS 사용자 설정 저장소
# ============================================================
class LocalFormLayoutStore:
    """중앙/프로젝트 데이터와 무관한 현재 PC 사용자별 폼 배치 저장소."""

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


# ============================================================
# 그룹·행·필드 편집 대화상자
# ============================================================
class FormLayoutEditor(QDialog):
    """JSON을 직접 다루지 않고 제한된 배치 연산만 제공하는 편집 UI."""

    def __init__(self, layer, fields, layout, parent=None):
        super().__init__(parent)
        self.layer = str(layer or "").upper()
        self.fields = fields
        self.fields_by_id = {str(field["id"]): field for field in fields}
        self._reset_requested = False
        self.setWindowTitle(f"GeoFlow · {self.layer} 폼 배치 편집")
        self.resize(900, 680)
        apply_form_style(self)

        outer = QVBoxLayout(self)
        guide = QLabel(
            "중앙 필드의 이름·Widget·필수·읽기전용 규칙은 바뀌지 않습니다. "
            "이 PC에서 보이는 탭·그룹·행·필드 순서만 저장합니다."
        )
        guide.setWordWrap(True)
        outer.addWidget(guide)

        splitter = QSplitter(self)
        left = QWidget(splitter)
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("현재 배치"))
        self.tree = QTreeWidget(left)
        self.tree.setHeaderHidden(True)
        left_layout.addWidget(self.tree)
        splitter.addWidget(left)

        right = QWidget(splitter)
        right_layout = QVBoxLayout(right)
        self.unplaced_label = QLabel()
        right_layout.addWidget(self.unplaced_label)
        self.unplaced = QListWidget(right)
        right_layout.addWidget(self.unplaced)
        right_layout.addWidget(QLabel("이동할 대상 행"))
        self.target_rows = QComboBox(right)
        right_layout.addWidget(self.target_rows)
        move_button = QPushButton("선택 필드를 대상 행으로 이동", right)
        move_button.clicked.connect(self._move_field)
        right_layout.addWidget(move_button)
        right_layout.addStretch(1)
        splitter.addWidget(right)
        splitter.setSizes([610, 290])
        outer.addWidget(splitter, 1)

        tools = QHBoxLayout()
        for label, slot in (
            ("+ 그룹", self._add_group), ("+ 행", self._add_row),
            ("그룹 이름", self._rename_group), ("위", lambda: self._move_item(-1)),
            ("아래", lambda: self._move_item(1)), ("필드 미배치", self._unplace_field),
        ):
            button = QPushButton(label, self)
            button.clicked.connect(slot)
            tools.addWidget(button)
        tools.addStretch(1)
        reset_button = QPushButton("기본 배치로 되돌리기", self)
        reset_button.clicked.connect(self._request_reset)
        tools.addWidget(reset_button)
        outer.addLayout(tools)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("저장")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self.tree.itemSelectionChanged.connect(self._tree_selection_changed)
        self.unplaced.itemSelectionChanged.connect(self._unplaced_selection_changed)
        self._load_tree(layout)

    @property
    def reset_requested(self):
        return self._reset_requested

    def _item(self, title, kind, field_id=None):
        item = QTreeWidgetItem([title])
        item.setData(0, _ROLE_KIND, kind)
        if field_id is not None:
            item.setData(0, _ROLE_FIELD_ID, str(field_id))
        return item

    @staticmethod
    def _field_caption(field):
        physical_name = (
            field.get("field_name")
            or (field.get("storage") or {}).get("key")
            or field.get("field_identifier")
            or field.get("id")
        )
        return f"{field['label']}  ·  {physical_name}"

    def _load_tree(self, layout):
        self.tree.clear()
        normalized = normalize_layout(layout, self.layer, self.fields) or default_layout(
            self.layer, self.fields
        )
        for tab in normalized["tabs"]:
            tab_item = self._item(tab["title"], _KIND_TAB)
            self.tree.addTopLevelItem(tab_item)
            for group in tab["groups"]:
                group_item = self._item(group["title"], _KIND_GROUP)
                tab_item.addChild(group_item)
                for row_index, row in enumerate(group["rows"], 1):
                    row_item = self._item(f"행 {row_index}", _KIND_ROW)
                    group_item.addChild(row_item)
                    for field_id in row:
                        field = self.fields_by_id[field_id]
                        row_item.addChild(self._item(
                            self._field_caption(field), _KIND_FIELD, field_id
                        ))
            tab_item.setExpanded(True)
        self.tree.expandAll()
        self._refresh_auxiliary()

    def _layout(self):
        tabs = []
        for tab_index in range(self.tree.topLevelItemCount()):
            tab_item = self.tree.topLevelItem(tab_index)
            groups = []
            for group_index in range(tab_item.childCount()):
                group_item = tab_item.child(group_index)
                rows = []
                for row_index in range(group_item.childCount()):
                    row_item = group_item.child(row_index)
                    row = [
                        str(row_item.child(i).data(0, _ROLE_FIELD_ID))
                        for i in range(row_item.childCount())
                    ]
                    rows.append(row)
                groups.append({"title": group_item.text(0), "rows": rows})
            tabs.append({"title": tab_item.text(0), "groups": groups})
        return {"version": 1, "layer": self.layer, "tabs": tabs}

    def value(self):
        return normalize_layout(self._layout(), self.layer, self.fields) or default_layout(
            self.layer, self.fields
        )

    def _refresh_auxiliary(self):
        current = self._layout()
        self.unplaced.clear()
        for field in unplaced_fields(current, self.fields):
            self.unplaced.addItem(self._field_caption(field))
            self.unplaced.item(self.unplaced.count() - 1).setData(_ROLE_FIELD_ID, str(field["id"]))
        self.unplaced_label.setText(f"미배치 필드 ({self.unplaced.count()})")
        self.target_rows.clear()
        for tab_index in range(self.tree.topLevelItemCount()):
            tab = self.tree.topLevelItem(tab_index)
            for group_index in range(tab.childCount()):
                group = tab.child(group_index)
                for row_index in range(group.childCount()):
                    row = group.child(row_index)
                    row.setText(0, f"행 {row_index + 1}")
                    self.target_rows.addItem(
                        f"{tab.text(0)} / {group.text(0)} / 행 {row_index + 1}", row
                    )

    def _selected_ancestor(self, kind):
        item = self.tree.currentItem()
        while item is not None and item.data(0, _ROLE_KIND) != kind:
            item = item.parent()
        return item

    def _tree_selection_changed(self):
        if self.tree.selectedItems():
            blocker = QSignalBlocker(self.unplaced)
            self.unplaced.clearSelection()
            del blocker

    def _unplaced_selection_changed(self):
        if self.unplaced.selectedItems():
            blocker = QSignalBlocker(self.tree)
            self.tree.clearSelection()
            del blocker

    def _add_group(self):
        tab = self._selected_ancestor(_KIND_TAB)
        if tab is None and self.tree.topLevelItemCount():
            tab = self.tree.topLevelItem(0)
        if tab is None:
            tab = self._item("기본 정보", _KIND_TAB)
            self.tree.addTopLevelItem(tab)
        title, accepted = QInputDialog.getText(self, "그룹 추가", "그룹 이름")
        if accepted and title.strip():
            group = self._item(title.strip(), _KIND_GROUP)
            group.addChild(self._item("행 1", _KIND_ROW))
            tab.addChild(group)
            tab.setExpanded(True)
            group.setExpanded(True)
            self.tree.setCurrentItem(group)
            self._refresh_auxiliary()

    def _add_row(self):
        group = self._selected_ancestor(_KIND_GROUP)
        if group is None:
            QMessageBox.information(self, "GeoFlow", "행을 추가할 그룹을 먼저 선택하세요.")
            return
        row = self._item(f"행 {group.childCount() + 1}", _KIND_ROW)
        group.addChild(row)
        group.setExpanded(True)
        self.tree.setCurrentItem(row)
        self._refresh_auxiliary()

    def _rename_group(self):
        group = self._selected_ancestor(_KIND_GROUP)
        if group is None:
            return
        title, accepted = QInputDialog.getText(
            self, "그룹 이름 변경", "그룹 이름", text=group.text(0)
        )
        if accepted and title.strip():
            group.setText(0, title.strip())

    def _move_item(self, offset):
        item = self.tree.currentItem()
        if item is None or item.data(0, _ROLE_KIND) == _KIND_TAB:
            return
        parent = item.parent()
        index = parent.indexOfChild(item)
        target = index + offset
        if 0 <= target < parent.childCount():
            parent.takeChild(index)
            parent.insertChild(target, item)
            self.tree.setCurrentItem(item)
            self._refresh_auxiliary()

    def _selected_field(self):
        tree_item = self.tree.selectedItems()[0] if self.tree.selectedItems() else None
        if tree_item is not None and tree_item.data(0, _ROLE_KIND) == _KIND_FIELD:
            return str(tree_item.data(0, _ROLE_FIELD_ID)), tree_item
        list_item = self.unplaced.selectedItems()[0] if self.unplaced.selectedItems() else None
        if list_item is not None:
            return str(list_item.data(_ROLE_FIELD_ID)), None
        return None, None

    def _move_field(self):
        field_id, source = self._selected_field()
        target = self.target_rows.currentData()
        if not field_id or target is None:
            QMessageBox.information(self, "GeoFlow", "필드와 이동할 대상 행을 선택하세요.")
            return
        if source is not None:
            source.parent().removeChild(source)
        field = self.fields_by_id[field_id]
        target.addChild(self._item(self._field_caption(field), _KIND_FIELD, field_id))
        target.setExpanded(True)
        self._refresh_auxiliary()

    def _unplace_field(self):
        item = self.tree.currentItem()
        if item is None or item.data(0, _ROLE_KIND) != _KIND_FIELD:
            return
        item.parent().removeChild(item)
        self._refresh_auxiliary()

    def _request_reset(self):
        answer = QMessageBox.question(
            self, "GeoFlow · 기본 배치 복원",
            "이 레이어의 로컬 사용자 배치를 삭제하고 기본 배치로 되돌릴까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._reset_requested = True
            self.accept()
