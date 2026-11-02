"""Expose a small dock entry that opens the modeless Survey work window."""
from pathlib import Path

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QToolButton
try:
    from qgis.PyQt.QtGui import QAction
except ImportError:
    from qgis.PyQt.QtWidgets import QAction


class SurveyIntegrationMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._survey_panel = None
        self._survey_action = None
        self._survey_button = None

    def initGui(self):
        super().initGui()
        self._survey_action = QAction("GeoFlow Survey", self.iface.mainWindow())
        self._survey_action.setIconText("Survey")
        self._survey_action.setObjectName("GeoFlowSurveyAction")
        self._survey_action.setIcon(QIcon(str(Path(__file__).resolve().parents[1]
                                            / "resources/icons/tabler/map-pin.svg")))
        self._survey_action.triggered.connect(self._show_survey)
        self.iface.addPluginToMenu("GeoFlow", self._survey_action)
        self.iface.addToolBarIcon(self._survey_action)
        self.integration_events.changed.connect(self._survey_state_changed)
        self._survey_state_changed()

    def _survey_state_changed(self):
        if self._survey_action is not None:
            self._survey_action.setToolTip(
                "Survey 목록 / CSV·XLSX Import" if self.integration_state().get("ready")
                else "Survey · 먼저 로그인하고 GeoFlow 프로젝트를 여세요.")
        if self._survey_panel is not None:
            self._survey_panel.reset_scope()

    def _ensure_ui(self):
        super()._ensure_ui()
        if self._survey_button is None:
            root = self.presentation.root
            self._survey_button = QToolButton(root.rail)
            self._survey_button.setObjectName("GeoFlowRail_survey")
            self._survey_button.setDefaultAction(self._survey_action)
            self._survey_button.setText("Survey")
            self._survey_button.setAccessibleName("GeoFlow Survey")
            self._survey_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            self._survey_button.setFixedSize(38, 34)
            project_index = root.rail_layout.indexOf(root.GeoFlowRail_projects)
            root.rail_layout.insertWidget(project_index + 1, self._survey_button)
            root.moreActionsButton.menu().addAction(self._survey_action)

    def _show_survey(self):
        if not self.integration_state().get("ready"):
            self.run()
            self.iface.messageBar().pushMessage(
                "GeoFlow Survey", "로그인 후 GeoFlow 프로젝트를 열고 Survey를 선택하세요.", duration=8)
            return
        self._ensure_ui()
        if self._survey_panel is None:
            from ..ui.survey_panel import SurveyPanel
            self._survey_panel = SurveyPanel(self, self.iface.mainWindow())
        self._survey_panel.reset_scope()
        self._survey_panel.show()
        self._survey_panel.raise_()
        self._survey_panel.activateWindow()

    def _sync_active_project(self, client, automatic=False):
        result = super()._sync_active_project(client, automatic=automatic)
        if (isinstance(result, dict) and result.get('ok') is True
                and client is self.active_client and not self._sync_in_progress):
            if self._survey_panel is not None:
                try:
                    self._survey_panel.refresh_creation_states()
                except RuntimeError:
                    pass  # A closing popup must not turn a successful sync into a failure.
        return result

    def unload(self):
        if self._survey_button is not None:
            self._survey_button.deleteLater()
            self._survey_button = None
        if self._survey_action is not None:
            self.integration_events.changed.disconnect(self._survey_state_changed)
            self.iface.removePluginMenu("GeoFlow", self._survey_action)
            self.iface.removeToolBarIcon(self._survey_action)
            self._survey_action.deleteLater()
            self._survey_action = None
        if self._survey_panel is not None:
            self._survey_panel.close_service()
            self._survey_panel.close()
            self._survey_panel.deleteLater()
            self._survey_panel = None
        super().unload()
