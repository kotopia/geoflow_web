# GeoFlow QGIS 플러그인 - 중앙 Dynamic Form 호스트
# 레이어 선택·객체 바인딩·로컬 폼 배치 편집 화면을 하나의 업무 패널로 연결한다.
import json
import os

from qgis.PyQt.QtCore import QDate, Qt, QTimer, QSettings
from qgis.PyQt.QtWidgets import (
    QDialog, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QTabWidget,
    QToolBar, QToolButton, QMenu, QVBoxLayout, QWidget,
)
from qgis.PyQt.uic import loadUiType
from qgis.core import QgsMessageLog, Qgis, QgsProject

from .connector_adapter import ConnectorAdapter
from .form_actions import FormActionToolbar
from .photo_section import PhotoSection
from .behaviors import create_shape_switches
from ..api.references import fields_with_worker_references, worker_reference_codes
from ..forms.dynamic.binding import DynamicFormBinding
from ..forms.dynamic.contract import layer_fields
from ..forms.dynamic.form import DynamicForm
from ..forms.dynamic.layout_model import central_photo_tab_spec
from ..forms.dynamic.layout_editor import FormLayoutEditor, LocalFormLayoutStore
from ..layers.identify import IdentifyGeometry
from ..services.previous_values import PreviousValueService
from ..services.settings import GeoFlowSettingsService


FORM_CLASS, _ = loadUiType(os.path.join(os.path.dirname(__file__), "designer", "form_host.ui"))


# ============================================================
# 레이어 선택·객체 바인딩·Dynamic Form 통합 화면
# ============================================================
class Main(QWidget, FORM_CLASS):
    def __init__(self, plugin, worker=None, date=None, project_code=None):
        super().__init__()
        self.plugin = plugin
        self.worker = worker or ""
        self.date = date or QDate.currentDate()
        self.project_code = project_code or ""
        self._signature = None
        self._closed = self._refreshing = self._split_initialized = False
        self._shutting_down = False
        self._selection_guarding = False
        self.pages, self.archives = {}, []
        from ..forms.common.lifecycle import BusinessFormSettings
        self._form_settings = BusinessFormSettings()
        self._layout_store = LocalFormLayoutStore()
        self.previous_values = PreviousValueService(plugin)
        self.geoflow_settings = GeoFlowSettingsService(plugin)
        self.setupUi(self)
        self.status = self.connectionStatus
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.workspaceSplitter.setSizes([200, 500])
        self.workspaceSplitter.setStretchFactor(1, 1)
        self.workspaceSplitter.setCollapsible(1, True)
        self.layerListHost.setMinimumWidth(230)
        self.adapter = ConnectorAdapter(plugin.iface, self)
        self.placeholder = QLabel("레이어를 선택하세요")
        self.placeholder.setWordWrap(True)
        self.placeholder.setTextFormat(Qt.TextFormat.PlainText)
        self.formStack.addWidget(self.placeholder)
        self.list_notice = QLabel("GeoFlow Connector를 설치·활성화하세요.")
        self.list_notice.setWordWrap(True)
        self.layerListLayout.addWidget(self.list_notice)
        toolbar = QToolBar(self)
        self.presentation_toolbar = toolbar
        self.open_button = QPushButton("Connector 열기")
        self.select_button = QToolButton(self)
        self.select_button.setText("객체 선택")
        self.add_button = QPushButton("추가")
        self.save_button = QPushButton("현재 객체 저장")
        self.zoom_button = QPushButton("범위 이동")
        self.retained_button = QPushButton("보존 입력")
        self.reference_diagnostic_button = QPushButton("중앙 정의 진단")
        self.layout_button = QPushButton("폼 배치 편집")
        self.select_button.setCheckable(True)
        self.select_button.setStyleSheet(
            "QPushButton:checked { background-color: #dbeafe; "
            "border: 1px solid #3b7ddd; border-radius: 4px; }"
        )
        for button in (self.select_button, self.add_button, self.save_button,
                       self.zoom_button, self.retained_button, self.layout_button,
                       self.reference_diagnostic_button):
            toolbar.addWidget(button)
        # Saving remains wired to the existing lifecycle, but its user-facing
        # entry point now lives in the Dynamic Form tab corner toolbar.
        self.save_button.hide()
        self.add_button.setEnabled(False)
        self.add_button.setToolTip("도형 추가는 QGIS 편집 도구를 사용합니다.")
        self.open_button.clicked.connect(self.adapter.open_connector)
        self.save_button.clicked.connect(self.save_current)
        self.select_button.clicked.connect(self.set_select_map_tool)
        self.zoom_button.clicked.connect(self.adapter.zoom_selected)
        self.retained_button.clicked.connect(self.show_retained)
        self.reference_diagnostic_button.clicked.connect(self.show_definition_diagnostics)
        self.layout_button.clicked.connect(self.edit_form_layout)
        self.verticalLayout.insertWidget(1, toolbar)
        self.verticalLayout.setStretch(2, 1)
        self.select_tool = IdentifyGeometry(
            plugin.mapCanvas, layer_provider=self.adapter.layers_by_id,
            active_layer=plugin.iface.activeLayer,
            notify=lambda text: plugin.iface.messageBar().pushMessage('GeoFlow', text, duration=3))
        self.select_tool.mode = str(QSettings().value('GeoFlowConnector/selectionMode', 'single'))
        if self.select_tool.mode not in ('single', 'area'):
            self.select_tool.mode = 'single'
        self.configure_selection_button(self.select_button)
        presentation = getattr(plugin, 'presentation', None)
        rail = getattr(presentation, 'buttons', {}).get('select')
        if rail is not None:
            self.configure_selection_button(rail)
        plugin.iface.currentLayerChanged.connect(self.select_tool.cancel_drag)
        QgsProject.instance().cleared.connect(self.select_tool.cancel_drag)
        self.select_tool.geomIdentified.connect(self.on_feature_selected)
        self.select_tool.noFeatureIdentified.connect(self._empty_map_clicked)
        plugin.mapCanvas.mapToolSet.connect(self._sync_select_tool_state)
        self.adapter.changed.connect(self.refresh_connection)
        self.adapter.selectionChanged.connect(self._selection_changed)
        self.adapter.objectSelected.connect(self._object_selected)
        self._photo_policy_service = getattr(plugin, "_photo_policy_service", None)
        if self._photo_policy_service is not None:
            self._photo_policy_service.changed.connect(self._photo_policy_changed)
        self._retained_window = None
        self.refresh_connection()
        self._sync_select_tool_state()

    def configure_selection_button(self, button):
        menu = QMenu(button)
        for mode, label in (('single', '단일 선택'), ('area', '영역 선택')):
            menu.addAction(label, lambda checked=False, m=mode: self.set_selection_mode(m))
        button.setMenu(menu)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.DelayedPopup)
        self._selection_button_hint(button)

    def _selection_button_hint(self, button):
        from qgis.core import QgsApplication
        area = self.select_tool.mode == 'area'
        button.setIcon(QgsApplication.getThemeIcon('/mActionSelectRectangle.svg' if area else '/mActionIdentify.svg'))
        button.setToolTip(('영역 선택' if area else '단일 선택') + ' · 길게 눌러 모드 변경 · Shift 추가 / Ctrl 해제')

    def set_selection_mode(self, mode):
        self.select_tool.cancel_drag()
        self.select_tool.mode = mode
        QSettings().setValue('GeoFlowConnector/selectionMode', mode)
        buttons = [self.select_button]
        presentation = getattr(self.plugin, 'presentation', None)
        rail = getattr(presentation, 'buttons', {}).get('select')
        if rail is not None:
            buttons.append(rail)
        for button in buttons:
            self._selection_button_hint(button)
        if self.adapter.selected_layer_id() in self.adapter.layers_by_id():
            self.plugin.mapCanvas.setMapTool(self.select_tool)
        self._sync_select_tool_state()

    @property
    def formHeader(self):
        page = self.formStack.currentWidget()
        return getattr(page, "form_actions", None)

    def _sync_header(self, *args):
        return None

    def _sync_select_tool_state(self, *args):
        active = self.plugin.mapCanvas.mapTool() is self.select_tool
        self.select_button.setChecked(active)
        presentation = getattr(self.plugin, "presentation", None)
        rail_button = getattr(presentation, "buttons", {}).get("select") if presentation else None
        if rail_button is not None:
            rail_button.setChecked(active)

    def _definition_service(self):
        return getattr(self.plugin, "_definition_service", None)

    def show_definition_diagnostics(self):
        service = self._definition_service()
        references = getattr(self.plugin, "_reference_service", None)
        definition = getattr(service, "definition", {}) or {}
        payload = {
            "project": self.plugin.integration_state(),
            "definition": {"state": getattr(service, "state", "missing"),
                           "revision": definition.get("revision", ""),
                           "field_count": len(definition.get("fields", [])),
                           "rule_count": len(definition.get("rules", [])),
                           "error": getattr(service, "error", "")},
            "reference": getattr(references, "diagnostic", lambda: {"state": "missing"})(),
        }
        dialog = QDialog(self)
        dialog.setWindowTitle("GeoFlow 중앙 정의 · 현재 실행 상태")
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit(dialog)
        text.setReadOnly(True)
        text.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        layout.addWidget(text)
        dialog.resize(780, 680)
        dialog.exec()

    def _retained(self):
        if self._retained_window is None:
            window = QDialog(self.plugin.iface.mainWindow())
            window.setWindowTitle("GeoFlow · 보존 입력 (편집·저장 불가)")
            layout = QVBoxLayout(window)
            layout.addWidget(QLabel("이전 연결의 임시 입력입니다. 필요한 내용을 확인한 뒤 현재 객체에 다시 입력하세요."))
            window.tabs = QTabWidget(window)
            layout.addWidget(window.tabs)
            window.resize(800, 850)
            self._retained_window = window
        return self._retained_window

    def show_retained(self):
        if self.archives:
            self._retained().show()
            self._retained().raise_()

    def _freeze_page(self, layer_id):
        page = self.pages[layer_id]
        page.binding.has_actual_changes()
        page = self.pages.pop(layer_id)
        page.binding.dispose()
        page.form.setEnabled(False)
        self.formStack.removeWidget(page)
        if page.dirty and not self._shutting_down:
            page.note.setText("이전 연결·객체의 입력을 보존했습니다. 편집·저장할 수 없습니다.\n" + page.note.text())
            page.note.show()
            self._retained().tabs.addTab(page, page.project_name + " · " + page.standard)
            self.archives.append(page)
        else:
            page.deleteLater()

    def _stop_selection_tool(self):
        if self.plugin.mapCanvas.mapTool() is self.select_tool:
            self.plugin.mapCanvas.unsetMapTool(self.select_tool)
        self._sync_select_tool_state()

    def refresh_connection(self):
        if self._closed or self._refreshing or getattr(self.plugin, "_opening", False):
            return
        self._refreshing = True
        try:
            state = self.adapter.state()
            service = self._definition_service()
            definition = getattr(service, "definition", {}) or {}
            revision = definition.get("revision", "")
            signature = (state.get("instance"), state["epoch"], state["ready"],
                         state["project_id"], state["can_write"], revision)
            if signature != self._signature:
                self._stop_selection_tool()
                for layer_id in list(self.pages):
                    self._freeze_page(layer_id)
                self._signature = signature
            self.project_code = state["project_code"]
            layers = self.adapter.layers_by_id(state)
            standards = {row.get("layer_standard_name") for row in definition.get("fields", [])}
            self._form_settings.update(layers, standards if getattr(service, "state", "") == "ready" else set())
            panel = self.adapter.attach_workspace(self.layerListHost)
            if panel is not None:
                self.layerListLayout.addWidget(panel)
            available = state["available"] and not state.get("upgrade_required")
            self.list_notice.setVisible(not available)
            self.open_button.setEnabled(self.adapter.connector() is not None)
            if state.get("upgrade_required"):
                message = "통합 목록 인터페이스 버전이 맞지 않습니다."
            elif not state["available"]:
                message = "GeoFlow Connector를 설치·활성화하세요."
            elif not state["authenticated"]:
                message = "로그인이 필요합니다. Connector 열기 버튼을 사용하세요."
            elif not state["ready"]:
                message = "GeoFlow Connector에서 프로젝트를 여세요."
            elif getattr(service, "state", "") == "loading":
                message = "중앙 Final Form Definition을 불러오는 중입니다."
            elif getattr(service, "state", "") != "ready":
                message = getattr(service, "error", "중앙 Final Form Definition을 사용할 수 없습니다.")
            else:
                mode = "편집 권한 있음" if state["can_write"] else "읽기 전용"
                message = f"{state['project_name']} · {mode} · 중앙 Dynamic Form {revision[:8]}"
            self.status.setText(message)
            references = getattr(self.plugin, "_reference_service", None)
            if getattr(references, "state", "") == "ready":
                codes = worker_reference_codes(references.catalog)
                for page in self.pages.values():
                    page.form.set_worker_reference_codes(codes)
            self._display_layer(self.adapter.selected_layer_id())
            self.retained_button.setEnabled(bool(self.archives))
            self.retained_button.setText(f"보존 입력 ({len(self.archives)})")
        finally:
            self._refreshing = False

    def _selection_changed(self, layer_id):
        if not self._closed and not getattr(self.plugin, "_opening", False):
            current = self.formStack.currentWidget()
            if (not self._selection_guarding and current in self.pages.values()
                    and current.layer_id != layer_id and self._update_page_dirty(current)):
                self._selection_guarding = True
                try:
                    if not self._guard_object_transition(None, None):
                        self.adapter.select_layer(current.layer_id)
                        self._display_layer(current.layer_id)
                        return
                finally:
                    self._selection_guarding = False
            self.refresh_connection()
            self._display_layer(layer_id)

    def _photo_policy_changed(self):
        """Refresh only the selected photo section; never rebuild a dirty form."""
        if self._closed or getattr(self.plugin, "_opening", False):
            return
        state = self.adapter.state()
        service = self._photo_policy_service
        if (not state.get("ready") or service is None or
                str(getattr(service, "project_id", "")) != str(state.get("project_id") or "")):
            return
        layer_id = self.adapter.selected_layer_id()
        page = self.pages.get(layer_id)
        if page is None or page.feature_id is None or not page.photos.feature_uuid:
            return
        page.photos.refresh_policy()
        self._sync_photo_tab(page)

    def _display_layer(self, layer_id):
        layer = self.adapter.layers_by_id().get(layer_id)
        self.select_button.setEnabled(layer is not None)
        self.zoom_button.setEnabled(layer is not None)
        self.layout_button.setEnabled(layer is not None)
        service = self._definition_service()
        if layer is None:
            self.placeholder.setText("현재 프로젝트의 GeoFlow 레이어를 선택하세요.")
            self.formStack.setCurrentWidget(self.placeholder)
            self.save_button.setEnabled(False)
            return
        if service is None or service.state != "ready":
            self.placeholder.setText("중앙 Final Form Definition을 확인하는 중입니다. 기존 폼으로 대체하지 않습니다.")
            self.formStack.setCurrentWidget(self.placeholder)
            self.save_button.setEnabled(False)
            return
        standard = str(layer.customProperty("geoflow/standard_name", "")).upper()
        fields = fields_with_worker_references(
            layer_fields(service.definition, standard),
            getattr(getattr(self.plugin, "_reference_service", None), "catalog", {}),
        )
        if not fields:
            self.placeholder.setText(f"{layer.name()} · {standard}\n중앙 업무정의에 이 레이어의 필드가 없습니다.")
            self.formStack.setCurrentWidget(self.placeholder)
            self.save_button.setEnabled(False)
            return
        if layer_id not in self.pages:
            self._create_form(layer, standard, fields)
        page = self.pages[layer_id]
        self.save_button.setEnabled(page.binding.can_save)
        if hasattr(self.plugin, "presentation"):
            from .presentation import PanelMode
            self.formStack.setVisible(self.plugin.presentation.mode == PanelMode.FULL)
        else:
            self.formStack.show()
        if not self._split_initialized and not hasattr(self.plugin, "presentation"):
            self._split_initialized = True
            QTimer.singleShot(0, lambda: self.workspaceSplitter.setSizes([200, 500]) if not self._closed else None)
        self.formStack.setCurrentWidget(page)
        self._update_page_dirty(page)
        QTimer.singleShot(0, lambda p=page: self._log_form_runtime(p))

    def _create_form(self, layer, standard, fields):
        state, service = self.adapter.state(), self._definition_service()
        page = QWidget()
        page.project_name, page.standard = state["project_name"], standard
        page.project_id, page.layer_id = state.get("project_id", ""), layer.id()
        page.readonly, page.feature_id, page.dirty = layer.readOnly(), None, False
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        page.note = QLabel(f"{standard} · 객체를 선택하세요")
        page.note.setTextFormat(Qt.TextFormat.PlainText)
        page.note.setWordWrap(True)
        page.note.hide()
        layout.addWidget(page.note)
        manifest_layers = (self.plugin.active_context or {}).get("manifest", {}).get("layers", [])
        page.display_name = self._layer_display_name(manifest_layers, standard)
        local_layout = self._layout_store.load(standard, fields)
        page.form = DynamicForm(
            service.definition, fields, page, layer=standard, form_layout=local_layout
        )
        page.shape_switches = create_shape_switches(layer, page.form, page.form)
        page.tabs = page.form.tabs
        page.form_actions = FormActionToolbar(page.form)
        page.form_actions.apply_preferences(
            self.geoflow_settings, page.project_id
        )
        page.form.set_header_widget(page.form_actions)
        self._apply_page_chrome(page)
        page.form.layoutChanged.connect(
            lambda p=page: self._apply_page_chrome(p)
        )
        page.form_actions.saveButton.clicked.connect(
            lambda _checked=False, p=page: self._save_page(p)
        )
        page.form_actions.layoutButton.clicked.connect(self.edit_form_layout)
        page.form_actions.referenceRefreshButton.clicked.connect(
            self.plugin.refresh_reference_catalog
        )
        tab_count_before = page.tabs.count()
        photo_tab = central_photo_tab_spec(fields)
        has_photo_capability = bool(
            layer.customProperty("geoflow/managed", False)
            and layer.customProperty("geoflow/definition_layer_id", "")
        )
        page.photo_dialog = None
        if has_photo_capability:
            photo_metadata = photo_tab or {"title": "사진", "index": None}
            page.photos = PhotoSection(self.plugin, page, layer, page.tabs)
            page.photo_tab_index = page.form.add_auxiliary_tab(
                page.photos,
                photo_metadata["title"],
                visible=False,
                index=photo_metadata["index"],
            )
            page.photos.tabNeededChanged.connect(
                lambda needed, p=page: self._sync_photo_tab(p, needed)
            )
        else:
            page.photo_dialog = QDialog(page)
            page.photo_dialog.setObjectName("GeoFlowPhotoManagerDialog")
            page.photo_dialog.setModal(False)
            page.photo_dialog.setWindowTitle("사진 보기/관리")
            page.photo_dialog.resize(720, 600)
            photo_dialog_layout = QVBoxLayout(page.photo_dialog)
            photo_dialog_layout.setContentsMargins(0, 0, 0, 0)
            page.photos = PhotoSection(
                self.plugin, page, layer, page.photo_dialog
            )
            photo_dialog_layout.addWidget(page.photos)
        page.photos.bind_action_button(page.form_actions.photoButton)
        self._log_photo_runtime(
            page,
            has_photo_capability=has_photo_capability,
            photo_tab=photo_tab,
            tab_count_before=tab_count_before,
            stage="build",
        )
        layout.addWidget(page.form)
        layout.setStretch(1, 1)
        page.form.setEnabled(bool(state["can_write"] and not layer.readOnly()))
        self.pages[layer.id()] = page
        self.formStack.addWidget(page)
        page.binding = DynamicFormBinding(
            page, layer, page.form, state["can_write"],
            user_context=getattr(self.plugin, "current_user_context", lambda: {})(),
            commit_callback=getattr(self.plugin, "commit_layer_online", None),
        )
        page.form_actions.saveButton.setEnabled(False)
        page.update_dirty = lambda p=page: self._update_page_dirty(p)
        edit_tools = getattr(self.plugin, "edit_tools", None)
        if edit_tools is not None:
            edit_tools.register_form_page(page, layer)
        page.photos.dirtyChanged.connect(lambda _dirty, p=page: self._update_page_dirty(p))
        self._update_page_dirty(page)

    @staticmethod
    def _sync_photo_tab(page, needed=None):
        """Show the registered photo tab only for content or explicit use."""
        if needed is None:
            needed = page.photos.tab_needed()
        page.form.set_auxiliary_tab_visible(page.photos, bool(needed))

    @staticmethod
    def _layer_display_name(manifest_layers, standard):
        """Resolve the central/manifest label without a local name mapping."""
        return str(next((row.get("label") for row in manifest_layers
            if str(row.get("standard_name", "")).upper() == standard), standard) or standard)

    @staticmethod
    def _apply_page_chrome(page):
        """Keep a stable one-line layer/action header above central tabs."""
        page.form_actions.set_layer_title(page.display_name)
        page.form_actions.show()

    @staticmethod
    def _geometry_text(widget):
        geometry = widget.geometry()
        return f"{geometry.x()},{geometry.y()},{geometry.width()},{geometry.height()}"

    @classmethod
    def _log_form_runtime(cls, page):
        """Log non-sensitive runtime geometry for the installed QGIS UI."""
        try:
            header = page.form_actions
            tabs = page.tabs
            buttons = (
                "saveButton", "previousButton", "nearbyButton", "layoutButton",
                "referenceRefreshButton", "photoButton",
            )
            button_state = []
            for name in buttons:
                button = getattr(header, name)
                button_state.append(
                    f"{name}:visible={int(button.isVisible())},hidden={int(button.isHidden())},"
                    f"enabled={int(button.isEnabled())},geometry={cls._geometry_text(button)},"
                    f"parent={type(button.parentWidget()).__name__}"
                )
            photo_index = tabs.indexOf(page.photos)
            message = (
                f"form_runtime layer={page.standard} "
                f"header_geometry={cls._geometry_text(header)} "
                f"header_visible={int(header.isVisible())} "
                f"tabs_geometry={cls._geometry_text(tabs)} "
                f"tabbar_geometry={cls._geometry_text(tabs.tabBar())} "
                f"corner_widget={int(tabs.cornerWidget(Qt.Corner.TopRightCorner) is not None)} "
                f"photo_parent={type(page.photos.parentWidget()).__name__} "
                f"photo_tab_index={photo_index} actions=[{' ; '.join(button_state)}]"
            )
            if message == getattr(page, "_runtime_geometry_log", ""):
                return
            page._runtime_geometry_log = message
            QgsMessageLog.logMessage(message, "GeoFlow", Qgis.MessageLevel.Info)
        except (AttributeError, RuntimeError, TypeError):
            return

    @staticmethod
    def _log_photo_runtime(
        page, *, has_photo_capability=None, photo_tab=None,
        tab_count_before=None, stage="feature",
    ):
        """Trace central photo-tab binding independently from photo capability."""
        try:
            tabs = page.tabs
            if has_photo_capability is None:
                layer = page.photos.layer
                has_photo_capability = bool(
                    layer.customProperty("geoflow/managed", False)
                    and layer.customProperty("geoflow/definition_layer_id", "")
                )
            if photo_tab is None:
                photo_tab = central_photo_tab_spec(page.form.fields)
            actual_index = tabs.indexOf(page.photos)
            tab_visible = bool(
                actual_index >= 0 and tabs.isTabVisible(actual_index)
            )
            titles = [tabs.tabText(index) for index in range(tabs.count())]
            message = (
                f"[PHOTO] stage={stage} layer={str(page.standard).lower()} "
                f"definition_photo_section={str(photo_tab is not None).lower()} "
                f"capability={str(bool(has_photo_capability)).lower()} "
                f"PhotoSection_created={str(page.photos is not None).lower()} "
                f"policy_found={'yes' if getattr(page.photos, 'policy', None) else 'no'} "
                f"tab_needed={str(page.photos.tab_needed()).lower()} "
                f"parent={type(page.photos.parentWidget()).__name__} "
                f"requested_tab_index={photo_tab['index'] if photo_tab else -1} "
                f"photo_tab_index={actual_index} "
                f"tab_visible={str(tab_visible).lower()} "
                f"tab_count_before={tab_count_before if tab_count_before is not None else tabs.count()} "
                f"actual_tab_count={tabs.count()} titles={titles!r} "
                f"feature_id={getattr(page.photos, 'feature_uuid', '') or '-'} "
                f"existing_photos={len(getattr(page.photos, 'photos', ()) or ())}"
            )
            QgsMessageLog.logMessage(message, "GeoFlow", Qgis.MessageLevel.Info)
        except (AttributeError, RuntimeError, TypeError):
            return

    def _update_page_dirty(self, page):
        binding = getattr(page, "binding", None)
        photos = getattr(page, "photos", None)
        # Object navigation guards only unsaved Dynamic Form attributes.
        # Geometry/create/delete work belongs to the layer edit session and is
        # committed as one changeset from the explicit save action.
        form_dirty = bool(binding and binding.dirty)
        photo_dirty = bool(photos and photos.has_pending_changes())
        page.dirty = form_dirty or photo_dirty
        suffix = " *" if page.dirty else ""
        if self.formStack.currentWidget() is page:
            self.save_button.setText("현재 객체 저장" + suffix)
        if hasattr(page, "form_actions"):
            page.form_actions.saveButton.setToolTip("현재 객체 저장" + suffix)
        return page.dirty

    def _discard_page(self, page):
        page.photos.discard_pending(reload=False)
        ok = page.binding.discard()
        if ok and page.feature_id is not None:
            page.photos.refresh_policy()
        self._update_page_dirty(page)
        return ok

    def _save_page(self, page):
        if not page.binding.save():
            self._update_page_dirty(page)
            return False
        result = page.photos.commit_pending()
        self._update_page_dirty(page)
        if not result["ok"]:
            page.note.setText(
                f"저장하지 못한 항목이 있습니다. 완료 {result['completed']}건 · "
                + " / ".join(result["errors"][:3])
            )
            return False
        self.previous_values.capture(page)
        edit_tools = getattr(self.plugin, "edit_tools", None)
        if edit_tools is not None:
            edit_tools.refresh()
        page.note.setText("현재 객체의 기본정보와 사진을 서버에 저장했습니다.")
        return True

    def _dirty_page(self, incoming_page=None, incoming_feature_id=None):
        for page in self.pages.values():
            if page.binding.is_feature_deleted():
                self._clear_deleted_page(page)
                continue
            page.binding.has_actual_changes()
            self._update_page_dirty(page)
            if not page.dirty:
                continue
            if page is incoming_page and page.feature_id == incoming_feature_id:
                continue
            return page
        return None

    def _clear_deleted_page(self, page):
        """Detach a deleted feature from the form without rolling back DELETE."""
        page.photos.clear()
        page.binding.clear_deleted()
        page.dirty = False
        page.note.setText("객체가 삭제되었습니다. 다른 객체를 선택하세요.")
        page.form_actions.saveButton.setEnabled(False)
        if self.formStack.currentWidget() is page:
            self.save_button.setEnabled(False)
        self._update_page_dirty(page)

    def _guard_object_transition(self, incoming_page, feature_id):
        page = self._dirty_page(incoming_page, feature_id)
        if page is None:
            return True
        reason = "form_dirty" if page.binding.has_form_changes() else "qgis_buffer_dirty"
        QgsMessageLog.logMessage(
            f"[NAV] blocked reason={reason} layer_id={page.layer_id} "
            f"feature_id={page.feature_id}",
            "GeoFlow", Qgis.MessageLevel.Info,
        )
        dialog = QMessageBox(self)
        dialog.setWindowTitle("GeoFlow · 객체 이동")
        dialog.setText("현재 객체에 저장하지 않은 변경사항이 있습니다.")
        save = dialog.addButton("저장 후 이동", QMessageBox.ButtonRole.AcceptRole)
        discard = dialog.addButton("변경 취소 후 이동", QMessageBox.ButtonRole.DestructiveRole)
        dialog.addButton("계속 편집", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        if dialog.clickedButton() is save:
            return self._save_page(page)
        if dialog.clickedButton() is discard:
            return self._discard_page(page)
        page.note.setText("현재 객체 편집을 계속합니다.")
        self.adapter.select_layer(page.layer_id)
        self._display_layer(page.layer_id)
        layer = self.adapter.layers_by_id().get(page.layer_id)
        if layer is not None and page.feature_id is not None:
            layer.selectByIds([page.feature_id])
        for other_id, other_layer in self.adapter.layers_by_id().items():
            if other_id != page.layer_id and other_layer.selectedFeatureIds():
                other_layer.removeSelection()
        return False

    def guard_transition(self, label):
        dirty = []
        for page in self.pages.values():
            if page.binding.is_feature_deleted():
                self._clear_deleted_page(page)
                continue
            if self._update_page_dirty(page):
                dirty.append(page)
        if not dirty:
            return True
        for page in dirty:
            reason = "form_dirty" if page.binding.has_form_changes() else "qgis_buffer_dirty"
            QgsMessageLog.logMessage(
                f"[NAV] blocked reason={reason} label={label} "
                f"layer_id={page.layer_id} feature_id={page.feature_id}",
                "GeoFlow", Qgis.MessageLevel.Info,
            )
        closing = label == "QGIS 종료"
        dialog = QMessageBox(self)
        dialog.setWindowTitle("GeoFlow · " + label)
        dialog.setText("저장하지 않은 변경사항이 있습니다.")
        save = dialog.addButton("저장 후 종료" if closing else "저장 후 이동",
                                QMessageBox.ButtonRole.AcceptRole)
        discard = dialog.addButton("변경 취소 후 종료" if closing else "변경 취소 후 이동",
                                   QMessageBox.ButtonRole.DestructiveRole)
        dialog.addButton("종료 취소" if closing else "계속 편집",
                         QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        if dialog.clickedButton() is save:
            return all(self._save_page(page) for page in dirty)
        if dialog.clickedButton() is discard:
            return all(self._discard_page(page) for page in dirty)
        return False

    # ============================================================
    # 레이어별 로컬 속성폼 배치 편집
    # ============================================================
    def edit_form_layout(self):
        layer_id = self.adapter.selected_layer_id()
        page = self.pages.get(layer_id)
        if page is None:
            return
        editor = FormLayoutEditor(
            page.standard, page.form.fields, page.form.form_layout,
            self.plugin.iface.mainWindow(),
        )
        dialog_code = getattr(QDialog, "DialogCode", QDialog)
        if editor.exec() != dialog_code.Accepted:
            return
        if editor.reset_requested:
            self._layout_store.reset(page.standard)
            value = self._layout_store.load(page.standard, page.form.fields)
            page.note.setText("로컬 사용자 배치를 삭제하고 기본 배치로 복원했습니다.")
        else:
            value = self._layout_store.save(
                page.standard, page.form.fields, editor.value()
            )
            page.note.setText("이 PC의 레이어별 폼 배치를 저장했습니다.")
        page.form.set_form_layout(value)

    def _object_selected(self, layer_id, feature_id):
        if self._closed or getattr(self.plugin, "_opening", False):
            return
        layer = self.adapter.layers_by_id().get(layer_id)
        if layer is not None and feature_id is not None:
            self.on_feature_selected(layer, layer.getFeature(feature_id))
        elif layer is not None:
            # A multi-selection is a calculation context, not a request to discard the form.
            if layer.selectedFeatureCount() > 1:
                return
            self._clear_selected_feature(layer_id)

    def _clear_selected_feature(self, layer_id):
        page = self.pages.get(layer_id)
        if page is None:
            return
        if page.binding.saving:
            return
        layer = self.adapter.layers_by_id().get(layer_id)
        if layer is not None and bool(layer.customProperty(
            "geoflow/delete_commit_in_progress", False
        )):
            return
        if page.binding.is_feature_deleted():
            self._clear_deleted_page(page)
            return
        if not self._guard_object_transition(None, None):
            return
        if page.binding.clear():
            page.note.setText("객체를 선택하세요")
        else:
            page.note.setText("객체를 선택하세요 · 미저장 입력은 보존되어 있습니다.")
        self.save_button.setEnabled(False)
        page.photos.clear()
        page.form_actions.saveButton.setEnabled(False)

    def complete_committed_delete(self, layer_id, deleted_ids):
        """Clear stale UI references only after the provider DELETE succeeds."""
        page = self.pages.get(str(layer_id))
        if page is None or not page.binding.clear_after_committed_delete(deleted_ids):
            return False
        page.photos.clear()
        page.dirty = False
        page.note.setText("객체가 서버에서 삭제되었습니다. 다른 객체를 선택하세요.")
        page.form_actions.saveButton.setEnabled(False)
        if self.formStack.currentWidget() is page:
            self.save_button.setEnabled(False)
        self._update_page_dirty(page)
        return True

    def clear_staged_delete_context(self, layer_id, deleted_ids):
        """Clear a deleted object's form while retaining its QGIS DELETE buffer."""
        page = self.pages.get(str(layer_id))
        if page is None or page.feature_id is None:
            return False
        if int(page.feature_id) not in {int(fid) for fid in (deleted_ids or ())}:
            return False
        self._clear_deleted_page(page)
        return True

    def _empty_map_clicked(self):
        layer = self.plugin.iface.activeLayer()
        if layer is None or self.adapter.layers_by_id().get(layer.id()) is not layer:
            return
        if layer.selectedFeatureIds():
            layer.removeSelection()
        self._clear_selected_feature(layer.id())

    def on_feature_selected(self, layer, feature):
        if self._closed or layer is None or feature is None or not feature.isValid():
            return
        if any(page.binding.saving for page in self.pages.values()):
            return
        self.refresh_connection()
        layer_id = layer.id()
        if self.adapter.layers_by_id().get(layer_id) is not layer:
            return
        self.adapter.select_layer(layer_id)
        if self.adapter.selected_layer_id() != layer_id:
            return
        self._display_layer(layer_id)
        page = self.pages.get(layer_id)
        if page is None:
            return
        if not self._guard_object_transition(page, feature.id()):
            return
        if hasattr(self.plugin, "presentation"):
            from .presentation import PanelMode
            self.plugin.presentation.set_mode(PanelMode.FULL)
        page.feature_id = feature.id()
        page.binding.load(feature)
        page.photos.set_feature(feature)
        self._sync_photo_tab(page)
        self._log_photo_runtime(page, stage="feature")
        page.note.setText(f"{page.standard} · 객체 {feature.id()} · 중앙 Dynamic Form")
        self.save_button.setEnabled(page.binding.can_save)
        page.form_actions.saveButton.setEnabled(page.binding.can_save)
        for other_id, other_layer in self.adapter.layers_by_id().items():
            if other_id != layer_id and other_layer.selectedFeatureIds():
                other_layer.removeSelection()
        if layer.selectedFeatureIds() != [feature.id()]:
            layer.selectByIds([feature.id()])

    def set_select_map_tool(self):
        self.refresh_connection()
        if self.plugin.mapCanvas.mapTool() is self.select_tool:
            self.plugin.mapCanvas.unsetMapTool(self.select_tool)
        elif self.adapter.selected_layer_id() in self.adapter.layers_by_id():
            self.plugin.mapCanvas.setMapTool(self.select_tool)
        self._sync_select_tool_state()

    def save_current(self):
        selected_layer_id = self.adapter.selected_layer_id()
        page = self.pages.get(selected_layer_id)
        layer = self.adapter.layers_by_id().get(selected_layer_id)
        pending_delete_ids = (
            layer.customProperty("geoflow/pending_delete_ids", [])
            if layer is not None else []
        )
        buffer = layer.editBuffer() if layer is not None else None
        native_deleted_ids = list(
            buffer.deletedFeatureIds() if buffer is not None else ()
        )
        deleted_ids = list(pending_delete_ids or native_deleted_ids)
        if layer is not None and deleted_ids and layer.isModified():
            result = self.plugin.commit_layer_online(layer, stop_editing=False)
            if not result.get("ok"):
                return False
            self.complete_committed_delete(layer.id(), deleted_ids)
            layer.removeSelection()
            workspace = getattr(self.plugin, "_workspace_model", None)
            if workspace is not None:
                workspace.refresh()
            return True
        if page is not None and page.binding.is_feature_deleted():
            deleted_ids = list(buffer.deletedFeatureIds()) if buffer is not None else []
            result = self.plugin.commit_layer_online(layer, stop_editing=False)
            if not result.get("ok"):
                return False
            self.complete_committed_delete(page.layer_id, deleted_ids)
            layer.removeSelection()
            workspace = getattr(self.plugin, "_workspace_model", None)
            if workspace is not None:
                workspace.refresh()
            return True
        if page is not None:
            return self._save_page(page)
        if layer is None or not layer.isModified():
            return False
        result = self.plugin.commit_layer_online(layer, stop_editing=False)
        if not result.get("ok"):
            return False
        layer.removeSelection()
        workspace = getattr(self.plugin, "_workspace_model", None)
        if workspace is not None:
            workspace.refresh()
        return True

    def get_manh_layer(self):
        return self.adapter.layers().get("WTL_MANH_PS")

    def shutdown(self):
        if self._closed:
            return
        self._closed = True
        # 종료 확인 단계에서 JSON 저장이 끝났으므로 새 보존 창을 만들지 않는다.
        self._shutting_down = True
        self._form_settings.close()
        self._stop_selection_tool()
        for layer_id in list(self.pages):
            self._freeze_page(layer_id)
        self.adapter.changed.disconnect(self.refresh_connection)
        self.adapter.selectionChanged.disconnect(self._selection_changed)
        self.adapter.objectSelected.disconnect(self._object_selected)
        if self._photo_policy_service is not None:
            try:
                self._photo_policy_service.changed.disconnect(self._photo_policy_changed)
            except (RuntimeError, TypeError):
                pass
        self.adapter.close()
        try:
            self.plugin.mapCanvas.mapToolSet.disconnect(self._sync_select_tool_state)
        except (RuntimeError, TypeError):
            pass
        self.select_tool.geomIdentified.disconnect(self.on_feature_selected)
        self.select_tool.noFeatureIdentified.disconnect(self._empty_map_clicked)
        self.plugin.iface.currentLayerChanged.disconnect(self.select_tool.cancel_drag)
        QgsProject.instance().cleared.disconnect(self.select_tool.cancel_drag)
        self.select_tool.dispose()
        self.select_tool.deleteLater()
        if self._retained_window is not None:
            self._retained_window.close()
            self._retained_window.deleteLater()
            self._retained_window = None
