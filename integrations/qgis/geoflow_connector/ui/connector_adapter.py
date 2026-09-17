# 제목: ui/connector_adapter.py
# 기능: 현재 통합 플러그인의 workspace·선택 신호를 기존 업무폼에 전달
"""Only bridge to the loaded Connector; no authentication or persistence here."""
from qgis.PyQt.QtCore import QObject, pyqtSignal
# Dependency is injected by the owning single plugin.


MAPPING_NOTICE = ('1차 연결: 필드 형식·NULL·필수값·속성코드·사진 API 매핑이 검증되지 않아 '
                  '저장할 수 없습니다. 원본 입력 조건만 사용할 수 있으며 기존 객체 속성은 채우지 않습니다.')


def load_codeList(table_name, class_name):
    """Legacy code domains are deliberately unresolved, never fetched from DB."""
    return []


class IntegrationEvents(QObject):
    changed = pyqtSignal()


class ConnectorAdapter(QObject):
    changed = pyqtSignal()
    selectionChanged = pyqtSignal(str)
    objectSelected = pyqtSignal(str, object)

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.service = parent.plugin
        self.closed = False
        self._workspace_connector = None
        self._workspace_host = None
        self._workspace_signals = []
        key = '_geoflow_integration_events_v1'
        bus = getattr(iface, key, None)
        if bus is None:
            bus = IntegrationEvents(iface.mainWindow())
            setattr(iface, key, bus)
        self.bus = bus
        self.bus.changed.connect(self._changed)

    def _changed(self):
        if not self.closed:
            self.changed.emit()

    def connector(self):
        return None if self.closed else self.service

    def state(self):
        connector = self.connector()
        empty = dict(available=False, authenticated=False, ready=False, can_write=False,
                     project_id='', project_name='', project_code='', layers=(), epoch=0)
        if connector is None:
            return empty
        if getattr(connector, 'integration_api_version', None) != 2:
            return dict(empty, upgrade_required=True)
        state = connector.integration_state()
        # Instance identity prevents rebinding drafts after Connector reload.
        return dict(state, instance=id(connector))

    def layers(self, state=None):
        state = state if state is not None else self.state()
        if not state['ready']:
            return {}
        grouped = {}
        for layer in state['layers']:
            key = str(layer.customProperty('geoflow/standard_name', ''))
            grouped.setdefault(key, []).append(layer)
        # Ambiguous standards are not safe bindings.
        return {key: layers[0] for key, layers in grouped.items() if len(layers) == 1}

    def open_connector(self):
        connector = self.connector()
        if connector is not None:
            connector.run()

    def attach_workspace(self, host):
        connector = self.connector()
        if connector is None or getattr(connector, 'integration_api_version', None) != 2 or not connector.integration_state()['available']:
            self.detach_workspace()
            return None
        if self._workspace_connector is connector:
            return None  # Already mounted; do not add a widget twice.
        self.detach_workspace()
        panel = connector.acquire_layer_workspace(host)
        if panel is None:
            return None
        self._workspace_connector = connector
        self._workspace_host = host
        selection, objects = connector.workspace_signals()
        self._workspace_signals = [(selection, self.selectionChanged.emit), (objects, self.objectSelected.emit)]
        for signal, slot in self._workspace_signals:
            signal.connect(slot)
        return panel

    def detach_workspace(self):
        for signal, slot in self._workspace_signals:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._workspace_signals.clear()
        if self._workspace_connector is not None:
            self._workspace_connector.release_layer_workspace(self._workspace_host)
        self._workspace_connector = None
        self._workspace_host = None

    def selected_layer_id(self):
        return self._workspace_connector.selected_layer_id() if self._workspace_connector is not None else ''

    def select_layer(self, layer_id):
        return bool(self._workspace_connector is not None and self._workspace_connector.select_workspace_layer(layer_id))

    def zoom_selected(self):
        if self._workspace_connector is not None:
            self._workspace_connector.zoom_workspace_layer()

    def layers_by_id(self, state=None):
        state = state if state is not None else self.state()
        return {layer.id(): layer for layer in state['layers']} if state['ready'] else {}

    def close(self):
        if self.closed:
            return
        self.detach_workspace()
        self.closed = True
        self.bus.changed.disconnect(self._changed)
