# 제목: api/references.py
# 기능: 프로젝트·세션별 비동기 참조코드 catalog 캐시 및 바인딩 해석
"""One asynchronous, session/project-scoped reference catalog for the plugin."""
from urllib.parse import urljoin, urlsplit
from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.core import QgsApplication, QgsTask
from ..layers.model import reference_groups, layer_reference_bindings


def field_options(catalog, standard, definition):
    return resolve_field_reference(catalog, standard, definition)['options']


def resolve_field_reference(catalog, standard, definition):
    """Resolve only received groups; an explicitly empty group is authoritative."""
    name = definition['name']
    binding = next((b for b in layer_reference_bindings(catalog, standard) if b.get('field_name') == name), {})
    groups = reference_groups(catalog)
    keys = dict(binding_key=binding.get('code_group_key'),
                definition_key=definition.get('code_group_key'))
    denied = any(row.get('editable') is False or row.get('readonly') is True
                 or row.get('visible') is False for row in (binding, definition))
    selected = None
    source = None
    for candidate in ('binding_key', 'definition_key'):
        if keys[candidate] and keys[candidate] in groups:
            selected, source = keys[candidate], candidate
            break
    missing = [keys[k] for k in ('binding_key', 'definition_key') if keys[k] and keys[k] not in groups]
    return dict(**keys, selected_key=selected, selected_source=source,
                candidate_present={k: bool(v and v in groups) for k, v in keys.items()},
                missing_server_keys=missing, local_fallback=False,
                permission_denied=denied, definition_required=not any(keys.values()),
                received_code_count=len(groups.get(selected, [])),
                options=[] if denied else groups.get(selected, []))


def normalize_catalog(payload):
    if not isinstance(payload, dict) or payload.get('ok') is not True:
        raise ValueError('invalid_reference_response')
    if not isinstance(payload.get('groups'), list) or not isinstance(payload.get('bindings', []), list):
        raise ValueError('invalid_reference_response')
    groups = []
    seen_groups = set()
    for group in payload['groups']:
        key = group.get('code_group_key') or group.get('group_key')
        if not isinstance(key, str) or not key or key in seen_groups:
            raise ValueError('invalid_reference_group')
        seen_groups.add(key)
        values = []
        seen = set()
        for row in group.get('values', []):
            code, label = row.get('code'), row.get('label')
            if not isinstance(code, str) or not isinstance(label, str) or code in seen:
                raise ValueError('invalid_reference_value')
            seen.add(code)
            values.append(dict(code=code, label=label, sort_order=int(row.get('sort_order') or 0)))
        values.sort(key=lambda row: (row['sort_order'], row['code']))
        groups.append(dict(code_group_key=key, values=values))
    bindings = payload.get('bindings', [])
    if any(not isinstance(row, dict) or not all(isinstance(row.get(key), str)
            for key in ('standard_name', 'field_name', 'code_group_key')) for row in bindings):
        raise ValueError('invalid_reference_binding')
    workers = payload.get('workers', [])
    if not isinstance(workers, list) or any(not isinstance(w, dict) or not isinstance(w.get('id'), str) or not isinstance(w.get('resolved'), bool) for w in workers):
        raise ValueError('invalid_worker_response')
    current = payload.get('current_user')
    return dict(ok=True, groups=groups, bindings=bindings, workers=workers,
                current_user=current if isinstance(current, dict) else {})


class ReferenceService(QObject):
    changed = pyqtSignal()

    def __init__(self, parent=None, submit=None):
        super().__init__(parent)
        self._submit = submit or self._submit_task
        self._task = None
        self._generation = 0
        self.scope = None
        self.client = None
        self.url = ''
        self.state = 'idle'
        self.catalog = {'bindings': [], 'groups': []}
        self.error = ''

    @staticmethod
    def _submit_task(work, done):
        task = QgsTask.fromFunction('GeoFlow 참조코드', lambda task: work(), on_finished=done)
        QgsApplication.taskManager().addTask(task)
        return task

    def clear(self):
        self._generation += 1
        if self._task is not None:
            self._task.cancel()
        self._task = None
        self.scope = self.client = None
        self.url = ''
        self.catalog = {'bindings': [], 'groups': []}
        self.state, self.error = 'idle', ''
        self.changed.emit()

    def open(self, manifest, client):
        project_id = str((manifest.get('project') or {}).get('id') or '')
        url = str((manifest.get('transport') or {}).get('reference_catalog_url') or '')
        scope = (id(client), client.base_url, project_id)
        if self.scope == scope and self.url == url and self.state in ('loading', 'ready'):
            return
        self.clear()
        self.scope, self.client, self.url = scope, client, url
        if not project_id or not url:
            self.state, self.error = 'unavailable', '프로젝트 참조코드 API 주소가 없습니다.'
            self.changed.emit()
            return
        self.refresh()

    def refresh(self):
        if self.client is None or not self.url:
            return
        # Reject cross-origin catalog URLs before copying authentication.
        base = urlsplit(self.client.base_url)
        target = urlsplit(urljoin(self.client.base_url+'/', self.url))
        if (base.scheme, base.netloc) != (target.scheme, target.netloc):
            self.state, self.error = 'error', '참조코드 API 주소의 서버가 다릅니다.'
            self.changed.emit()
            return
        self._generation += 1
        generation, scope = self._generation, self.scope
        if self._task is not None:
            self._task.cancel()
        session = self.client.readonly_session_copy()
        url = self.url
        self.state, self.error = 'loading', ''
        self.changed.emit()

        def complete(error, payload=None):
            # QgsTask.on_finished runs on the main thread, even if cancelled work
            # completes later. No widget or live client is accessed by work().
            if generation != self._generation or scope != self.scope:
                return
            self._task = None
            if error is None:
                try:
                    payload = normalize_catalog(payload)
                except Exception:
                    error = ValueError('invalid_reference_response')
            if error is not None:
                self.state = 'error'
                self.error = '참조코드 조회 실패 · 기존 값과 미저장 입력을 보존했습니다.'
                self.changed.emit()
                if getattr(error, 'http_status', None) in (401, 403):
                    callback = getattr(self.client, 'on_access_lost', None)
                    if callback:
                        callback()
                return
            self.catalog = payload
            self.state, self.error = 'ready', ''
            self.changed.emit()

        try:
            self._task = self._submit(lambda: session.get_json(url), complete)
        except Exception as error:
            complete(error)

    def diagnostic(self):
        """No session IDs, cookies, URLs or feature records in diagnostic output."""
        keys = set(reference_groups(self.catalog))
        return dict(state=self.state, group_count=len(keys),
                    binding_count=len(self.catalog.get('bindings', [])),
                    missing_groups=[])
