"""GeoFlow edit-mode launcher over QGIS native edit actions."""
from __future__ import annotations

import json
import traceback
from pathlib import Path

from qgis.PyQt.QtCore import QEvent, QObject, QPoint, QSize, Qt, QTimer
from qgis.PyQt.QtGui import QAction, QIcon
from qgis.PyQt.QtWidgets import QMessageBox, QMenu, QPushButton, QToolBar, QVBoxLayout, QWidget
from qgis.PyQt.uic import loadUi
from qgis.PyQt import sip
from qgis.core import (
    QgsApplication, QgsMessageLog, QgsProject, QgsVectorLayer, QgsWkbTypes, Qgis,
)

from ..services.depth import DepthService, FAILURE_REASONS
from ..services.nearby import NearbyStrategyRegistry
from .main_style import apply_main_style


class EditToolsController(QObject):
    def __init__(self, plugin, toggle_button):
        super().__init__(plugin.iface.mainWindow())
        self.plugin = plugin
        self.toggle_button = toggle_button
        self.panel = loadUi(str(Path(__file__).parent / "designer" / "edit_tools.ui"))
        main_window = plugin.iface.mainWindow()
        self.palette = QWidget(main_window)
        self.palette.setObjectName("GeoFlowEditToolsPalette")
        self.palette.setProperty("geoflowEditToolsPalette", True)
        self.palette.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        palette_layout = QVBoxLayout(self.palette)
        palette_layout.setContentsMargins(4, 4, 4, 4)
        palette_layout.addWidget(self.panel)
        self.palette.setFixedWidth(46)
        for button in self.panel.findChildren(type(self.panel.addFeatureButton)):
            button.setFixedSize(32, 32)
            button.setIconSize(QSize(22, 22))
        apply_main_style(self.palette)
        self.palette.hide()
        self.host = self.palette  # Compatibility for runtime diagnostics.
        self.registry = NearbyStrategyRegistry()
        self.depth = DepthService(plugin)
        from ..services.direction import DirectionService
        self.direction = DirectionService(plugin)
        self._rotation_dialog = None
        self._direction_buttons = {}
        self._direction_connections = []
        self.registry.register("WTL_PIPE_PS", self.depth.strategy)
        self._form_pages = {}
        self._depth_field_actions = {}
        self._native_actions = {}
        self._native_action_connections = []
        from .form_actions import default_field_action_registry
        self.field_action_registry = default_field_action_registry()
        self._selection_layer_id = ""
        self._layer_signal_connections = []
        self._mode = None
        self._last_context_signature = None
        self._last_display_signature = None
        self._owned_map_tool = None
        self._launched_map_tool = False
        self._closed = False
        self._save_proxy = None
        self._save_action = None
        self._save_action_hosts = []
        self._log("edit_tools_panel_created")
        rail = self.toggle_button.parentWidget()
        self._calculation_toolbar = None
        if rail is None or rail.layout() is None:
            self._calculation_toolbar = QToolBar('GeoFlow 계산',main_window)
            main_window.addToolBar(self._calculation_toolbar)
        def place_calculation(button, index):
            if self._calculation_toolbar is not None:
                self._calculation_toolbar.addWidget(button)
            else:
                rail.layout().insertWidget(index,button)
        self.depth_batch_button = QPushButton('심도 일괄계산', self.panel)
        place_calculation(self.depth_batch_button,5)
        self.depth_batch_button.clicked.connect(self._run_depth)
        self.direction_batch_button = QPushButton('방향각 일괄계산', self.panel)
        place_calculation(self.direction_batch_button,6)
        for button, title, icon in (
            (self.depth_batch_button, '심도 일괄계산', '/mActionFieldCalculator.svg'),
            (self.direction_batch_button, '방향각 일괄계산', '/mActionRotatePointSymbols.svg')):
            button.setText('')
            button.setAccessibleName(title)
            button.setToolTip(title)
            button.setIcon(QgsApplication.getThemeIcon(icon))
            button.setFixedSize(32, 32)
            button.setIconSize(QSize(22, 22))
        self.direction_batch_button.clicked.connect(self.direction_action)
        self._definition_events = getattr(plugin, '_definition_service', None)
        if self._definition_events is not None:
            self._definition_events.changed.connect(self.refresh)
        self._wire()
        plugin.dock.visibilityChanged.connect(self._main_dock_visibility_changed)
        plugin.dock.installEventFilter(self)
        main_window.installEventFilter(self)
        self._bind_native_actions()
        self._install_online_save_proxy()
        self._log("edit_tools_bound")
        self._active_layer_changed(self._active_layer())
        self.set_mode(False)

    def _log(self, event):
        logger = getattr(self.plugin, "log", None)
        if callable(logger):
            logger(event)

    def _wire(self):
        self.toggle_button.toggled.connect(self._toggle_requested)
        self.plugin.iface.currentLayerChanged.connect(self._active_layer_changed)
        QgsProject.instance().snappingConfigChanged.connect(self.refresh)
        self.panel.addFeatureButton.clicked.connect(self._add_feature)
        self.panel.moveButton.clicked.connect(
            lambda: self._native_edit_action("actionMoveFeature")
        )
        self.panel.vertexButton.clicked.connect(
            lambda: self._native_edit_action("actionVertexToolActiveLayer", "actionVertexTool")
        )
        self.panel.splitButton.clicked.connect(
            lambda: self._native_edit_action("actionSplitFeatures")
        )
        self.panel.deleteButton.clicked.connect(
            self._delete_selected
        )
        self.panel.snappingButton.clicked.connect(self._toggle_snapping)
        self.panel.undoButton.clicked.connect(lambda: self._undo_redo(False))
        self.panel.redoButton.clicked.connect(lambda: self._undo_redo(True))

    def _main_dock_visibility_changed(self, visible):
        if visible and self._mode:
            self._sync_palette_geometry()
            self.palette.show()
            self.palette.raise_()
        else:
            self.palette.hide()

    def eventFilter(self, watched, event):
        if watched in (self.plugin.dock, self.plugin.iface.mainWindow()) and event.type() in (
            QEvent.Type.Move,
            QEvent.Type.Resize,
            QEvent.Type.Show,
            QEvent.Type.Hide,
            QEvent.Type.WindowStateChange,
        ):
            QTimer.singleShot(0, self._sync_palette_geometry)
        return False

    def _sync_palette_geometry(self):
        if self._closed or not self._mode or not self.plugin.dock.isVisible():
            self.palette.hide()
            return
        main_window = self.plugin.iface.mainWindow()
        dock_top_left = self.plugin.dock.mapTo(main_window, QPoint(0, 0))
        width = self.palette.width()
        height = min(
            max(150, self.panel.sizeHint().height() + 8),
            max(150, self.plugin.dock.height()),
        )
        bounds = main_window.rect()
        x = max(0, dock_top_left.x() - width - 4)
        y = max(0, min(dock_top_left.y(), bounds.height() - height))
        self.palette.setGeometry(x, y, width, height)
        self.palette.raise_()

    def _iface_action(self, *names):
        for name in names:
            getter = getattr(self.plugin.iface, name, None)
            action = getter() if callable(getter) else None
            if action is not None:
                return action
        return None

    def _set_message(self, message, page=None):
        target = page or self._current_page()
        note = getattr(target, "note", None)
        if note is not None:
            note.setText(str(message))
        bar = getattr(self.plugin.iface, "messageBar", lambda: None)()
        if bar is not None:
            bar.pushMessage("GeoFlow", str(message))

    def _delete_log(self, key, value):
        message = f"[DELETE] {key}={value}"
        self._log(message)
        if not callable(getattr(self.plugin, "log", None)):
            QgsMessageLog.logMessage(message, "GeoFlow", Qgis.MessageLevel.Info)

    def _delete_selected(self):
        """Run native selection deletion and finish its online-only lifecycle."""
        layer = self._active_layer()
        self._delete_log("action_clicked", "true")
        if not self._is_managed_edit_layer(layer) or layer.readOnly():
            self._set_message("편집 가능한 GeoFlow 레이어를 선택하세요.")
            return False
        standard = str(layer.customProperty("geoflow/standard_name", "") or layer.name())
        selected_ids = [int(fid) for fid in layer.selectedFeatureIds()]
        self._delete_log("layer", standard)
        self._delete_log("selected_ids", selected_ids)
        if not selected_ids:
            self._set_message("삭제할 객체를 선택하세요.")
            return False
        if not layer.isEditable() and not layer.startEditing():
            self._set_message("레이어 편집을 시작할 수 없습니다.")
            return False

        layer.setCustomProperty("geoflow/delete_commit_in_progress", True)
        try:
            action = self._iface_action("actionDeleteSelected")
            if action is None:
                raise RuntimeError("QGIS 선택 객체 삭제 액션을 찾지 못했습니다.")
            action.trigger()
            buffer = layer.editBuffer()
            deleted_ids = sorted(int(fid) for fid in (
                buffer.deletedFeatureIds() if buffer is not None else ()
            ))
            self._delete_log("qgis_buffer_deleted_ids", deleted_ids)
            requested = sorted(set(selected_ids) & set(deleted_ids))
            if not requested:
                # The native confirmation dialog was cancelled.
                return False
            layer.setCustomProperty("geoflow/pending_delete_ids", requested)
            work = getattr(self.plugin, "work", None)
            clear_context = getattr(work, "clear_staged_delete_context", None)
            if callable(clear_context):
                clear_context(layer.id(), requested)
            self._set_message(
                f"객체 {len(requested)}건을 삭제 대기로 표시했습니다. "
                "다른 편집을 계속한 뒤 GeoFlow 저장을 누르세요."
            )
            self.refresh()
            return True
        except Exception:
            QgsMessageLog.logMessage(
                "[DELETE] exception\n" + traceback.format_exc(),
                "GeoFlow", Qgis.MessageLevel.Critical,
            )
            self._set_message("객체 삭제 중 오류가 발생했습니다. GeoFlow 로그를 확인하세요.")
            return False
        finally:
            try:
                layer.setCustomProperty("geoflow/delete_commit_in_progress", False)
            except RuntimeError:
                pass

    def _bind_native_actions(self):
        bindings = {
            "add": (self.panel.addFeatureButton, ("actionAddFeature",)),
            "move": (self.panel.moveButton, ("actionMoveFeature",)),
            "vertex": (self.panel.vertexButton, (
                "actionVertexToolActiveLayer", "actionVertexTool",
            )),
            "split": (self.panel.splitButton, ("actionSplitFeatures",)),
            "delete": (self.panel.deleteButton, ("actionDeleteSelected",)),
            "snapping": (self.panel.snappingButton, (
                "actionEnableSnapping", "actionSnappingOptions",
            )),
            "undo": (self.panel.undoButton, ("actionUndo",)),
            "redo": (self.panel.redoButton, ("actionRedo",)),
        }
        fallback_icons = {
            "snapping": ":/geoflow/tabler/magnet.svg",
            "undo": ":/geoflow/tabler/arrow-back-up.svg",
            "redo": ":/geoflow/tabler/arrow-forward-up.svg",
        }
        for key, (button, names) in bindings.items():
            action = self._iface_action(*names)
            self._native_actions[key] = action
            icon = action.icon() if action is not None and hasattr(action, "icon") else QIcon()
            if not isinstance(icon, QIcon):
                icon = QIcon()
            if icon.isNull() and key in fallback_icons:
                icon = QIcon(fallback_icons[key])
            button.setIcon(icon)
            changed = getattr(action, "changed", None)
            if changed is not None:
                changed.connect(self.refresh)
                self._native_action_connections.append((changed, self.refresh))

    def _install_online_save_proxy(self):
        """Route QGIS' visible Save Layer Edits action through server-first save."""
        original = self._iface_action("actionSaveActiveLayerEdits")
        if original is None:
            return
        proxy = QAction(original.icon(), original.text(), self.plugin.iface.mainWindow())
        proxy.setObjectName("GeoFlowOnlineSaveLayerEdits")
        proxy.setToolTip(original.toolTip())
        proxy.setStatusTip(original.statusTip())
        proxy.setWhatsThis(original.whatsThis())
        proxy.setShortcuts(original.shortcuts())
        proxy.setShortcutContext(original.shortcutContext())
        self._save_action = original
        self._save_proxy = proxy
        self._save_original_shortcuts = original.shortcuts()
        original.setShortcuts([])
        for host in list(original.associatedObjects()):
            if not isinstance(host, (QMenu, QToolBar)):
                continue
            actions = list(host.actions())
            if original not in actions:
                continue
            index = actions.index(original)
            before = actions[index + 1] if index + 1 < len(actions) else None
            host.insertAction(before, proxy)
            host.removeAction(original)
            self._save_action_hosts.append((host, before))
        proxy.triggered.connect(self._qgis_save_triggered)
        original.changed.connect(self._sync_save_proxy)
        self._native_action_connections.append((original.changed, self._sync_save_proxy))
        self._sync_save_proxy()

    def _sync_save_proxy(self, *args):
        del args
        if self._save_proxy is None or self._save_action is None:
            return
        layer = self._active_layer()
        managed = self._is_managed_edit_layer(layer)
        enabled = bool(
            managed and layer is not None and layer.isEditable()
            and layer.isModified()
        ) if managed else bool(self._save_action.isEnabled())
        self._save_proxy.setEnabled(enabled)

    def _qgis_save_triggered(self, checked=False):
        del checked
        layer = self._active_layer()
        if not self._is_managed_edit_layer(layer):
            if self._save_action is not None:
                self._save_action.trigger()
            return
        work = getattr(self.plugin, "work", None)
        if work is None:
            return
        previous = getattr(self.plugin, "_online_save_trigger", "geoflow_save")
        self.plugin._online_save_trigger = "qgis_save_action"
        try:
            adapter = getattr(work, "adapter", None)
            selected_layer_id = (
                adapter.selected_layer_id() if adapter is not None else ""
            )
            if selected_layer_id == layer.id():
                work.save_current()
            else:
                self.plugin.commit_layer_online(layer, stop_editing=False)
        finally:
            self.plugin._online_save_trigger = previous
        self.refresh()

    def _sync_action_icons(self, layer):
        for key, action in self._native_actions.items():
            if action is not None and hasattr(action, "icon"):
                icon = action.icon()
                if isinstance(icon, QIcon) and not icon.isNull():
                    getattr(self.panel, {
                        "add": "addFeatureButton", "move": "moveButton",
                        "vertex": "vertexButton", "split": "splitButton",
                        "delete": "deleteButton", "snapping": "snappingButton",
                        "undo": "undoButton", "redo": "redoButton",
                    }[key]).setIcon(icon)
        if not isinstance(layer, QgsVectorLayer):
            return
        geometry = QgsWkbTypes.geometryType(layer.wkbType())
        theme_icon = {
            QgsWkbTypes.GeometryType.PointGeometry: "/mActionCapturePoint.svg",
            QgsWkbTypes.GeometryType.LineGeometry: "/mActionCaptureLine.svg",
            QgsWkbTypes.GeometryType.PolygonGeometry: "/mActionCapturePolygon.svg",
        }.get(geometry)
        if theme_icon:
            icon = QgsApplication.getThemeIcon(theme_icon)
            if not icon.isNull():
                self.panel.addFeatureButton.setIcon(icon)

    def _is_managed_edit_layer(self, layer):
        if not isinstance(layer, QgsVectorLayer):
            return False
        try:
            if sip.isdeleted(layer):
                return False
            managed_ids = {
                candidate.id() for candidate in self.plugin.integration_state().get("layers", ())
                if isinstance(candidate, QgsVectorLayer) and not sip.isdeleted(candidate)
            }
            return layer.id() in managed_ids
        except RuntimeError:
            return False

    def _toggle_requested(self, enabled):
        layer = self._active_layer()
        if enabled:
            if not self._is_managed_edit_layer(layer) or layer.readOnly():
                self._set_message("편집 가능한 GeoFlow 레이어를 선택하세요.")
                self.set_mode(False)
                return
            if not layer.isEditable() and not layer.startEditing():
                self._set_message("활성 레이어의 편집을 시작할 수 없습니다.")
                self.set_mode(False)
                return
            self.set_mode(True)
            return
        self._request_stop_editing(layer)

    def _request_stop_editing(self, layer):
        if not isinstance(layer, QgsVectorLayer) or not layer.isEditable():
            self.set_mode(False)
            return
        work = getattr(self.plugin, "work", None)
        if layer.isModified() and work is not None and not work.guard_transition("편집 종료"):
            self.set_mode(True)
            return
        if not layer.isEditable():
            self.set_mode(False)
            return
        action = self._iface_action("actionToggleEditing")
        if action is not None:
            action.trigger()
        elif not layer.isModified():
            layer.rollBack()
        self.set_mode(layer.isEditable())

    def _sync_edit_state(self, *args):
        layer = self._active_layer()
        self.set_mode(bool(
            self._is_managed_edit_layer(layer) and layer.isEditable()
        ))

    def set_mode(self, enabled):
        enabled = bool(enabled)
        was_enabled = self._mode
        self._mode = enabled
        self.toggle_button.blockSignals(True)
        self.toggle_button.setChecked(enabled)
        self.toggle_button.setText("")
        self.toggle_button.setToolTip("편집 도구")
        self.toggle_button.blockSignals(False)
        self.panel.setVisible(enabled)
        if enabled and self.plugin.dock.isVisible():
            self._sync_palette_geometry()
            self.palette.show()
            self.palette.raise_()
        else:
            self.palette.hide()
        if not enabled and was_enabled and self._launched_map_tool:
            canvas_getter = getattr(self.plugin.iface, "mapCanvas", None)
            canvas = canvas_getter() if callable(canvas_getter) else None
            current = canvas.mapTool() if canvas is not None else None
            # Do not replace a map tool another plugin installed afterwards.
            if self._owned_map_tool is None or current is self._owned_map_tool:
                action = getattr(self.plugin.iface, "actionPan", lambda: None)()
                if action is not None:
                    action.trigger()
            self._owned_map_tool = None
            self._launched_map_tool = False
        if was_enabled is None or was_enabled != enabled:
            self._log(f"edit_mode_changed enabled={str(enabled).lower()}")
            self._log(
                "edit_tools_palette_visible="
                + str(bool(self.palette.isVisible() and self.panel.isVisible())).lower()
            )
        self.refresh()
        self.log_runtime_state(force=was_enabled is None or was_enabled != enabled)

    @staticmethod
    def _geometry(widget):
        rect = widget.geometry()
        return [rect.x(), rect.y(), rect.width(), rect.height()]

    def log_runtime_state(self, force=False):
        button = self.toggle_button
        ancestors = []
        parent = button.parentWidget()
        while parent is not None:
            ancestors.append({
                "name": parent.objectName() or type(parent).__name__,
                "visible": bool(parent.isVisible()),
                "hidden": bool(parent.isHidden()),
                "geometry": self._geometry(parent),
            })
            parent = parent.parentWidget()
        global_position = button.mapToGlobal(button.rect().topLeft())
        dock = getattr(self.plugin, "dock", None)
        button_state = {
            "visible": bool(button.isVisible()),
            "visible_to_dock": bool(dock is not None and button.isVisibleTo(dock)),
            "hidden": bool(button.isHidden()),
            "enabled": bool(button.isEnabled()),
            "geometry": self._geometry(button),
            "global_position": [global_position.x(), global_position.y()],
            "parent": button.parentWidget().objectName() if button.parentWidget() else "",
            "ancestors": ancestors,
        }
        panel_state = {
            "palette_visible": bool(self.palette.isVisible()),
            "palette_geometry": self._geometry(self.palette),
            "panel_visible": bool(self.panel.isVisible()),
            "panel_geometry": self._geometry(self.panel),
        }
        signature = json.dumps(
            {"button": button_state, "panel": panel_state},
            ensure_ascii=False, sort_keys=True,
        )
        if force or signature != self._last_display_signature:
            self._last_display_signature = signature
            self._log("edit_mode_button_state=" + json.dumps(
                button_state, ensure_ascii=False, sort_keys=True,
            ))
            self._log("edit_tools_display_state=" + json.dumps(
                panel_state, ensure_ascii=False, sort_keys=True,
            ))

    def _active_layer_changed(self, layer=None):
        for signal, slot in self._layer_signal_connections:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._layer_signal_connections.clear()
        self._selection_layer_id = ""
        if layer is not None and sip.isdeleted(layer):
            layer = None
        if isinstance(layer, QgsVectorLayer):
            self._selection_layer_id = layer.id()
            for signal, slot in (
                (layer.selectionChanged, self.refresh),
                (layer.editingStarted, self._sync_edit_state),
                (layer.editingStopped, self._sync_edit_state),
                (layer.afterCommitChanges, self._sync_edit_state),
                (layer.afterRollBack, self._sync_edit_state),
            ):
                signal.connect(slot)
                self._layer_signal_connections.append((signal, slot))
        self._sync_edit_state()
        self.refresh()

    def _active_layer(self):
        layer = self.plugin.iface.activeLayer()
        return None if layer is not None and sip.isdeleted(layer) else layer

    def _trigger_iface_action(self, *names):
        for name in names:
            getter = getattr(self.plugin.iface, name, None)
            action = getter() if callable(getter) else None
            if action is not None:
                action.trigger()
                return True
        return False

    def _add_feature(self):
        self._native_edit_action("actionAddFeature")

    def _native_edit_action(self, *names):
        layer = self._active_layer()
        state = self.plugin.integration_state()
        if (not isinstance(layer, QgsVectorLayer) or layer.readOnly()
                or not state.get("ready") or not state.get("can_write")):
            return False
        if not layer.isEditable() and not layer.startEditing():
            self._set_message("활성 레이어의 편집을 시작할 수 없습니다.")
            return False
        triggered = self._trigger_iface_action(*names)
        if triggered:
            self._launched_map_tool = True
            canvas_getter = getattr(self.plugin.iface, "mapCanvas", None)
            canvas = canvas_getter() if callable(canvas_getter) else None
            self._owned_map_tool = canvas.mapTool() if canvas is not None else None
        return triggered

    def _toggle_snapping(self):
        project = QgsProject.instance()
        config = project.snappingConfig()
        config.setEnabled(not config.enabled())
        project.setSnappingConfig(config)
        self.refresh()

    def _undo_redo(self, redo):
        layer = self._active_layer()
        stack = layer.undoStack() if isinstance(layer, QgsVectorLayer) else None
        if stack is not None:
            stack.redo() if redo else stack.undo()
        self.refresh()

    def _current_page(self):
        layer = self._active_layer()
        work = getattr(self.plugin, "work", None)
        try:
            return (getattr(work, "pages", {}) or {}).get(layer.id()) if layer is not None else None
        except RuntimeError:
            return None

    def _layer_by_id(self, layer_id):
        layer = QgsProject.instance().mapLayer(str(layer_id))
        if layer is not None:
            return layer
        active = self._active_layer()
        try:
            return active if active is not None and active.id() == str(layer_id) else None
        except RuntimeError:
            return None

    def register_form_page(self, page, layer):
        self._form_pages[layer.id()] = page
        page.form_actions.previousButton.clicked.connect(
            lambda _checked=False, p=page: self._apply_previous(p)
        )
        page.form_actions.nearbyButton.clicked.connect(
            lambda _checked=False, p=page: self._run_nearby(p)
        )
        self._depth_field_actions[layer.id()] = self.field_action_registry.attach(
            page, layer, self
        )
        from ..services.settings import GeoFlowSettingsService
        visible = GeoFlowSettingsService(self.plugin).show_field_action_buttons(
            getattr(page, "project_id", None)
        )
        for button in self._depth_field_actions[layer.id()]:
            button.setVisible(visible)
        self._refresh_direction_page(page, layer)
        self.refresh()

    def _refresh_direction_page(self, page, layer):
        from qgis.PyQt.QtWidgets import QToolButton
        from .form_actions import configure_field_action_button
        targets = self.direction.targets(layer)
        attached = getattr(page, '_direction_actions', {})
        for field in targets:
            field_id = field['id']
            if field_id not in attached:
                buttons = []
                for manual,label,callback in ((False,'자동계산',self.calculate_direction),(True,'직접 회전',self.rotate_direction)):
                    button = QToolButton(page.form)
                    button.setProperty('directionManual',manual)
                    configure_field_action_button(button,icon=':/geoflow/tabler/rotate.svg',tooltip=label)
                    button.setAccessibleName(label)
                    button.clicked.connect(lambda checked=False, cb=callback, p=page: cb(page=p))
                    if page.form.add_field_action(field_id,button):
                        buttons.append(button)
                    else:
                        button.deleteLater()
                        self._set_message('방향각 필드 액션 부착 실패: ' + field_id, page)
                        self._log('direction_attach_failed field_id=' + field_id)
                attached[field_id] = buttons
        valid_ids = {f['id'] for f in targets}
        for field_id,buttons in attached.items():
            for button in buttons:
                button.setVisible(field_id in valid_ids)
                manual = bool(button.property('directionManual'))
                label = '직접 회전' if manual else '자동계산'
                reason = ''
                try: self.direction.settings(layer,manual=manual)
                except (ValueError,TypeError,AttributeError) as exc: reason = str(exc)
                state = self.plugin.integration_state()
                if not state.get('ready') or not state.get('can_write') or layer.readOnly() or not self._is_managed_edit_layer(layer):
                    reason = '현재 프로젝트의 편집 권한이 없습니다.'
                elif page.feature_id is None or layer.selectedFeatureIds() != [page.feature_id]:
                    reason = reason or '대상 객체를 하나 선택하세요.'
                button.setEnabled(not reason and field_id in valid_ids)
                button.setToolTip(label + (' · ' + reason if reason else ''))
                if reason and reason != button.property('directionReason'):
                    self._log('direction_action_unavailable field_id=' + field_id + ' reason=' + reason)
                button.setProperty('directionReason',reason)
        page._direction_actions = attached
        self._direction_buttons[layer.id()] = [b for buttons in attached.values() for b in buttons]
        if targets and not getattr(page,'_direction_sync_connected',False):
            def sync_angle(fid,index,value):
                if page.feature_id == fid and not page.binding.loading and not page.binding.saving:
                    for field in self.direction.targets(layer):
                        if index == layer.fields().indexFromName((field.get('storage') or {}).get('key','')):
                            try:
                                self.direction.sync_form(page,layer)
                            except (ValueError,TypeError,AttributeError) as exc:
                                self._log('direction_sync_failed field_id=' + field['id'] + ' reason=' + str(exc))
                                self._set_message('방향각 폼 동기화 실패: ' + str(exc),page)
            layer.attributeValueChanged.connect(sync_angle)
            self._direction_connections.append((layer,sync_angle))
            page.destroyed.connect(lambda:self._disconnect_direction(layer,sync_angle))
            page._direction_sync_connected = True
        try:
            field,config = self.direction.settings(layer,manual=True)
            signature = (field['id'],json.dumps(config,sort_keys=True))
            if signature != getattr(page,'_direction_render_signature',None):
                self.direction.bind_renderer(layer)
                page._direction_render_signature = signature
        except (ValueError,TypeError,AttributeError) as exc:
            page._direction_render_signature = None

    @staticmethod
    def _disconnect_direction(layer, slot):
        try: layer.attributeValueChanged.disconnect(slot)
        except (RuntimeError, TypeError): pass

    def rotate_direction(self, checked=False, page=None):
        from .direction import RotationDialog
        page = page or self._current_page()
        layer = self._layer_by_id(page.layer_id) if page is not None else self._active_layer()
        if page is None or page.feature_id is None or layer.selectedFeatureCount() != 1:
            return
        try:
            if self._rotation_dialog is not None: self._rotation_dialog.reject()
            self._rotation_dialog = RotationDialog(self, layer, page)
            self._rotation_dialog.show()
        except Exception as exc: self._set_message(str(exc), page)

    def calculate_direction(self, checked=False, page=None):
        from .direction import DirectionResults
        page = page or self._current_page()
        layer = self._layer_by_id(page.layer_id) if page is not None else self._active_layer()
        if layer is None: return
        features = list(layer.selectedFeatures())
        if not features and page is not None and page.feature_id is not None:
            features = [layer.getFeature(page.feature_id)]
        if not features: return
        dialog = DirectionResults(self, layer, features, page)
        dialog.exec()

    def _apply_previous(self, page=None):
        page = page or self._current_page()
        work = getattr(self.plugin, "work", None)
        if page is None or page.feature_id is None or work is None:
            self._set_message("현재 객체의 Dynamic Form을 먼저 여세요.", page)
            return
        applied = work.previous_values.apply(page)
        self._set_message(
            f"이전 업무값 {len(applied)}개를 적용했습니다. 저장 전 검토하세요."
            if applied else "가져올 이전 업무값이 없습니다.", page
        )
        self.refresh()

    def _run_nearby(self, page=None):
        page = page or self._current_page()
        layer = self._active_layer()
        if page is not None:
            layer = self._layer_by_id(page.layer_id)
        standard = str(layer.customProperty("geoflow/standard_name", "") or "") if layer else ""
        strategies = self.registry.for_layer(standard)
        if not strategies:
            self._set_message("현재 레이어에 등록된 근처값 전략이 없습니다.", page)
            return
        if page is not None:
            self.calculate_current_depth(page)
        else:
            self._run_depth()

    def calculate_current_depth(self, page):
        from .inline_message import show_depth_feedback
        layer = self._layer_by_id(page.layer_id)
        feature = self._current_form_feature(layer, page)
        try:
            result = (self.depth.apply_to_form(page, feature, overwrite=True)
                      if feature is not None and self.depth.target_supported(layer)
                      else {"ok": False, "reason": "calculation_failed"})
        except Exception as exc:
            self._log("depth_calculate_failed stage=inline_form reason=calculation_failed "
                      f"exception_type={type(exc).__name__} message={str(exc)[:500]}")
            result = {"ok": False, "reason": "calculation_failed"}
        self.refresh()
        show_depth_feedback(page, result, self.depth.radius_m)

    def _overwrite_choice(self):
        box = QMessageBox(self.panel)
        box.setWindowTitle("상수심도 자동계산")
        box.setText("기존 심도값 처리 방법을 선택하세요.")
        null_only = box.addButton("NULL만 계산", QMessageBox.ButtonRole.AcceptRole)
        overwrite = box.addButton("전체 재계산", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is null_only:
            return False
        if clicked is overwrite:
            return True
        return None

    @staticmethod
    def _feature_uuid(feature):
        if feature is None or not feature.isValid() or "id" not in feature.fields().names():
            return ""
        return str(feature["id"] or "").strip("{}").casefold()

    def _current_form_feature(self, layer, page):
        if (not isinstance(layer, QgsVectorLayer) or page is None
                or page.feature_id is None):
            return None
        feature = layer.getFeature(page.feature_id)
        return feature if feature.isValid() else None

    def _run_depth(self):
        layer = self._active_layer()
        if not isinstance(layer, QgsVectorLayer): return
        selected = list(layer.selectedFeatures())
        if len(selected) < 2:
            self._set_message('심도 객체를 2개 이상 선택하세요.'); return
        state = self.plugin.integration_state()
        if not (state.get('ready') and state.get('can_write') and self._is_managed_edit_layer(layer)
                and not layer.readOnly() and self.depth.target_supported(layer)):
            self._set_message('현재 프로젝트의 쓰기 가능한 심도 레이어가 필요합니다.'); return
        overwrite = self._overwrite_choice()
        if overwrite is None: return
        try:
            summary = self.depth.apply_to_features(layer, selected, overwrite=overwrite, page=self._current_page())
            from .depth_results import DepthResults
            old = getattr(self, '_depth_results', None)
            if old is not None: old.close()
            self._depth_results = DepthResults(self,layer,summary)
            self._depth_results.show()
            self.refresh()
        except Exception as exc:
            self._log('depth_batch_failed ' + str(exc))
            self._set_message('심도 일괄계산 실패: ' + str(exc))

    def direction_action(self):
        layer = self._active_layer()
        if layer is None or not layer.selectedFeatureCount():
            self._set_message('방향각 대상 객체를 선택하세요.'); return
        if layer.selectedFeatureCount() > 1:
            self.calculate_direction(); return
        menu = QMenu(self.direction_batch_button)
        menu.addAction('자동계산', self.calculate_direction)
        menu.addAction('직접 회전', self.rotate_direction)
        menu.exec(self.direction_batch_button.mapToGlobal(self.direction_batch_button.rect().bottomRight()))

    def refresh(self, *args):
        if self._closed:
            return
        layer = self._active_layer()
        self._sync_action_icons(layer)
        state = self.plugin.integration_state()
        ready = bool(state.get("ready"))
        self.toggle_button.setEnabled(bool(
            ready and state.get("can_write") and self._is_managed_edit_layer(layer)
            and not layer.readOnly()
        ) if isinstance(layer, QgsVectorLayer) else False)
        vector = isinstance(layer, QgsVectorLayer)
        editable = bool(
            vector and ready and state.get("can_write")
            and not layer.readOnly() and layer.isEditable()
        )
        geometry_type = QgsWkbTypes.geometryType(layer.wkbType()) if vector else None
        selected = int(layer.selectedFeatureCount()) if vector else 0
        standard = str(layer.customProperty("geoflow/standard_name", "") or "") if layer else ""
        def native_enabled(key, fallback):
            action = self._native_actions.get(key)
            if action is None or not hasattr(action, "isEnabled"):
                return bool(fallback)
            try:
                return bool(fallback and action.isEnabled())
            except (RuntimeError, TypeError):
                return bool(fallback)

        geometry_label = {
            QgsWkbTypes.GeometryType.PointGeometry: "점 생성",
            QgsWkbTypes.GeometryType.LineGeometry: "선 생성",
            QgsWkbTypes.GeometryType.PolygonGeometry: "면 생성",
        }.get(geometry_type, "객체 생성")
        self.panel.addFeatureButton.setToolTip(geometry_label)
        self.panel.addFeatureButton.setEnabled(native_enabled("add", editable))
        self.panel.moveButton.setEnabled(native_enabled("move", editable and selected > 0))
        self.panel.vertexButton.setEnabled(native_enabled("vertex", editable and selected > 0))
        self.panel.splitButton.setEnabled(
            native_enabled("split", editable and geometry_type in (
                QgsWkbTypes.GeometryType.LineGeometry,
                QgsWkbTypes.GeometryType.PolygonGeometry,
            ))
        )
        self.panel.deleteButton.setEnabled(
            native_enabled("delete", editable and selected > 0)
        )
        stack = layer.undoStack() if editable and hasattr(layer, "undoStack") else None
        self.panel.undoButton.setEnabled(native_enabled(
            "undo", bool(stack and stack.canUndo())
        ))
        self.panel.redoButton.setEnabled(native_enabled(
            "redo", bool(stack and stack.canRedo())
        ))
        self.panel.snappingButton.setEnabled(native_enabled("snapping", ready))
        self.panel.snappingButton.blockSignals(True)
        self.panel.snappingButton.setChecked(QgsProject.instance().snappingConfig().enabled())
        self.panel.snappingButton.blockSignals(False)
        self._sync_save_proxy()
        page = self._current_page()
        work = getattr(self.plugin, "work", None)
        depth_support = self.depth.support_status(layer)
        self.depth_batch_button.setEnabled(bool(
            ready and state.get('can_write') and self._is_managed_edit_layer(layer)
            and not layer.readOnly() and depth_support['supported'] and selected >= 2))
        depth_available = self.depth_batch_button.isEnabled()
        direction_targets = self.direction.targets(layer)
        direction_ready = bool(vector and ready and state.get('can_write') and not layer.readOnly()
                               and self._is_managed_edit_layer(layer) and direction_targets)
        self.direction_batch_button.setEnabled(direction_ready and selected > 0)
        self.direction_batch_button.setToolTip('방향각 · ' + (
            '대상 객체를 선택하세요.' if not selected else
            '중앙 방향각 기능 정의를 확인하세요.' if not direction_targets else
            '자동계산 / 직접 회전' if selected == 1 else '선택 객체 일괄계산'))
        stale_page_ids = []
        for page_layer_id, candidate_page in self._form_pages.items():
            candidate_layer = self._layer_by_id(page_layer_id)
            if candidate_layer is None:
                stale_page_ids.append(page_layer_id)
                continue
            self._refresh_direction_page(candidate_page,candidate_layer)
            candidate_standard = str(candidate_layer.customProperty(
                "geoflow/standard_name", ""
            ) or "")
            candidate_editable = bool(
                ready and state.get("can_write") and not candidate_layer.readOnly()
            )
            has_feature = candidate_page.feature_id is not None
            candidate_page.form_actions.saveButton.setEnabled(bool(
                candidate_editable and has_feature and candidate_page.binding.can_save
            ))
            candidate_page.form_actions.previousButton.setEnabled(bool(
                candidate_editable and has_feature and work is not None
                and work.previous_values.available(candidate_page)
            ))
            has_nearby = bool(self.registry.for_layer(candidate_standard))
            candidate_page.form_actions.nearbyButton.setEnabled(bool(
                candidate_editable and has_feature and has_nearby
            ))
            inline_enabled = bool(
                candidate_editable and has_feature
                and self.depth.target_supported(candidate_layer)
            )
            for button in self._depth_field_actions.get(page_layer_id, ()):
                button.setEnabled(inline_enabled)
        for page_layer_id in stale_page_ids:
            self._form_pages.pop(page_layer_id, None)
            self._depth_field_actions.pop(page_layer_id, None)
        geometry_name = (
            QgsWkbTypes.displayString(layer.wkbType()) if vector else "none"
        )
        context_signature = (
            standard, geometry_name, selected,
            bool(page and page.feature_id is not None), depth_available,
            tuple(depth_support["reasons"]),
        )
        if context_signature != self._last_context_signature:
            self._last_context_signature = context_signature
            self._log(
                "edit_tools_context "
                f"layer={standard or 'none'} geometry={geometry_name} "
                f"selected={selected} form_feature={str(context_signature[3]).lower()} "
                f"depth_enabled={str(depth_available).lower()} "
                f"depth_reasons={','.join(depth_support['reasons']) or 'none'}"
            )

    def close(self):
        if self._definition_events is not None:
            self._definition_events.changed.disconnect(self.refresh)
        for layer, slot in self._direction_connections:
            self._disconnect_direction(layer, slot)
        self._direction_connections.clear()
        if self._rotation_dialog is not None:
            self._rotation_dialog.reject()
        if getattr(self, '_depth_results', None) is not None:
            self._depth_results.close()
        self.depth_batch_button.deleteLater()
        self.direction_batch_button.deleteLater()
        if self._calculation_toolbar is not None:
            self._calculation_toolbar.deleteLater()
        self._closed = True
        self.set_mode(False)
        for signal, slot in self._layer_signal_connections:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._layer_signal_connections.clear()
        self._selection_layer_id = ""
        try:
            self.plugin.iface.currentLayerChanged.disconnect(self._active_layer_changed)
        except (RuntimeError, TypeError):
            pass
        try:
            QgsProject.instance().snappingConfigChanged.disconnect(self.refresh)
        except (RuntimeError, TypeError):
            pass
        try:
            self.plugin.dock.visibilityChanged.disconnect(
                self._main_dock_visibility_changed
            )
        except (RuntimeError, TypeError):
            pass
        self.plugin.dock.removeEventFilter(self)
        self.plugin.iface.mainWindow().removeEventFilter(self)
        for signal, slot in self._native_action_connections:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._native_action_connections.clear()
        if self._save_action is not None:
            self._save_action.setShortcuts(self._save_original_shortcuts)
        if self._save_proxy is not None:
            for host, before in self._save_action_hosts:
                try:
                    host.insertAction(before, self._save_action)
                    host.removeAction(self._save_proxy)
                except RuntimeError:
                    pass
            self._save_action_hosts.clear()
            self._save_proxy.deleteLater()
            self._save_proxy = None
            self._save_action = None
        self.palette.hide()
        self.palette.deleteLater()
