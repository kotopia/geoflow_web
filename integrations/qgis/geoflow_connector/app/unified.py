# 제목: app/unified.py
# 기능: 단일 Dock, 로그인/프로젝트/업무 화면 전환 및 종료 보호
"""Single plugin shell around the existing authentication and sync engines."""
import traceback

from qgis.PyQt.QtCore import Qt, QEvent, QObject, QTimer
from qgis.PyQt.QtWidgets import (QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QPushButton, QToolButton, QLabel, QMessageBox, QDialog)
from qgis.core import QgsProject, QgsMessageLog, Qgis
from qgis import utils
from qgis.PyQt import sip
from ..ui.dialog import GeoFlowConnectorDialog
from .state import State, StateManager
from ..ui.presentation import PanelPresentation
from pathlib import Path
from qgis.PyQt.uic import loadUi
from . import protection


# ============================================================
# QGIS 종료 요청과 복구 입력 보호
# ============================================================
class ExitGuard(QObject):
    def __init__(self, engine):
        super().__init__(engine.iface.mainWindow())
        self.engine = engine
        self._approved = False

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Close and self.engine._integration_live:
            # QGIS가 한 번의 종료 과정에서 Close를 다시 보내도 복구 확인을 반복하지 않는다.
            if self._approved:
                event.accept()
                return False
            if not self.engine.guard_transition('QGIS 종료'):
                event.ignore()
                return True
            self._approved = True
            event.accept()
        elif self._approved and event.type() in (
                QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress):
            # 다른 QGIS 구성요소가 종료를 취소한 뒤 사용자가 작업을 재개하면 다시 보호한다.
            self._approved = False
        return False


class LoginDialog(GeoFlowConnectorDialog):
    """Reuses the current login/client implementation; project controls live in Dock."""
    def __init__(self, engine):
        self.engine = engine
        super().__init__(engine.iface.mainWindow(),
            on_open_project=engine._materialize_project, on_sync=engine._sync_active_project,
            on_session_changing=engine._integration_auth_changing,
            on_state_changed=engine.session_changed,
            on_cache_pin_state=engine._active_cache_pin_state,
            on_toggle_cache_pin=engine._toggle_active_cache_pin)

    def _open_project(self):
        self.engine.open_selected_project()

    def _login(self):
        if not self.engine.check_single_instance():
            return
        try:
            super()._login()
        except Exception:
            self.password_edit.clear()
            self.clear_session()
            self.status_label.setText('로그인 요청을 처리하지 못했습니다. 연결을 확인하고 다시 시도하세요.')
            self.engine.log('login_failure')
        if self.client is None:
            self.engine.state_manager.message = '로그인 실패 · 계정 또는 연결을 확인하세요.'
            self.engine.log('login_failure')


# ============================================================
# 단일 Dock 업무 흐름과 프로젝트 전환
# ============================================================
class UnifiedMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.state_manager = StateManager(self)
        self.dock = None
        self.work = None
        self.mapCanvas = self.iface.mapCanvas()
        self._opening = False
        self._project_selector_visible = False
        self._selector_extent = None
        self._unloading = False
        self._last_sync_error = False
        self.sync_center = None
        self._settings_dialog = None
        self._form_connections = []
        self._sync_connections = []
        self._exit_guard = ExitGuard(self)

    def log(self, event):
        # Only controlled event identifiers; no exception bodies, URLs or tokens.
        QgsMessageLog.logMessage(event, 'GeoFlow', Qgis.MessageLevel.Info)

    def log_exception(self, event, exc):
        QgsMessageLog.logMessage(
            f"{event}\n{type(exc).__name__}: {exc}\n{traceback.format_exc()}",
            'GeoFlow',
            Qgis.MessageLevel.Critical,
        )

    def check_single_instance(self):
        others = getattr(utils, 'active_plugins', [])
        registered = getattr(utils, 'plugins', {}).get('geoflow_connector')
        blocked = 'GeoFlow_Kwater' in others or (registered is not None and registered is not self)
        if blocked:
            self.iface.messageBar().pushMessage('GeoFlow', '기존 GeoFlow_Kwater를 비활성화한 후 통합 GeoFlow만 실행하세요.', level=Qgis.Warning)
        return not blocked

    def initGui(self):
        super().initGui()
        self.action.setText('GeoFlow')
        from pathlib import Path
        from qgis.PyQt.QtGui import QIcon
        self.action.setIcon(QIcon(str(Path(__file__).resolve().parents[1] / 'resources' / 'icons' / 'geoflow.png')))
        # Same QAction remains registered once in menu and toolbar.
        for name in ('_cache_pin_action', '_layer_workspace_action'):
            action = getattr(self, name, None)
            if action is not None:
                self.iface.removePluginMenu('GeoFlow', action)
                action.setVisible(False)
        self.state_manager.changed.connect(self.render_state)
        self.iface.mainWindow().installEventFilter(self._exit_guard)
        self.log('plugin_start')

    def integration_state(self):
        state = super().integration_state()
        manager = getattr(self, 'state_manager', None)
        recovering = manager is not None and manager.state == State.ERROR and manager.recovery == State.PROJECT_READY
        if manager is not None and manager.state != State.PROJECT_READY and not recovering:
            state.update(ready=False, can_write=False, layers=())
        return state

    def show_settings(self):
        if not self.integration_state().get('ready'):
            return
        from ..ui.settings_dialog import GeoFlowSettingsDialog
        if self._settings_dialog is None:
            self._settings_dialog = GeoFlowSettingsDialog(self)
        else:
            self._settings_dialog.reload()
        self._settings_dialog.show()
        self._settings_dialog.raise_()
        self._settings_dialog.activateWindow()

    def _ensure_ui(self):
        if self.dialog is not None:
            return
        self.log('edit_tools_init')
        self.dialog = LoginDialog(self)
        self.dock = QDockWidget('GeoFlow', self.iface.mainWindow())
        self.dock.setObjectName('GeoFlowMainDock')
        main_dock_path = Path(__file__).resolve().parents[1] / 'ui' / 'designer' / 'main_dock.ui'
        self.log('edit_tools_main_dock_path=' + str(main_dock_path.resolve()))
        root = loadUi(str(main_dock_path))
        edit_button = root.findChild(QToolButton, 'editModeButton')
        self.log(
            'edit_tools_button_found=' + ('yes' if edit_button is not None else 'no')
        )
        if edit_button is None:
            raise RuntimeError(
                'GeoFlow main dock edit toggle is missing'
            )
        for name in ('GeoFlowRail_info', 'editModeButton',
                     'message', 'stack', 'error_page',
                     'retry_button'):
            setattr(self, name, getattr(root, name))
        self.project_page = self.dialog.project_panel
        self.return_button = self.project_page.return_button
        self.return_button.clicked.connect(self.return_to_current_project)
        self.stack.insertWidget(0, self.project_page)
        self.stack.setCurrentWidget(self.project_page)
        self.presentation = PanelPresentation(self, root)
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
        self.dock.hide()
        from ..ui.project_info import ProjectInfoPopup
        self.project_info = ProjectInfoPopup(self, self.GeoFlowRail_info)
        self.projectNameLabel = self.project_info.project_label
        self.projectCrsLabel = self.project_info.crs_label
        self.projectCrsButton = self.project_info.crs_button
        from ..ui.project_crs import ProjectCrsController
        self.project_crs = ProjectCrsController(
            self, self.projectNameLabel, self.projectCrsLabel,
            self.projectCrsButton,
        )
        from ..ui import edit_tools as edit_tools_module
        self.log(
            'edit_tools_module_path='
            + str(Path(edit_tools_module.__file__).resolve())
        )
        self.edit_tools = edit_tools_module.EditToolsController(
            self, self.editModeButton,
        )
        self.retry_button.clicked.connect(self.recover_screen)
        self.dialog.refresh_button.clicked.connect(self.refresh_projects)

    def run(self):
        if not self.check_single_instance():
            return
        self._ensure_ui()
        if not self.state_manager.authenticated:
            self.dialog.show()
            self.dialog.raise_()
            self.dialog.activateWindow()
        else:
            self.render_state()
            self.dock.show()
            self.dock.raise_()

    def session_changed(self):
        if self._opening or self._unloading:
            return
        if self.dialog is not None and self.dialog.client is not None:
            self.state_manager.set(State.PROJECT_READY if self.dialog.project_opened and self.active_context else State.LOGGED_IN_NO_PROJECT)
            self.dialog.hide()
            self.dock.show()
            self.log('login_success')
        else:
            self.state_manager.set(State.LOGGED_OUT)
        self._integration_changed()

    def render_state(self):
        if self.dock is None:
            return
        manager = self.state_manager
        self.message.setText(manager.message)
        self.project_info.set_user(
            self.dialog.email_edit.text() if manager.authenticated else ""
        )
        busy = manager.state in (State.PROJECT_LOADING, State.PROJECT_SWITCHING)
        self.dialog._set_busy(busy)
        self.dialog.refresh_button.setEnabled(not busy and manager.authenticated)
        if manager.state == State.LOGGED_OUT:
            self.dock.hide()
        elif manager.state == State.PROJECT_READY:
            self._ensure_work()
            self.stack.setCurrentWidget(self.project_page if self._project_selector_visible else self.work)
        elif manager.state == State.ERROR:
            self.stack.setCurrentWidget(self.error_page)
        else:
            self.stack.setCurrentWidget(self.project_page)
        self._update_presentation()
        self._sync_center_changed()

    def show_sync_center(self, status_filter=None):
        self.iface.messageBar().pushMessage(
            "GeoFlow",
            "온라인 전용 저장에서는 로컬 동기화 큐를 사용하지 않습니다.",
            level=Qgis.Info,
            duration=6,
        )

    def _sync_center_changed(self):
        center = getattr(self, "sync_center", None)
        if center is not None:
            center.refresh_if_visible()

    def notify_sync_items(self, status="ALL", count=1):
        """Show a safe message-bar shortcut without changing sync lifecycle."""
        status = str(status or "ALL").upper()
        label = "충돌" if status == "CONFLICT" else "동기화 항목"
        text = f"확인이 필요한 {label} {int(count or 0)}건이 있습니다."
        bar = self.iface.messageBar()
        create = getattr(bar, "createMessage", None)
        push_widget = getattr(bar, "pushWidget", None)
        if callable(create) and callable(push_widget):
            widget = create("GeoFlow", text)
            view = QPushButton("보기", widget)
            view.clicked.connect(
                lambda _checked=False, value=status: self.show_sync_center(value)
            )
            widget.layout().addWidget(view)
            push_widget(widget, Qgis.Warning, 12)
        else:
            bar.pushMessage("GeoFlow", text, level=Qgis.Warning, duration=12)

    def _update_presentation(self):
        available = bool(self.active_context and self.dialog.project_opened and self.state_manager.authenticated)
        self.return_button.setVisible(available)
        self.return_button.setEnabled(available and not self._opening)
        working = self.work is not None and self.stack.currentWidget() is self.work
        self.message.setVisible(not working and bool(self.state_manager.message))
        self.presentation.apply()
        if hasattr(self, 'edit_tools'):
            self.edit_tools.refresh()
            QTimer.singleShot(0, self.edit_tools.log_runtime_state)

    def _ensure_work(self):
        if self.work is None:
            from ..ui.form_host import Main
            self.work = Main(self)
            self.work.setWindowFlags(Qt.WindowType.Widget)
            self.stack.addWidget(self.work)
            self.work.open_button.hide()
            self.presentation.attach_work(self.work)
        self.work.refresh_connection()

    def _ensure_layer_workspace(self):
        # No secondary dock, including during lazy construction.
        if self._workspace_panel is None:
            from ..ui.layer_workspace import GeoFlowLayerWorkspace
            self._workspace_panel = GeoFlowLayerWorkspace(self)
            self._workspace_panel.set_integrated(True)
        return self._workspace_panel

    def acquire_layer_workspace(self, host):
        if self._workspace_host not in (None, host):
            return None
        panel = self._ensure_layer_workspace()
        self._workspace_host = host
        panel.setParent(host)
        panel.show()
        return panel

    def release_layer_workspace(self, host):
        if self._workspace_host is host:
            self._workspace_host = None
            if self._workspace_panel is not None:
                self._workspace_panel.hide()
                self._workspace_panel.setParent(None)

    def _show_layer_workspace(self):
        self.run()

    # ============================================================
    # 미저장 입력·QGIS 편집 버퍼 전환 보호
    # ============================================================
    def guard_transition(self, label):
        if self._opening or self._sync_in_progress:
            return False
        work = getattr(self, "work", None)
        if work is not None and not work.guard_transition(label):
            return False
        try:
            report = protection.inspect(self)
        except Exception as exc:
            self.log_exception('transition_inspection_failure', exc)
            self.iface.messageBar().pushMessage('GeoFlow', 'QGIS 편집 상태 확인 실패로 전환을 중단했습니다.', level=Qgis.Warning)
            return False
        if report['buffers']:
            self.iface.messageBar().pushMessage('GeoFlow', 'QGIS 편집 버퍼를 먼저 저장하거나 명시적으로 취소하세요. 전환을 중단했습니다.', level=Qgis.Warning)
            return False
        return True

    def show_projects(self):
        # Keep A alive while selecting B, and only retire A after B is ready.
        if not self._opening and self.state_manager.authenticated:
            if hasattr(self, 'edit_tools'):
                self.edit_tools.set_mode(False)
            if not self._project_selector_visible and self.active_context:
                from qgis.core import QgsRectangle
                self._selector_extent = QgsRectangle(self.mapCanvas.extent())
            self._project_selector_visible = True
            self.stack.setCurrentWidget(self.project_page)
            self._update_presentation()

    def return_to_current_project(self):
        if self._opening or not self.active_context or not self.dialog.project_opened or not self.state_manager.authenticated:
            return
        self._project_selector_visible = False
        if self.state_manager.state == State.ERROR:
            self.state_manager.set(State.PROJECT_READY)
        else:
            self.stack.setCurrentWidget(self.work)
            self._update_presentation()
        extent, context = self._selector_extent, self.active_context
        self._selector_extent = None
        if extent is not None:
            def restore_extent():
                if not self._unloading and not self._opening and self.active_context is context:
                    self.mapCanvas.setExtent(extent)
                    self.mapCanvas.refresh()
            QTimer.singleShot(0, restore_extent)

    def refresh_projects(self):
        if not self.state_manager.authenticated or self._opening:
            return
        try:
            payload = self.dialog.client.get_json('/gis/api/qgis/projects/')
            projects = payload.get('results')
            if not isinstance(projects, list):
                raise ValueError('Invalid project list contract')
            self.dialog.set_projects(projects)
            self.dialog._set_busy(False)
        except Exception:
            self.state_manager.fail('project_list', '프로젝트 목록을 불러오지 못했습니다.', State.PROJECT_READY if self.active_context else State.LOGGED_IN_NO_PROJECT)

    def open_selected_project(self):
        if not self.check_single_instance() or not self.state_manager.authenticated or not self.guard_transition('프로젝트 열기'):
            return
        row = self.dialog.selected_project()
        if not isinstance(row, dict) or not row.get('manifest_url'):
            return
        previous = State.PROJECT_READY if self.active_context else State.LOGGED_IN_NO_PROJECT
        old_epoch = self._integration_epoch
        old_selected = self._workspace_model.selected_id
        old_active = self.iface.activeLayer()
        from qgis.core import QgsRectangle
        old_extent = QgsRectangle(self.mapCanvas.extent())
        succeeded = False
        self._opening = True
        self.state_manager.set(State.PROJECT_SWITCHING if self.active_context else State.PROJECT_LOADING, '프로젝트를 준비하고 있습니다…')
        try:
            client = self.dialog.client
            manifest = client.get_json(row['manifest_url'])
            result = self._materialize_project(manifest, client)
            if self.dialog.client is not client:
                raise RuntimeError('Session changed during project open')
            self.dialog.project_opened = True
            self.dialog.sync_ready = bool(result.get('sync_supported'))
            succeeded = True
            self._project_selector_visible = False
            self._selector_extent = None
            self.state_manager.set(State.PROJECT_READY, '프로젝트 열기 성공 · 로컬 저장과 서버 동기화는 별도 상태입니다.')
            self.log('project_open_success')
        except Exception as exc:
            self._integration_epoch = old_epoch
            self.dialog.project_opened = bool(self.active_context and self.dialog.client)
            self.state_manager.fail('project_load', '프로젝트 로딩에 실패했습니다. 이전 프로젝트를 보존했습니다. 연결·레이어·metadata를 확인하고 재시도하세요.', previous)
            self.log_exception('project_load_failure', exc)
        finally:
            self._opening = False
            self.render_state()
            self._integration_changed()
            if not succeeded and self.active_context:
                if old_selected:
                    self._workspace_model.select_layer(old_selected)
                if old_active is not None and old_active.id() in QgsProject.instance().mapLayers():
                    self.iface.setActiveLayer(old_active)
                self.mapCanvas.setExtent(old_extent)
                self.mapCanvas.refresh()

    def recover_screen(self):
        self._project_selector_visible = False
        self.state_manager.set(self.state_manager.recovery)
        self._integration_changed()

    def _materialize_project(self, manifest, client, **kwargs):
        if not self.check_single_instance():
            raise RuntimeError('Duplicate GeoFlow plugins')
        self.log('project_materialize_manifest_ok')
        old = self.active_context
        old_client = self.active_client
        old_catalog = self._reference_catalog
        project = QgsProject.instance()
        before = set(project.mapLayers())
        before_groups = set(id(g) for g in project.layerTreeRoot().findGroups())
        # Same project reuse avoids parallel OGR writers of the same cached package.
        if old and str((manifest.get('project') or {}).get('id')) == str(old.get('project_id')):
            from ..cache.snapshot import manifest_cache_fingerprint
            if manifest_cache_fingerprint(manifest) != manifest_cache_fingerprint(old['manifest']):
                raise RuntimeError('Project schema changed; close the current project before reopening')
            old['manifest'] = manifest
            self._load_reference_catalog(manifest, client)
            transport = manifest.get('transport') or {}
            allowed = bool(transport.get('write_authorized') and transport.get('local_editing_supported') and old.get('sync_supported'))
            for layer in protection.owned_layers(old):
                self._configure_layer_fields(layer, self._layer_def(layer), old['project_id'], allowed)
                layer.setCustomProperty('geoflow/local_editing', allowed)
            self.active_client = client
            project = manifest.get('project') or {}
            code = str(project.get('code') or old.get('project_code') or '')
            name = str(project.get('name') or code)
            title = f"{code} {name}" if code and code not in name else name
            self.project_crs.activate(old['project_id'], title)
            return {'loaded': len(protection.owned_layers(old)), 'sync_supported': old.get('sync_supported', False)}
        try:
            self.log('project_materialize_super_start')
            result = super()._materialize_project(manifest, client, **kwargs)
            if not result.get('loaded'):
                raise RuntimeError('No project layers loaded')
            project = manifest.get('project') or {}
            code = str(project.get('code') or (self.active_context or {}).get('project_code') or '')
            name = str(project.get('name') or code)
            title = f"{code} {name}" if code and code not in name else name
            self.project_crs.activate((self.active_context or {}).get('project_id', ''), title)
            self._disconnect_sync_layers((old or {}).get('layer_ids', []))
            protection.remove_owned(old)
            self.log('project_materialize_done')
            return result
        except Exception:
            self._stop_realtime_socket()
            for timer in (self._realtime_delta_timer, self._realtime_reconnect_timer, self._realtime_poll_timer):
                timer.stop()
            # Only newly materialized, tagged layers, never user layers.
            added = [lid for lid, layer in project.mapLayers().items() if lid not in before and layer.customProperty('geoflow/managed', False)]
            self._disconnect_sync_layers(added)
            project.removeMapLayers(added)
            for group in reversed(project.layerTreeRoot().findGroups()):
                if id(group) not in before_groups and group.customProperty('geoflow/context_owner', '') and not group.findLayers():
                    group.parent().removeChildNode(group)
            self.active_context, self._reference_catalog = old, old_catalog
            if old:
                self._write_project_metadata(project, old['manifest'], old['project_id'], old['project_code'], old['package_path'], old.get('sync_supported', False), old.get('changeset_supported', False))
            else:
                project.removeEntry('GeoFlow', '')
            self.active_client = old_client if self.dialog and self.dialog.client is old_client else None
            if old and self.active_client is not None:
                self._load_reference_catalog(old['manifest'], self.active_client)
                old_project = (old.get('manifest') or {}).get('project') or {}
                old_code = str(old_project.get('code') or old.get('project_code') or '')
                old_name = str(old_project.get('name') or old_code)
                old_title = f"{old_code} {old_name}" if old_code and old_code not in old_name else old_name
                self.project_crs.activate(old.get('project_id', ''), old_title)
            else:
                self._reference_service.clear()
                self.project_crs.deactivate()
            self._watch_integration_layers()
            if self.active_client is not None:
                self._start_realtime_socket()
            raise

    def _sync_active_project(self, client, automatic=False):
        if not self.check_single_instance() or client is not self.active_client or not self.dialog or client is not self.dialog.client:
            raise RuntimeError('Inactive GeoFlow session')
        try:
            result = super()._sync_active_project(client, automatic=automatic)
            self._last_sync_error = False
            return result
        except Exception:
            self._last_sync_error = True
            self.log('online_server_refresh_failed')
            raise
        finally:
            self._sync_center_changed()

    def logout_requested(self):
        if not self.guard_transition('로그아웃'):
            return
        old = self.active_context
        self.logout_integration_session()
        self._disconnect_sync_layers((old or {}).get('layer_ids', []))
        protection.remove_owned(old)
        self.active_context = None
        if hasattr(self, 'project_crs'):
            self.project_crs.deactivate()
        if hasattr(self, 'edit_tools'):
            self.edit_tools.set_mode(False)
        QgsProject.instance().removeEntry('GeoFlow', '')
        self.state_manager.set(State.LOGGED_OUT)
        self._integration_changed()

    def _integration_auth_changing(self):
        super()._integration_auth_changing()

    def unload(self):
        self._unloading = True
        if self._settings_dialog is not None:
            self._settings_dialog.close()
            self._settings_dialog = None
        if self.sync_center is not None:
            self.sync_center.close()
            self.sync_center = None
        if hasattr(self, 'edit_tools'):
            self.edit_tools.close()
        if hasattr(self, 'project_crs'):
            self.project_crs.close()
        if hasattr(self, 'project_info'):
            self.project_info.close()
        if hasattr(self, 'presentation'):
            self.presentation.close()
        self._disconnect_sync_layers()
        self.iface.mainWindow().removeEventFilter(self._exit_guard)
        if self.work is not None:
            self.work.shutdown()
            self.work = None
        if self._workspace_panel is not None:
            self._workspace_panel.shutdown()
            self._workspace_panel.deleteLater()
            self._workspace_panel = None
        if self.dock is not None:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        super().unload()
        self.state_manager.changed.disconnect(self.render_state)
        self.log('plugin_unload')

    def _run_cache_lifecycle(self):
        if not self._opening:
            return super()._run_cache_lifecycle()

    def _connect_sync(self, layer, signal, slot):
        signal.connect(slot)
        # A bound signal may outlive its C++ sender after project close/removal.
        # Keep the exact sender wrapper to check lifetime before disconnecting.
        self._sync_connections.append((layer.id(), layer, signal, slot))

    def _disconnect_sync_layers(self, ids=None):
        keep = []
        for lid, layer, signal, slot in self._sync_connections:
            if sip.isdeleted(layer):
                # Qt already removed the connection when the sender died.
                # Calling disconnect here can crash before Python can catch it.
                continue
            if ids is not None and lid not in ids:
                keep.append((lid, layer, signal, slot))
                continue
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._sync_connections = keep
