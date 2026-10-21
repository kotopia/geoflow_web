"""Project-scoped QGIS display CRS; feature storage geometry is untouched."""
from __future__ import annotations

from qgis.PyQt.QtCore import QEvent, QObject, QSettings, Qt
from qgis.PyQt.QtWidgets import QDialog
from qgis.core import QgsCoordinateReferenceSystem, QgsProject
from qgis.gui import QgsProjectionSelectionDialog


_KEY_PREFIX = "GeoFlowConnector/projectDisplayCrs/"


class ProjectCrsController(QObject):
    def __init__(self, plugin, project_label, crs_label, change_button):
        super().__init__(change_button)
        self.plugin = plugin
        self.project_label = project_label
        self.crs_label = crs_label
        self.change_button = change_button
        self.project_id = ""
        self.project_name = ""
        self._applying = False
        self.project_label.installEventFilter(self)
        change_button.clicked.connect(self.choose)
        QgsProject.instance().crsChanged.connect(self._crs_changed)
        self.deactivate()

    @staticmethod
    def _key(project_id: str) -> str:
        return _KEY_PREFIX + str(project_id)

    @staticmethod
    def _serialize(crs: QgsCoordinateReferenceSystem) -> str:
        return str(crs.authid() or ("WKT:" + crs.toWkt())) if crs.isValid() else ""

    @staticmethod
    def _deserialize(value: str) -> QgsCoordinateReferenceSystem:
        value = str(value or "")
        if value.startswith("WKT:"):
            return QgsCoordinateReferenceSystem.fromWkt(value[4:])
        return QgsCoordinateReferenceSystem(value)

    def activate(self, project_id: str, project_name: str) -> None:
        self.project_id = str(project_id or "")
        name = str(project_name or self.project_id)
        self.project_name = name
        self._render_project_name()
        self.project_label.setToolTip(name)
        self.change_button.setEnabled(bool(self.project_id))
        saved = str(QSettings().value(self._key(self.project_id), "") or "")
        restored = False
        if saved:
            crs = self._deserialize(saved)
            if crs.isValid():
                restored = True
                if crs != QgsProject.instance().crs():
                    self._applying = True
                    try:
                        QgsProject.instance().setCrs(crs)
                    finally:
                        self._applying = False
        if not restored:
            value = self._serialize(QgsProject.instance().crs())
            if value:
                settings = QSettings()
                settings.setValue(self._key(self.project_id), value)
                settings.sync()
        self._update_label()

    def deactivate(self) -> None:
        self.project_id = ""
        self.project_name = ""
        self.project_label.clear()
        self.project_label.setToolTip("")
        self.change_button.setEnabled(False)
        self._update_label()

    def choose(self) -> None:
        if not self.project_id:
            return
        dialog = QgsProjectionSelectionDialog(self.change_button)
        dialog.setWindowTitle("GeoFlow 프로젝트 표시 좌표계")
        dialog.setRequireValidSelection()
        current = QgsProject.instance().crs()
        if current.isValid():
            dialog.setCrs(current)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        crs = dialog.crs()
        if crs.isValid():
            QgsProject.instance().setCrs(crs)

    def _crs_changed(self, *args) -> None:
        self._update_label()
        if self.project_id and not self._applying:
            value = self._serialize(QgsProject.instance().crs())
            if value:
                settings = QSettings()
                settings.setValue(self._key(self.project_id), value)
                settings.sync()
        canvas = getattr(self.plugin.iface, "mapCanvas", lambda: None)()
        if canvas is not None:
            canvas.refresh()

    def _update_label(self) -> None:
        crs = QgsProject.instance().crs()
        text = str(crs.authid() or crs.description() or "설정 안 됨") if crs.isValid() else "설정 안 됨"
        self.crs_label.setText(text)
        self.crs_label.setToolTip(crs.description() if crs.isValid() else "")

    def _render_project_name(self) -> None:
        self.project_label.setText(self.project_name or "-")

    def eventFilter(self, watched, event):
        if watched is self.project_label and event.type() == QEvent.Type.Resize:
            self._render_project_name()
        return False

    def close(self) -> None:
        try:
            QgsProject.instance().crsChanged.disconnect(self._crs_changed)
        except (RuntimeError, TypeError):
            pass
