# GeoFlow QGIS 플러그인 - 중앙 Dynamic Form 호스트
# 레이어 선택·객체 바인딩·로컬 폼 배치 편집 화면을 하나의 업무 패널로 연결한다.
import json
import os

from qgis.PyQt.QtCore import QDate, Qt, QTimer
from qgis.PyQt.QtWidgets import (
    QDialog, QLabel, QPlainTextEdit, QPushButton, QScrollArea, QTabWidget,
    QToolBar, QVBoxLayout, QWidget,
)
from qgis.PyQt.uic import loadUiType

from .connector_adapter import ConnectorAdapter
from .form_header import FormHeader
from .photo_section import PhotoSection
from ..api.references import fields_with_worker_references, worker_reference_codes
from ..forms.dynamic.binding import DynamicFormBinding
from ..forms.dynamic.contract import layer_fields
from ..forms.dynamic.form import DynamicForm
from ..forms.dynamic.layout_editor import FormLayoutEditor, LocalFormLayoutStore
from ..layers.identify import IdentifyGeometry


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
        self.pages, self.archives = {}, []
        from ..forms.common.lifecycle import BusinessFormSettings
        self._form_settings = BusinessFormSettings()
        self._layout_store = LocalFormLayoutStore()
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
        self.select_button = QPushButton("객체 선택")
        self.add_button = QPushButton("추가")
        self.save_button = QPushButton("저장")
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
        self.select_tool = IdentifyGeometry(plugin.mapCanvas, layer_provider=self.adapter.layers_by_id)
        self.select_tool.geomIdentified.connect(self.on_feature_selected)
        self.select_tool.noFeatureIdentified.connect(self._empty_map_clicked)
        plugin.mapCanvas.mapToolSet.connect(self._sync_select_tool_state)
        self.adapter.changed.connect(self.refresh_connection)
        self.adapter.selectionChanged.connect(self._selection_changed)
        self.adapter.objectSelected.connect(self._object_selected)
        self._retained_window = None
        self.formStack.currentChanged.connect(self._sync_header)
        self.placeholderHeader.layoutButton.setEnabled(False)
        self.refresh_connection()
        self._sync_select_tool_state()

    @property
    def formHeader(self):
        return self.headerStack.currentWidget()

    def _sync_header(self, *args):
        page = self.formStack.currentWidget()
        self.headerStack.setCurrentWidget(getattr(page, "header", self.placeholderHeader))

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
        self.headerStack.removeWidget(page.header)
        page.layout().insertWidget(0, page.header)
        page.header.setEnabled(False)
        page.form.setEnabled(False)
        self.formStack.removeWidget(page)
        if page.dirty and not self._shutting_down:
            page.note.setText("이전 연결·객체의 입력을 보존했습니다. 편집·저장할 수 없습니다.\n" + page.note.text())
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
            photo_service = getattr(self.plugin, "_photo_policy_service", None)
            photo_signature = (getattr(photo_service, "state", ""),
                               getattr(photo_service, "revision", ""))
            signature = (state.get("instance"), state["epoch"], state["ready"],
                         state["project_id"], state["can_write"], revision, photo_signature)
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
            self.refresh_connection()
            self._display_layer(layer_id)

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

    def _create_form(self, layer, standard, fields):
        state, service = self.adapter.state(), self._definition_service()
        page = QWidget()
        page.project_name, page.standard = state["project_name"], standard
        page.readonly, page.feature_id, page.dirty = layer.readOnly(), None, False
        layout = QVBoxLayout(page)
        page.note = QLabel(f"{standard} · 객체를 선택하세요")
        page.note.setTextFormat(Qt.TextFormat.PlainText)
        page.note.setWordWrap(True)
        layout.addWidget(page.note)
        page.header = FormHeader(self.headerStack)
        manifest_layers = (self.plugin.active_context or {}).get("manifest", {}).get("layers", [])
        page.header.layerNameLabel.setText(next((row.get("label") for row in manifest_layers
            if str(row.get("standard_name", "")).upper() == standard), standard))
        page.header.layoutButton.clicked.connect(self.edit_form_layout)
        page.header.referenceRefreshButton.clicked.connect(self.plugin.refresh_reference_catalog)
        page.header.pushButtonUpdate.clicked.connect(self.save_current)
        user = getattr(self.plugin, "current_user_context", lambda: {})()
        page.header.lineEditWorker.setText(str(user.get("worker_name") or user.get("display_name") or ""))
        page.header.dateEdit.setDate(QDate.currentDate())
        self.headerStack.addWidget(page.header)
        local_layout = self._layout_store.load(standard, fields)
        page.form = DynamicForm(
            service.definition, fields, page, layer=standard, form_layout=local_layout
        )
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page.form)
        layout.addWidget(scroll)
        page.photos = PhotoSection(self.plugin, page, layer, page)
        page.form._root_layout.addWidget(page.photos)
        layout.setStretch(1, 1)
        page.form.setEnabled(bool(state["can_write"] and not layer.readOnly()))
        self.pages[layer.id()] = page
        self.formStack.addWidget(page)
        page.binding = DynamicFormBinding(page, layer, page.form, state["can_write"])

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
            self._clear_selected_feature(layer_id)

    def _clear_selected_feature(self, layer_id):
        page = self.pages.get(layer_id)
        if page is None:
            return
        if page.binding.clear():
            page.note.setText("객체를 선택하세요")
        else:
            page.note.setText("객체를 선택하세요 · 미저장 입력은 보존되어 있습니다.")
        self.save_button.setEnabled(False)
        page.photos.clear()
        page.header.pushButtonUpdate.setEnabled(False)

    def _empty_map_clicked(self):
        selected_layer_id = self.adapter.selected_layer_id()
        for layer in self.adapter.layers_by_id().values():
            if layer.selectedFeatureIds():
                layer.removeSelection()
        if selected_layer_id:
            self._clear_selected_feature(selected_layer_id)

    def on_feature_selected(self, layer, feature):
        if self._closed or layer is None or feature is None or not feature.isValid():
            return
        self.refresh_connection()
        layer_id = layer.id()
        if self.adapter.layers_by_id().get(layer_id) is not layer:
            return
        self.adapter.select_layer(layer_id)
        self._display_layer(layer_id)
        page = self.pages.get(layer_id)
        if page is None:
            return
        if hasattr(self.plugin, "presentation"):
            from .presentation import PanelMode
            self.plugin.presentation.set_mode(PanelMode.FULL)
        if page.binding.has_actual_changes() and page.feature_id != feature.id():
            page.note.setText(f"{page.standard} · 이전 객체 {page.feature_id}의 임시 입력 보존 (새 객체 연결 거부)")
            return
        page.feature_id = feature.id()
        page.binding.load(feature)
        page.photos.set_feature(feature)
        page.note.setText(f"{page.standard} · 객체 {feature.id()} · 중앙 Dynamic Form")
        self.save_button.setEnabled(page.binding.can_save)
        page.header.pushButtonUpdate.setEnabled(page.binding.can_save)
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
        page = self.pages.get(self.adapter.selected_layer_id())
        return page.binding.save() if page is not None else False

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
        self.adapter.close()
        try:
            self.plugin.mapCanvas.mapToolSet.disconnect(self._sync_select_tool_state)
        except (RuntimeError, TypeError):
            pass
        self.select_tool.geomIdentified.disconnect(self.on_feature_selected)
        self.select_tool.noFeatureIdentified.disconnect(self._empty_map_clicked)
        self.select_tool.deleteLater()
        if self._retained_window is not None:
            self._retained_window.close()
            self._retained_window.deleteLater()
            self._retained_window = None
