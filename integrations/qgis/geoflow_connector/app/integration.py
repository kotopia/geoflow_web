# 제목: app/integration.py
# 기능: 플러그인 내부 상태·레이어·선택 이벤트와 workspace 소유권 연결
"""Version 1 local UI integration. Never exports clients, tokens or manifests."""
from qgis.PyQt.QtCore import QObject, pyqtSignal, QTimer
from qgis.core import QgsProject
from qgis.PyQt import sip


class IntegrationEvents(QObject):
    changed = pyqtSignal()


def integration_events(iface):
    # Lifetime belongs to QGIS, so either plugin can be loaded first/reloaded.
    key = '_geoflow_integration_events_v1'
    bus = getattr(iface, key, None)
    if bus is None:
        bus = IntegrationEvents(iface.mainWindow())
        setattr(iface, key, bus)
    return bus


# ============================================================
# 플러그인 상태·레이어·선택 이벤트 통합
# ============================================================
class ConnectorIntegrationMixin:
    integration_api_version = 2

    def acquire_layer_workspace(self, host):
        """Loan the one list widget to a host; never create a second list/model."""
        if not self._integration_live or self._workspace_host not in (None, host):
            return None
        panel = self._ensure_layer_workspace()
        if self._workspace_host is host:
            return panel
        self._workspace_host = host
        panel.setParent(host)
        self._layer_workspace.hide()
        panel.set_integrated(True)
        panel.show()
        self._workspace_host_destroyed = lambda *_: self.release_layer_workspace(host)
        host.destroyed.connect(self._workspace_host_destroyed)
        self._workspace_model.refresh()
        return panel

    def release_layer_workspace(self, host):
        if self._workspace_host is not host:
            return
        try:
            host.destroyed.disconnect(self._workspace_host_destroyed)
        except (RuntimeError, TypeError):
            pass
        self._workspace_host = None
        self._workspace_host_destroyed = None
        panel = self._workspace_panel
        if panel is not None:
            panel.setParent(self._layer_workspace)
            self._layer_workspace.setWidget(panel)
            panel.set_integrated(False)
            if self._integration_live and self.integration_state()['ready']:
                self._layer_workspace.show()
                panel.show()

    def workspace_signals(self):
        return self._workspace_model.selectionChanged, self._workspace_model.objectSelected

    def selected_layer_id(self):
        return self._workspace_model.selected_id if self._workspace_model is not None else ''

    def select_workspace_layer(self, layer_id):
        return bool(self._integration_live and self._workspace_model is not None
                    and self._workspace_model.select_layer(layer_id))

    def zoom_workspace_layer(self):
        if self._workspace_model is None:
            return
        layer = self._workspace_model.layers().get(self.selected_layer_id())
        if layer is not None and layer.featureCount() > 0:
            self.iface.mapCanvas().setExtent(layer.extent())
            self.iface.mapCanvas().refresh()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._integration_live = False
        self._integration_busy = False
        self._integration_epoch = 0
        self._integration_connections = []
        self._integration_layer_connections = []
        self.integration_events = integration_events(self.iface)

    def initGui(self):
        super().initGui()
        self._integration_live = True
        project = QgsProject.instance()
        for signal in (project.layersAdded, project.layersRemoved):
            signal.connect(self._integration_changed)
            self._integration_connections.append((signal, self._integration_changed))
        project.cleared.connect(self._integration_project_cleared)
        self._integration_connections.append((project.cleared, self._integration_project_cleared))
        # QGIS inserts active_plugins after initGui returns.
        QTimer.singleShot(0, self._integration_changed)

    def _integration_changed(self, *args):
        self.integration_events.changed.emit()

    def _integration_project_cleared(self):
        self.active_context = None
        if self.dialog is not None:
            self.dialog.project_opened = False
            self.dialog.sync_ready = False
            self.dialog._set_busy(False)
            self.dialog.refresh_cache_pin_state()
        self._integration_auth_changing()

    def _watch_integration_layers(self):
        for layer, signal, slot in self._integration_layer_connections:
            if sip.isdeleted(layer):
                continue
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._integration_layer_connections.clear()
        for layer in self._managed_layers():
            for signal in (layer.readOnlyChanged, layer.customPropertyChanged):
                signal.connect(self._integration_changed)
                self._integration_layer_connections.append((layer, signal, self._integration_changed))

    def integration_state(self):
        dialog = self.dialog
        authenticated = bool(self._integration_live and dialog is not None and dialog.client is not None)
        context = self.active_context or {}
        ready = bool(authenticated and not self._integration_busy and dialog.project_opened
                     and self.active_client is dialog.client and context.get('project_id'))
        layers = []
        if ready:
            for layer in self._managed_layers():
                if (layer.isValid() and layer.customProperty('geoflow/managed', False)
                        and str(layer.customProperty('geoflow/project_id', '')) == str(context['project_id'])
                        and str(layer.customProperty('geoflow/package_path', '')) == str(context.get('package_path', ''))):
                    layers.append(layer)
        transport = (context.get('manifest') or {}).get('transport') or {}
        can_write = bool(ready and transport.get('write_authorized')
                         and transport.get('local_editing_supported') and context.get('sync_supported'))
        project = (context.get('manifest') or {}).get('project') or {}
        return {
            'available': self._integration_live, 'authenticated': authenticated,
            'ready': ready, 'epoch': self._integration_epoch,
            'project_id': str(context.get('project_id') or '') if ready else '',
            'project_name': str(project.get('name') or context.get('project_code') or '') if ready else '',
            'project_code': str(context.get('project_code') or '') if ready else '',
            'can_write': can_write, 'layers': tuple(layers),
        }

    def _integration_auth_changing(self):
        self._integration_epoch += 1
        service = getattr(self, '_reference_service', None)
        if service is not None:
            service.clear()
        definitions = getattr(self, '_definition_service', None)
        if definitions is not None:
            definitions.clear()
        self.active_client = None
        self._auto_sync_timer.stop()
        for name in ('_realtime_delta_timer', '_realtime_reconnect_timer', '_realtime_poll_timer'):
            timer = getattr(self, name, None)
            if timer is not None:
                timer.stop()
        stop = getattr(self, '_stop_realtime_socket', None)
        if stop:
            stop()
        self._integration_changed()

    def _materialize_project(self, manifest, client, **kwargs):
        # SnapshotReuse removes old layer groups. Never let it remove edit buffers.
        # Check all GeoFlow groups, including a previous inactive project.
        for layer in QgsProject.instance().mapLayers().values():
            if (layer.customProperty('geoflow/managed', False)
                    and hasattr(layer, 'isModified') and layer.isModified()):
                raise RuntimeError('저장되지 않은 GeoFlow QGIS 편집 버퍼가 있습니다. 현재 편집을 명시적으로 저장하거나 취소한 뒤 프로젝트를 여세요.')
        self._integration_busy = True
        self._integration_epoch += 1
        self._integration_changed()
        try:
            return super()._materialize_project(manifest, client, **kwargs)
        finally:
            self._integration_busy = False
            self._watch_integration_layers()
            self._integration_changed()

    def _halt_realtime_for_expired_session(self):
        self.logout_integration_session()
        super()._halt_realtime_for_expired_session()

    def logout_integration_session(self):
        """End this Connector's local session; retain all QGIS edit buffers/queues."""
        if self.dialog is not None:
            self.dialog.clear_session()
        else:
            self._integration_auth_changing()

    def unload(self):
        self._integration_live = False
        self.logout_integration_session()
        live_connections = [(signal, slot) for layer, signal, slot in self._integration_layer_connections if not sip.isdeleted(layer)]
        for signal, slot in self._integration_connections + live_connections:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._integration_connections.clear()
        self._integration_layer_connections.clear()
        if self.dialog is not None:
            self.dialog.close()
            self.dialog.deleteLater()
            self.dialog = None
        super().unload()
