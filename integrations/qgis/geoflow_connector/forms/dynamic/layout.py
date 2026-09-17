"""Generic tab/section renderer for central layout metadata."""
from __future__ import annotations

from collections import OrderedDict

from qgis.PyQt.QtWidgets import QFormLayout, QGroupBox, QTabWidget, QVBoxLayout, QWidget


def _name(field, key, default):
    value = (field.get("layout") or {}).get(key)
    return str(value or default).strip()


class LayoutRenderer:
    def render(self, fields, handles, parent=None):
        root = QWidget(parent)
        outer = QVBoxLayout(root)
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
            for section_name, rows in sections.items():
                box = QGroupBox(section_name, tab)
                form = QFormLayout(box)
                for field in rows:
                    label = field["label"] + (" *" if field.get("required") else "")
                    form.addRow(label, handles[field["id"]].widget)
                tab_layout.addWidget(box)
            tab_layout.addStretch(1)
            tabs.addTab(tab, tab_name)
        outer.addWidget(tabs)
        return root
