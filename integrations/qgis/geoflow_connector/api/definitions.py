"""Asynchronous loader for the server-authoritative Final Form Definition."""
from urllib.parse import urljoin, urlsplit

from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.core import QgsApplication, QgsTask

from ..forms.dynamic.contract import normalize_definition


class DefinitionService(QObject):
    changed = pyqtSignal()

    def __init__(self, parent=None, submit=None):
        super().__init__(parent)
        self._submit = submit or self._submit_task
        self._task = None
        self._generation = 0
        self.scope = None
        self.client = None
        self.url = ""
        self.state = "idle"
        self.definition = {"fields": [], "rules": []}
        self.error = ""

    @staticmethod
    def _submit_task(work, done):
        task = QgsTask.fromFunction("GeoFlow 중앙 업무폼", lambda task: work(), on_finished=done)
        QgsApplication.taskManager().addTask(task)
        return task

    def clear(self):
        self._generation += 1
        if self._task is not None:
            self._task.cancel()
        self._task = None
        self.scope = self.client = None
        self.url = ""
        self.state, self.error = "idle", ""
        self.definition = {"fields": [], "rules": []}
        self.changed.emit()

    def open(self, manifest, client):
        project_id = str((manifest.get("project") or {}).get("id") or "")
        transport = manifest.get("transport") or {}
        url = str(transport.get("form_definition_url") or "")
        revision = str(transport.get("form_definition_revision")
                       or (manifest.get("definition") or {}).get("revision") or "")
        scope = (id(client), client.base_url, project_id, revision)
        if self.scope == scope and self.url == url and self.state in {"loading", "ready"}:
            return
        self.clear()
        self.scope, self.client, self.url = scope, client, url
        if not project_id or not url or not revision:
            self.state, self.error = "error", "중앙 Final Form Definition 주소 또는 revision이 없습니다."
            self.changed.emit()
            return
        self.refresh()

    def refresh(self):
        if self.client is None or not self.url:
            return
        base = urlsplit(self.client.base_url)
        target = urlsplit(urljoin(self.client.base_url + "/", self.url))
        if (base.scheme, base.netloc) != (target.scheme, target.netloc):
            self.state, self.error = "error", "Final Form Definition API 주소의 서버가 다릅니다."
            self.changed.emit()
            return
        self._generation += 1
        generation, scope = self._generation, self.scope
        if self._task is not None:
            self._task.cancel()
        session, url = self.client.readonly_session_copy(), self.url
        self.state, self.error = "loading", ""
        self.changed.emit()

        def complete(error, payload=None):
            if generation != self._generation or scope != self.scope:
                return
            self._task = None
            if error is None:
                try:
                    payload = normalize_definition(payload)
                    if payload["revision"] != scope[3]:
                        raise ValueError("definition_revision_mismatch")
                except Exception as exc:
                    error = exc
            if error is not None:
                self.state = "error"
                self.error = "중앙 업무정의 조회 실패 · 기존 입력과 편집 버퍼를 보존했습니다."
                self.changed.emit()
                if getattr(error, "http_status", None) in (401, 403):
                    callback = getattr(self.client, "on_access_lost", None)
                    if callback:
                        callback()
                return
            self.definition = payload
            self.state, self.error = "ready", ""
            self.changed.emit()

        try:
            self._task = self._submit(lambda: session.get_json(url), complete)
        except Exception as error:
            complete(error)
