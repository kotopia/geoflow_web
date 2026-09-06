from __future__ import annotations

from qgis.PyQt.QtCore import QSettings
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from .client import GeoFlowClientError, GeoFlowHttpClient


def _password_echo_mode():
    """Return the password echo enum for both Qt5/QGIS 3 and Qt6/QGIS 4."""
    echo_mode = getattr(QLineEdit, "EchoMode", None)
    if echo_mode is not None and hasattr(echo_mode, "Password"):
        return echo_mode.Password
    return QLineEdit.Password


class GeoFlowConnectorDialog(QDialog):
    def __init__(
        self,
        parent=None,
        *,
        on_open_project=None,
        on_sync=None,
        on_cache_pin_state=None,
        on_toggle_cache_pin=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("GeoFlow Connector")
        self.resize(680, 320)
        self.on_open_project = on_open_project
        self.on_sync = on_sync
        self.on_cache_pin_state = on_cache_pin_state
        self.on_toggle_cache_pin = on_toggle_cache_pin
        self.client = None
        self.projects = []
        self.sync_ready = False
        self.project_opened = False

        settings = QSettings()
        self.server_edit = QLineEdit(
            settings.value("GeoFlowConnector/serverUrl", "http://127.0.0.1:8000", type=str)
        )
        self.email_edit = QLineEdit(
            settings.value("GeoFlowConnector/email", "", type=str)
        )
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(_password_echo_mode())
        self.password_edit.setPlaceholderText("저장하지 않습니다")

        self.project_combo = QComboBox()
        self.project_combo.setEnabled(False)

        self.login_button = QPushButton("로그인 / 프로젝트 불러오기")
        self.open_button = QPushButton("선택 프로젝트 QGIS에 열기")
        self.open_button.setEnabled(False)
        self.sync_button = QPushButton("GeoFlow에 동기화")
        self.sync_button.setEnabled(False)
        self.cache_pin_button = QPushButton("현재 프로젝트 로컬 Snapshot 고정")
        self.cache_pin_button.setEnabled(False)
        self.cache_pin_button.setToolTip(
            "고정된 프로젝트의 로컬 GeoPackage Snapshot은 자동 캐시 정리에서 제외됩니다."
        )
        self.close_button = QPushButton("닫기")

        self.status_label = QLabel(
            "GeoFlow Server에 로그인하면 현재 계정에 허용된 GIS 프로젝트만 표시됩니다."
        )
        self.status_label.setWordWrap(True)

        form = QFormLayout()
        form.addRow("GeoFlow Server", self.server_edit)
        form.addRow("이메일", self.email_edit)
        form.addRow("비밀번호", self.password_edit)
        form.addRow("GIS 프로젝트", self.project_combo)

        buttons = QHBoxLayout()
        buttons.addWidget(self.login_button)
        buttons.addStretch(1)
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.sync_button)
        buttons.addWidget(self.close_button)

        cache_buttons = QHBoxLayout()
        cache_buttons.addStretch(1)
        cache_buttons.addWidget(self.cache_pin_button)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.status_label)
        layout.addLayout(cache_buttons)
        layout.addStretch(1)
        layout.addLayout(buttons)

        self.login_button.clicked.connect(self._login)
        self.open_button.clicked.connect(self._open_project)
        self.sync_button.clicked.connect(self._sync_project)
        self.cache_pin_button.clicked.connect(self._toggle_cache_pin)
        self.close_button.clicked.connect(self.close)

    def _set_busy(self, busy: bool):
        self.login_button.setEnabled(not busy)
        self.open_button.setEnabled(not busy and bool(self.projects))
        self.project_combo.setEnabled(not busy and bool(self.projects))
        self.sync_button.setEnabled(not busy and self.sync_ready)
        self.cache_pin_button.setEnabled(
            not busy
            and self.project_opened
            and callable(self.on_toggle_cache_pin)
        )

    def refresh_cache_pin_state(self):
        if not self.project_opened or not callable(self.on_cache_pin_state):
            self.cache_pin_button.setEnabled(False)
            self.cache_pin_button.setText("현재 프로젝트 로컬 Snapshot 고정")
            return
        try:
            pinned = bool(self.on_cache_pin_state())
        except Exception:
            pinned = False
        self.cache_pin_button.setText(
            "현재 프로젝트 로컬 Snapshot 고정 해제"
            if pinned
            else "현재 프로젝트 로컬 Snapshot 고정"
        )
        self.cache_pin_button.setEnabled(callable(self.on_toggle_cache_pin))

    def _toggle_cache_pin(self):
        if not self.project_opened or not callable(self.on_toggle_cache_pin):
            return
        try:
            self.on_toggle_cache_pin()
        finally:
            self.refresh_cache_pin_state()

    def _login(self):
        self.sync_ready = False
        self.project_opened = False
        self.refresh_cache_pin_state()
        self._set_busy(True)
        self.status_label.setText("GeoFlow 로그인 및 프로젝트 권한을 확인하는 중입니다…")
        try:
            client = GeoFlowHttpClient(self.server_edit.text())
            projects = client.login(self.email_edit.text(), self.password_edit.text())
        except GeoFlowClientError as exc:
            self.client = None
            self.projects = []
            self.project_combo.clear()
            self.status_label.setText(str(exc))
            QMessageBox.warning(self, "GeoFlow 로그인 실패", str(exc))
            self._set_busy(False)
            return

        self.client = client
        self.projects = projects
        self.project_combo.clear()
        for project in projects:
            code = project.get("code") or "코드 없음"
            name = project.get("name") or "프로젝트"
            caps = ", ".join(
                row.get("code", "") for row in (project.get("capabilities") or []) if row.get("code")
            )
            suffix = f" · {caps}" if caps else ""
            self.project_combo.addItem(f"{code} · {name}{suffix}", project)

        settings = QSettings()
        settings.setValue("GeoFlowConnector/serverUrl", self.server_edit.text().strip())
        settings.setValue("GeoFlowConnector/email", self.email_edit.text().strip().lower())
        self.password_edit.clear()

        if projects:
            self.status_label.setText(
                f"로그인 성공 · 접근 가능한 GIS 프로젝트 {len(projects)}개"
            )
        else:
            self.status_label.setText("로그인은 성공했지만 접근 가능한 GIS 프로젝트가 없습니다.")
        self._set_busy(False)

    def _open_project(self):
        if self.client is None or self.project_combo.currentIndex() < 0:
            return
        project = self.project_combo.currentData()
        manifest_url = project.get("manifest_url") if isinstance(project, dict) else None
        if not manifest_url:
            QMessageBox.warning(self, "GeoFlow", "QGIS manifest URL이 없습니다.")
            return

        self.sync_ready = False
        self.project_opened = False
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
        suffix = " · 서버 동기화 가능" if self.sync_ready else " · 로컬 저장만 가능"
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
