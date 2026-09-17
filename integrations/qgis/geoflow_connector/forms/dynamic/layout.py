"""Generic tab/section renderer for central layout metadata."""
from __future__ import annotations

from collections import OrderedDict

from qgis.PyQt.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QTabWidget, QVBoxLayout, QWidget,
)


def _name(field, key, default):
    value = (field.get("layout") or {}).get(key)
    return str(value or default).strip()


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

    def render(self, fields, handles, parent=None):
        root = QWidget(parent)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(16)
        tabs = QTabWidget(root)
        grouped = OrderedDict()
        for field in fields:
            if not field.get("visible", True) or field.get("widget_type") == "hidden":
                continue
            tab = _name(field, "tab", "기본 정보")
            section = _name(field, "section", "속성")
            grouped.setdefault(tab, OrderedDict()).setdefault(section, []).append(field)
        for tab_name, sections in grouped.items():
            tab = QWidget(tabs)
            tab_layout = QVBoxLayout(tab)
            tab_layout.setContentsMargins(4, 4, 4, 4)
            tab_layout.setSpacing(16)
            for section_name, rows in sections.items():
                box = QGroupBox(section_name, tab)
                form = QVBoxLayout(box)
                form.setContentsMargins(10, 12, 10, 10)
                form.setSpacing(12)
                for field in rows:
                    form.addWidget(self._field_block(field, handles[field["id"]], box))
                tab_layout.addWidget(box)
            tab_layout.addStretch(1)
            tabs.addTab(tab, tab_name)
        outer.addWidget(tabs)
        return root
