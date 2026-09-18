# GeoFlow QGIS 플러그인 - 속성폼 화면 배치
# 중앙 필드 위젯을 로컬 Tab → Group → Row → Field 배치에 따라 표시한다.
from __future__ import annotations

from qgis.PyQt.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QTabWidget, QVBoxLayout, QWidget,
)

from .layout_model import render_layout

# ============================================================
# 필드 Label · 입력 위젯 · 오류 메시지 블록
# ============================================================
class LayoutRenderer:
    @staticmethod
    def _field_block(field, handle, parent):
        block = QWidget(parent)
        block.setProperty("geoflowRole", "fieldBlock")
        layout = QVBoxLayout(block)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        label_row = QHBoxLayout()
        label_row.setContentsMargins(0, 0, 0, 0)
        label_row.setSpacing(3)
        label = QLabel(field["label"], block)
        label.setProperty("geoflowRole", "fieldLabel")
        label_row.addWidget(label)
        if field.get("required"):
            marker = QLabel("*", block)
            marker.setProperty("geoflowRole", "requiredMarker")
            label_row.addWidget(marker)
        label_row.addStretch(1)
        layout.addLayout(label_row)
        layout.addWidget(handle.widget)

        error = QLabel("", block)
        error.setProperty("geoflowRole", "fieldError")
        error.setWordWrap(True)
        error.hide()
        layout.addWidget(error)
        handle.attach_error_label(error)
        return block

    # ============================================================
    # 사용자 배치에 따른 탭·그룹·행 렌더링
    # ============================================================
    def render(self, fields, handles, parent=None, *, layer="", layout=None):
        root = QWidget(parent)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(16)
        tabs = QTabWidget(root)
        fields_by_id = {str(field["id"]): field for field in fields}
        effective = render_layout(layout, layer, fields)
        for tab_spec in effective["tabs"]:
            tab = QWidget(tabs)
            tab_layout = QVBoxLayout(tab)
            tab_layout.setContentsMargins(4, 4, 4, 4)
            tab_layout.setSpacing(16)
            for group_spec in tab_spec["groups"]:
                box = QGroupBox(group_spec["title"], tab)
                form = QVBoxLayout(box)
                form.setContentsMargins(10, 12, 10, 10)
                form.setSpacing(12)
                for row_spec in group_spec["rows"]:
                    row = QHBoxLayout()
                    row.setContentsMargins(0, 0, 0, 0)
                    row.setSpacing(12)
                    for field_id in row_spec:
                        field = fields_by_id[field_id]
                        row.addWidget(
                            self._field_block(field, handles[field_id], box), 1
                        )
                    form.addLayout(row)
                tab_layout.addWidget(box)
            tab_layout.addStretch(1)
            tabs.addTab(tab, tab_spec["title"])
        outer.addWidget(tabs)
        return root
