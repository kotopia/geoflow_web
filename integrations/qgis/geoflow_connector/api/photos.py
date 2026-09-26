"""Revision-aware project photo policy loader for the QGIS client."""
import json
from urllib.parse import urljoin, urlsplit

from qgis.PyQt.QtCore import QObject, QSettings, pyqtSignal
from qgis.core import QgsApplication, QgsMessageLog, QgsTask, Qgis


def _log(message):
    QgsMessageLog.logMessage("photo_policy " + str(message), "GeoFlow", Qgis.MessageLevel.Info)


class PhotoPolicyService(QObject):
    changed = pyqtSignal()
    CACHE_PREFIX = "GeoFlowConnector/photoPolicies/"

    def __init__(self, parent=None, submit=None):
        super().__init__(parent)
        self._submit = submit or self._submit_task
        self._task = None
        self._generation = 0
        self.client = None
        self.project_id = self.revision = self.url = ""
        self.state, self.error = "idle", ""
        self.payload = {"layers": []}

    @staticmethod
    def _submit_task(work, done):
        task = QgsTask.fromFunction("GeoFlow 사진 정책", lambda task: work(), on_finished=done)
        QgsApplication.taskManager().addTask(task)
        return task

    def clear(self):
        self._generation += 1
        if self._task is not None:
            self._task.cancel()
        self._task = None
        self.client = None
        self.project_id = self.revision = self.url = ""
        self.state, self.error = "idle", ""
        self.payload = {"layers": []}
        self.changed.emit()

    def _cache_key(self):
        return self.CACHE_PREFIX + self.project_id + "/" + self.revision

    def open(self, manifest, client):
        project_id = str((manifest.get("project") or {}).get("id") or "")
        revision = str(manifest.get("photo_policy_revision") or "")
        url = str(manifest.get("photo_policy_url") or "")
        if (self.client is client and self.project_id == project_id and
                self.revision == revision and self.url == url and self.state in {"loading", "ready"}):
            return
        self.clear()
        self.client, self.project_id, self.revision, self.url = client, project_id, revision, url
        _log(f"open project_id={project_id} revision={revision} url={url or '-'}")
        if not project_id or not revision or not url:
            self.state, self.error = "unavailable", "이 프로젝트에는 사진 정책이 없습니다."
            self.changed.emit()
            return
        cached = QSettings().value(self._cache_key(), "")
        try:
            cached = json.loads(str(cached)) if cached else None
        except (TypeError, ValueError):
            cached = None
        if isinstance(cached, dict) and cached.get("photo_policy_revision") == revision:
            self.payload, self.state = cached, "ready"
            _log(f"cache_ready revision={revision} layers={len(cached.get('layers') or [])}")
            self.changed.emit()
            return
        self.refresh()

    def refresh(self):
        if self.client is None or not self.url or not self.revision:
            return
        base, target = urlsplit(self.client.base_url), urlsplit(urljoin(self.client.base_url + "/", self.url))
        if (base.scheme, base.netloc) != (target.scheme, target.netloc):
            self.state, self.error = "error", "사진 정책 API 주소의 서버가 다릅니다."
            self.changed.emit()
            return
        self._generation += 1
        generation = self._generation
        session, url, revision = self.client.readonly_session_copy(), self.url, self.revision
        self.state, self.error = "loading", ""
        self.changed.emit()

        def complete(error, payload=None):
            if generation != self._generation:
                return
            self._task = None
            if error is None and (not isinstance(payload, dict) or not payload.get("ok") or
                                  str(payload.get("photo_policy_revision") or "") != revision):
                error = ValueError("photo_policy_revision_mismatch")
            if error is not None:
                self.state, self.error = "error", "사진 정책을 불러오지 못했습니다. 기존 편집 내용은 보존됩니다."
                _log(f"fetch_error revision={revision} error={type(error).__name__}")
            else:
                self.payload, self.state = payload, "ready"
                QSettings().setValue(self._cache_key(), json.dumps(payload, ensure_ascii=False))
                _log(f"fetch_ready revision={revision} layers={len(payload.get('layers') or [])}")
            self.changed.emit()

        try:
            self._task = self._submit(lambda: session.get_json(url), complete)
        except Exception as error:
            complete(error)

    def policy(self, layer_definition_id):
        layer_id = str(layer_definition_id or "")
        row = next((row for row in self.payload.get("layers", [])
                    if str(row.get("layer_id") or "") == layer_id), None)
        _log(f"lookup state={self.state} layer_id={layer_id or '-'} found={'yes' if row else 'no'}")
        return (row or {}).get("policy")
