# 제목: ui/dialog.py
# 기능: 로그인과 프로젝트 선택 UI, 세션 및 연결 상태 처리
from __future__ import annotations

from pathlib import Path
from qgis.PyQt.uic import loadUi
from qgis.PyQt.QtCore import QSettings, Qt, QEvent, QTimer
from qgis.PyQt.QtWidgets import (
    QListWidgetItem,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..api.client import GeoFlowClientError, GeoFlowHttpClient
from ..api.defaults import PRODUCTION_SERVER_URL, migrate_legacy_connection_defaults


def _password_echo_mode():
    """Return the password echo enum for both Qt5/QGIS 3 and Qt6/QGIS 4."""
    echo_mode = getattr(QLineEdit, "EchoMode", None)
    if echo_mode is not None and hasattr(echo_mode, "Password"):
        return echo_mode.Password
    return QLineEdit.Password


# ============================================================
# 로그인과 프로젝트 선택 화면
# ============================================================
class GeoFlowConnectorDialog(QDialog):
    def __init__(
        self,
        parent=None,
        *,
        on_open_project=None,
        on_sync=None,
        on_session_changing=None,
        on_state_changed=None,
        on_cache_pin_state=None,
        on_toggle_cache_pin=None,
    ):
        super().__init__(parent)
        ui_dir = Path(__file__).resolve().parents[1] / "ui" / "designer"
        loadUi(str(ui_dir / "login.ui"), self)
        # Status output is optional in Designer, but session handlers need a sink.
        # Do not reuse decorative labels or replace the user's custom layout.
        if not hasattr(self, 'status_label'):
            self.status_label = QLabel(self)
            self.status_label.setObjectName('status_label')
            self.layout().addWidget(self.status_label)
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.on_open_project = on_open_project
        self.on_sync = on_sync
        self.on_session_changing = on_session_changing
        self.on_state_changed = on_state_changed
        self.on_cache_pin_state = on_cache_pin_state
        self.on_toggle_cache_pin = on_toggle_cache_pin
        self.client = None
        self.projects = []
        self.sync_ready = False
        self.project_opened = False

        settings = QSettings()
        stored_server = settings.value(
            "GeoFlowConnector/serverUrl", PRODUCTION_SERVER_URL, type=str
        )
        stored_email = settings.value("GeoFlowConnector/email", "", type=str)
        server_url, email = migrate_legacy_connection_defaults(
            stored_server,
            stored_email,
        )
        if server_url != stored_server:
            settings.setValue("GeoFlowConnector/serverUrl", server_url)
        if email != stored_email:
            settings.setValue("GeoFlowConnector/email", email)
        self.server_url = server_url
        self.server_label.setTextFormat(Qt.TextFormat.PlainText)
        self.server_label.setText(self.server_url)
        self.email_edit.setText(email)
        self.project_panel = loadUi(str(ui_dir / "project_selection.ui"))
        for name in ('project_list', 'open_button', 'sync_button', 'cache_pin_button', 'refresh_button'):
            setattr(self, name, getattr(self.project_panel, name))

        from .project_name_delegate import ProjectNameDelegate
        self.project_list.setItemDelegate(ProjectNameDelegate(self.project_list))
        self.project_list.viewport().installEventFilter(self)
        self.login_button.clicked.connect(self._login)
        self.open_button.clicked.connect(self._open_project)
        self.sync_button.clicked.connect(self._sync_project)
        self.cache_pin_button.clicked.connect(self._toggle_cache_pin)
        self.close_button.clicked.connect(self.close)

    def set_projects(self, projects):
        previous = self.selected_project()
        previous_id = previous.get('id') if previous else None
        self.projects = projects
        self.project_list.clear()
        selected = 0
        for index, project in enumerate(projects):
            item = QListWidgetItem(f"[{project.get('code') or ''}] {project.get('name') or ''}")
            item.setData(Qt.ItemDataRole.UserRole, project)
            self.project_list.addItem(item)
            if previous_id and project.get('id') == previous_id:
                selected = index
        if projects:
            self.project_list.setCurrentRow(selected)

    def selected_project(self):
        item = self.project_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def eventFilter(self, watched, event):
        if (watched is self.project_list.viewport()
                and event.type() == QEvent.Type.MouseButtonDblClick
                and event.button() == Qt.MouseButton.LeftButton):
            item = self.project_list.itemAt(event.position().toPoint())
            if item is not None and self.project_list.isEnabled() and self.open_button.isEnabled():
                self.project_list.setCurrentItem(item)
                # Open after mouse dispatch, before replacing the project UI.
                QTimer.singleShot(0, self.open_button.click)
            return True
        return super().eventFilter(watched, event)

    def _set_busy(self, busy: bool):
        self.login_button.setEnabled(not busy)
        self.open_button.setEnabled(not busy and bool(self.projects))
        self.project_list.setEnabled(not busy and bool(self.projects))
        self.sync_button.setEnabled(not busy and self.sync_ready)
        self.cache_pin_button.setEnabled(
            not busy
            and self.project_opened
            and callable(self.on_toggle_cache_pin)
        )

    def refresh_cache_pin_state(self):
        if not self.project_opened or not callable(self.on_cache_pin_state):
            self.cache_pin_button.setChecked(False)
            self.cache_pin_button.setEnabled(False)
            self.cache_pin_button.setToolTip("현재 프로젝트 로컬 Snapshot 고정")
            return
        try:
            pinned = bool(self.on_cache_pin_state())
        except Exception:
            pinned = False
        self.cache_pin_button.setToolTip(
            "현재 프로젝트 로컬 Snapshot 고정 해제"
            if pinned
            else "현재 프로젝트 로컬 Snapshot 고정"
        )
        self.cache_pin_button.setChecked(pinned)
        self.cache_pin_button.setEnabled(callable(self.on_toggle_cache_pin))

    def _toggle_cache_pin(self):
        if not self.project_opened or not callable(self.on_toggle_cache_pin):
            return
        try:
            self.on_toggle_cache_pin()
        finally:
            self.refresh_cache_pin_state()

    def _notify_state(self):
        if self.on_state_changed:
            self.on_state_changed()

    def clear_session(self, *, clear_password=True):
        if self.client is not None:
            self.client.on_access_lost = None
        self.client = None
        self.projects = []
        self.project_opened = False
        self.sync_ready = False
        if clear_password:
            self.password_edit.clear()
        self.project_list.clear()
        self._set_busy(False)
        self.refresh_cache_pin_state()
        if self.on_session_changing:
            self.on_session_changing()
        self.status_label.setText('로그아웃됨 · QGIS 미저장 편집과 오프라인 큐는 유지됩니다.')
        self._notify_state()

    def _login(self):
        self.clear_session(clear_password=False)
        self.sync_ready = False
        self.project_opened = False
        self._notify_state()
        self.refresh_cache_pin_state()
        self._set_busy(True)
        self.status_label.setText("GeoFlow 로그인 및 프로젝트 권한을 확인하는 중입니다…")
        try:
            client = GeoFlowHttpClient(self.server_url)
            projects = client.login(self.email_edit.text(), self.password_edit.text())
        except GeoFlowClientError as exc:
            self.password_edit.clear()
            self.client = None
            self.projects = []
            self.project_list.clear()
            self.status_label.setText(str(exc))
            QMessageBox.warning(self, "GeoFlow 로그인 실패", str(exc))
            self._set_busy(False)
            return

        client.on_access_lost = self.clear_session
        self.client = client
        self.projects = projects
        self.set_projects(projects)

        settings = QSettings()
        settings.setValue("GeoFlowConnector/serverUrl", self.server_url)
        settings.setValue("GeoFlowConnector/email", self.email_edit.text().strip().lower())
        self.password_edit.clear()

        if projects:
            self.status_label.setText(
                f"로그인 성공 · 접근 가능한 GIS 프로젝트 {len(projects)}개"
            )
        else:
            self.status_label.setText("로그인은 성공했지만 접근 가능한 GIS 프로젝트가 없습니다.")
        self._set_busy(False)
        self._notify_state()

    def _open_project(self):
        if self.client is None or self.project_list.currentRow() < 0:
            return
        project = self.selected_project()
        manifest_url = project.get("manifest_url") if isinstance(project, dict) else None
        if not manifest_url:
            QMessageBox.warning(self, "GeoFlow", "QGIS manifest URL이 없습니다.")
            return

        self.sync_ready = False
        self.project_opened = False
        self._notify_state()
        self.refresh_cache_pin_state()
        self._set_busy(True)
        self.status_label.setText("Layer Plan 확인 후 프로젝트 GeoPackage를 준비하는 중입니다…")
        try:
            manifest = self.client.get_json(manifest_url)
            if self.on_open_project is None:
                raise GeoFlowClientError("QGIS project materializer is unavailable.")
            result = self.on_open_project(manifest, self.client)
            if isinstance(result, dict):
                loaded = int(result.get("loaded") or 0)
                self.sync_ready = bool(result.get("sync_supported"))
            else:
                loaded = int(result or 0)
                self.sync_ready = False
        except Exception as exc:
            self.status_label.setText(str(exc))
            QMessageBox.critical(self, "GeoFlow 프로젝트 열기 실패", str(exc))
            self._set_busy(False)
            return

        self.project_opened = True
        self._notify_state()
        suffix = (
            " · 저장 즉시 서버 자동 동기화"
            if self.sync_ready
            else " · 서버 동기화 비활성 · 편집 불가"
        )
        self.status_label.setText(f"QGIS GeoPackage 구성 완료 · 레이어 {loaded}개{suffix}")
        self._set_busy(False)
        self.refresh_cache_pin_state()

    def _sync_project(self):
        if self.client is None or not self.sync_ready or self.on_sync is None:
            return
        self._set_busy(True)
        self.status_label.setText("QGIS 변경사항을 GeoFlow Server와 비교·동기화하는 중입니다…")
        try:
            result = self.on_sync(self.client)
        except Exception as exc:
            self.status_label.setText(str(exc))
            QMessageBox.critical(self, "GeoFlow 동기화 실패", str(exc))
            self._set_busy(False)
            return

        created = int(result.get("created") or 0)
        updated = int(result.get("updated") or 0)
        deleted = int(result.get("deleted") or 0)
        self.status_label.setText(
            f"GeoFlow 동기화 완료 · 신규 {created} · 수정 {updated} · 삭제 {deleted} · 기준선 갱신 완료"
        )
        QMessageBox.information(
            self,
            "GeoFlow 동기화 완료",
            f"신규 {created}건\n수정 {updated}건\n삭제 {deleted}건\n\n현재 GeoPackage 기준선이 갱신되었습니다.",
        )
        self.sync_ready = True
        self._set_busy(False)
