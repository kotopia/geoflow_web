"""Project-scoped GeoFlow settings dialog."""
from __future__ import annotations

from pathlib import Path

from qgis.PyQt.QtWidgets import QDialog, QMessageBox
from qgis.PyQt.uic import loadUi

from ..services.settings import GeoFlowSettingsService, SettingsValidationError
from .main_style import apply_main_style


class GeoFlowSettingsDialog(QDialog):
    def __init__(self, plugin, parent=None, *, settings_service=None):
        super().__init__(parent or plugin.iface.mainWindow())
        loadUi(str(Path(__file__).parent / "designer" / "settings.ui"), self)
        apply_main_style(self)
        self.plugin = plugin
        self.service = settings_service or GeoFlowSettingsService(plugin)
        self.project_id = ""
        self.defaultsButton.clicked.connect(self.load_defaults)
        self.cancelButton.clicked.connect(self.reject)
        self.saveButton.clicked.connect(self.save)
        self.reload()

    def reload(self):
        self.project_id = self.service.project_id()
        state = getattr(self.plugin, "integration_state", lambda: {})() or {}
        title = state.get("project_name") or state.get("project_code") or self.project_id
        self.projectLabel.setText(f"프로젝트: {title}")
        values = self.service.snapshot(self.project_id)
        self.defaultRadiusSpin.setValue(values["default_radius_m"])
        self.depthRadiusSpin.setValue(values["depth_radius_m"])
        self.manholeRadiusSpin.setValue(values["manhole_radius_m"])
        self.nearestFirstCheck.setChecked(values["nearest_first"])
        self.showNearbyCheck.setChecked(values["show_nearby_button"])
        self.showPreviousCheck.setChecked(values["show_previous_button"])
        self.showFieldActionsCheck.setChecked(values["show_field_action_buttons"])

    def load_defaults(self):
        self.defaultRadiusSpin.setValue(self.service.DEFAULT_RADIUS_M)
        self.depthRadiusSpin.setValue(self.service.DEFAULT_DEPTH_RADIUS_M)
        self.manholeRadiusSpin.setValue(self.service.DEFAULT_MANHOLE_RADIUS_M)
        self.nearestFirstCheck.setChecked(True)
        self.showNearbyCheck.setChecked(True)
        self.showPreviousCheck.setChecked(True)
        self.showFieldActionsCheck.setChecked(True)

    def save(self):
        try:
            self.service.save_nearby(
                default_radius_m=self.defaultRadiusSpin.value(),
                depth_radius_m=self.depthRadiusSpin.value(),
                manhole_radius_m=self.manholeRadiusSpin.value(),
                nearest_first=self.nearestFirstCheck.isChecked(),
                project_id=self.project_id,
            )
            self.service.save_form(
                show_nearby_button=self.showNearbyCheck.isChecked(),
                show_previous_button=self.showPreviousCheck.isChecked(),
                show_field_action_buttons=self.showFieldActionsCheck.isChecked(),
                project_id=self.project_id,
            )
        except SettingsValidationError as exc:
            QMessageBox.warning(self, "GeoFlow 환경설정", str(exc))
            return
        apply_form_preferences(self.plugin, self.service)
        self.accept()


def apply_form_preferences(plugin, service=None):
    service = service or GeoFlowSettingsService(plugin)
    work = getattr(plugin, "work", None)
    for page in (getattr(work, "pages", {}) or {}).values():
        page.form_actions.apply_preferences(service, page.project_id)
    controller = getattr(plugin, "edit_tools", None)
    if controller is not None:
        visible = service.show_field_action_buttons()
        for buttons in getattr(controller, "_depth_field_actions", {}).values():
            for button in buttons:
                button.setVisible(visible)
