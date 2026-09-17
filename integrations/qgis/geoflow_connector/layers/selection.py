# 제목: layers/selection.py
# 기능: 레이어·객체 선택과 생성/삭제/저장 신호의 단일 모델
"""One project-scoped selection model for the dock and the integrated workspace."""
from qgis.PyQt.QtCore import QObject, pyqtSignal, QTimer
from qgis.core import QgsProject
from qgis.PyQt import sip
from .model import workspace_rows


class LayerWorkspaceState(QObject):
    rowsChanged = pyqtSignal()
    selectionChanged = pyqtSignal(str)
    revealRequested = pyqtSignal(str)
    objectSelected = pyqtSignal(str, object)
    visibilityChanged = pyqtSignal()

    def __init__(self, plugin):
        super().__init__(plugin.iface.mainWindow())
        self.plugin = plugin
        self.rows = []
        self.selected_id = ''
        self._scope = None
        self._closed = False
        self._connections = []
        self._layer_connections = []
        self._watched = set()
        self._missing_labels = set()
        self._pending_added = {}
        for signal, slot in ((plugin.integration_events.changed, self.refresh),
                             (plugin.iface.currentLayerChanged, self._active_changed),
                             (QgsProject.instance().layerTreeRoot().visibilityChanged, self._visibility_changed)):
            signal.connect(slot)
            self._connections.append((signal, slot))

    def _visibility_changed(self, *args):
        if not self._closed:
            self.visibilityChanged.emit()

    def layers(self):
        if self._closed:
            return {}
        return {layer.id(): layer for layer in self.plugin.integration_state()['layers']}

    def refresh(self, *args):
        if self._closed:
            return
        state = self.plugin.integration_state()
        scope = (state['epoch'], state['project_id'], state['ready'])
        layers = self.layers()
        if scope != self._scope:
            self._scope = scope
            self._set_selected('', activate=False, reveal=False)
        if self.selected_id and self.selected_id not in layers:
            self._set_selected('', activate=False, reveal=False)
        manifest = (self.plugin.active_context or {}).get('manifest') or {}
        self.rows = workspace_rows(manifest.get('layers') or [], layers.values())
        for row in self.rows:
            label = str(row.get('label') or '')
            if not label.strip():
                key = row.get('standard_name', '')
                row['label'] = '표시명 미등록'
                if key not in self._missing_labels:
                    self._missing_labels.add(key)
                    from qgis.core import QgsMessageLog
                    QgsMessageLog.logMessage('missing_layer_label: ' + key, 'GeoFlow')

        if set(layers) != self._watched:
            self._disconnect(self._layer_connections)
            self._watched = set(layers)
            for lid, layer in layers.items():
                callbacks = (
                    (layer.featureAdded, lambda fid, key=lid: self._added(key, fid)),
                    (layer.featureDeleted, lambda fid, key=lid: self._deleted(key, fid)),
                    (layer.selectionChanged, lambda *args, key=lid: self._objects_changed(key)),
                    (layer.afterCommitChanges, self.refresh),
                    (layer.afterRollBack, self.refresh),
                )
                for signal, slot in callbacks:
                    signal.connect(slot)
                    self._layer_connections.append((layer, signal, slot))
        self.rowsChanged.emit()
        if not self.selected_id:
            active = self.plugin.iface.activeLayer()
            if active is not None and active.id() in layers:
                self._set_selected(active.id(), activate=False, reveal=False)

    def select_layer(self, layer_id, *, activate=True, reveal=True):
        if self._closed or str(layer_id) not in self.layers():
            return False
        self._set_selected(str(layer_id), activate=activate, reveal=reveal)
        return True

    def _set_selected(self, lid, *, activate, reveal):
        changed = lid != self.selected_id
        self.selected_id = lid
        if activate and lid:
            layer = self.layers().get(lid)
            if layer is not None and self.plugin.iface.activeLayer() is not layer:
                self.plugin.iface.setActiveLayer(layer)
        if changed:
            self.selectionChanged.emit(lid)
        if reveal and lid:
            self.revealRequested.emit(lid)

    def _active_changed(self, layer):
        if self._closed:
            return
        lid = layer.id() if layer is not None else ''
        if not self.select_layer(lid, activate=False):
            self._set_selected('', activate=False, reveal=False)

    def _objects_changed(self, lid):
        layer = self.layers().get(lid)
        if layer is None:
            return
        ids = layer.selectedFeatureIds()
        if len(ids) == 1:
            self.select_layer(lid)
            self.objectSelected.emit(lid, ids[0])
        elif self.selected_id == lid:
            self.objectSelected.emit(lid, None)

    def _added(self, lid, fid):
        # QGIS is still inside addFeature here; defer form reads until it returns.
        # A bulk insert needs one UI refresh per layer, not one per geometry.
        pending = getattr(self, '_pending_added', None)
        if pending is None:
            self._pending_added = pending = {}
        queued = lid in pending
        pending[lid] = fid
        if queued:
            return
        scope = self._scope
        def deliver():
            latest = pending.pop(lid, None)
            if latest is not None:
                self._show_added(lid, latest, scope)
        QTimer.singleShot(0, deliver)

    def _show_added(self, lid, fid, scope):
        if self._closed or self._scope != scope:
            return
        self.refresh()
        layer = self.layers().get(lid)
        if self.selected_id == lid and layer is not None and layer.getFeature(fid).isValid():
            self.objectSelected.emit(lid, fid)

    def _deleted(self, lid, fid):
        self.refresh()
        if self.selected_id == lid:
            self.objectSelected.emit(lid, None)

    @staticmethod
    def _disconnect(connections):
        for connection in connections:
            if len(connection) == 3:
                sender, signal, slot = connection
                if sip.isdeleted(sender):
                    continue  # Qt already disconnected the deleted layer.
            else:
                signal, slot = connection
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        connections.clear()

    def close(self):
        self._closed = True
        self._disconnect(self._connections)
        self._disconnect(self._layer_connections)
        self.rows = []
        self.selected_id = ''
