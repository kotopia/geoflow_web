"""Compact project information popup for the main GeoFlow panel."""
from pathlib import Path

from qgis.PyQt.QtCore import QPoint, Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.uic import loadUi

from .main_style import apply_main_style


class ProjectInfoPopup:
    def __init__(self, plugin, button):
        self.plugin = plugin
        self.button = button
        self.button.setIcon(QIcon(":/geoflow/tabler/info-circle.svg"))
        self.popup = loadUi(str(
            Path(__file__).parent / "designer" / "project_info_popup.ui"
        ))
        apply_main_style(self.popup)
        self.popup.setParent(
            plugin.iface.mainWindow(), Qt.WindowType.Popup
        )
        self.popup.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        button.clicked.connect(self.toggle)

    @property
    def project_label(self):
        return self.popup.projectNameLabel

    @property
    def crs_label(self):
        return self.popup.projectCrsLabel

    @property
    def crs_button(self):
        return self.popup.projectCrsButton

    def set_user(self, value):
        self.popup.userValueLabel.setText(str(value or "-"))

    def toggle(self):
        if self.popup.isVisible():
            self.popup.hide()
            return
        self.popup.adjustSize()
        anchor = self.button.mapToGlobal(QPoint(
            self.button.width() - self.popup.width(), self.button.height()
        ))
        self.popup.move(anchor)
        self.popup.show()
        self.popup.raise_()

    def close(self):
        self.popup.close()
        self.popup.deleteLater()
