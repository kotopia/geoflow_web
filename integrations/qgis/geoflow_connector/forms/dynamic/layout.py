# GeoFlow QGIS 플러그인 - 속성폼 화면 배치
# 중앙 필드 위젯을 로컬 Tab → Group → Row → Field 배치에 따라 표시한다.
from __future__ import annotations

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QTabWidget,
    QVBoxLayout, QWidget,
)

from .layout_model import render_layout, row_field_id, row_field_weight

# ============================================================
# 필드 Label · 입력 위젯 · 오류 메시지 블록
# ============================================================
class LayoutRenderer:
    @staticmethod
    def _field_block(field, handle, parent):
        block = QWidget(parent)
        block.setProperty("geoflowRole", "fieldBlock")
        block.setMinimumWidth(0)
        block.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        for widget in (handle.widget, handle.editor):
            widget.setMinimumWidth(0)
            policy = widget.sizePolicy()
            policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
            policy.setHorizontalStretch(1)
            widget.setSizePolicy(policy)
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
    def populate_tabs(self, tabs, fields, handles, *, layer="", layout=None):
        """Append form tabs to a shared host and return the created tab pages."""
        fields_by_id = {str(field["id"]): field for field in fields}
        effective = render_layout(layout, layer, fields)
        pages = []
        for tab_spec in effective["tabs"]:
            content = QWidget(tabs)
            tab_layout = QVBoxLayout(content)
            tab_layout.setContentsMargins(4, 4, 4, 4)
            tab_layout.setSpacing(16)
            for group_spec in tab_spec["groups"]:
                box = QGroupBox(group_spec["title"], content)
                form = QVBoxLayout(box)
                form.setContentsMargins(10, 12, 10, 10)
                form.setSpacing(12)
                for row_spec in group_spec["rows"]:
                    row = QHBoxLayout()
                    row.setContentsMargins(0, 0, 0, 0)
                    row.setSpacing(12)
                    for field_spec in row_spec:
                        field_id = row_field_id(field_spec)
                        field = fields_by_id[field_id]
                        row.addWidget(
                            self._field_block(field, handles[field_id], box),
                            row_field_weight(field_spec),
                        )
                    form.addLayout(row)
                tab_layout.addWidget(box)
            tab_layout.addStretch(1)
            scroll = QScrollArea(tabs)
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setWidget(content)
            tabs.addTab(scroll, tab_spec["title"])
            pages.append(scroll)
        return pages

    def render(self, fields, handles, parent=None, *, layer="", layout=None):
        root = QWidget(parent)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(16)
        tabs = QTabWidget(root)
        self.populate_tabs(tabs, fields, handles, layer=layer, layout=layout)
        outer.addWidget(tabs)
        return root
