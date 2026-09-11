from __future__ import annotations

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QAction,
    QAbstractItemView,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qgis.core import (
    QgsEditFormConfig,
    QgsEditorWidgetSetup,
    QgsFieldConstraints,
    QgsProject,
    Qgis,
)

from .layer_workspace_model import (
    domain_label,
    editor_widget_spec,
    form_field_label,
    grouped_layer_rows,
    layer_reference_bindings,
    reference_groups,
    setting_enabled,
)


def _qt_value(enum_name: str, member_name: str, legacy_name: str):
    enum = getattr(Qt, enum_name, None)
    if enum is not None and hasattr(enum, member_name):
        return getattr(enum, member_name)
    return getattr(Qt, legacy_name)


_USER_ROLE = _qt_value("ItemDataRole", "UserRole", "UserRole")
_CHECKED = _qt_value("CheckState", "Checked", "Checked")
_UNCHECKED = _qt_value("CheckState", "Unchecked", "Unchecked")
_RIGHT_DOCK = _qt_value("DockWidgetArea", "RightDockWidgetArea", "RightDockWidgetArea")


class GeoFlowLayerWorkspace(QDockWidget):
    """Metadata-driven layer workspace with one reusable native form."""

    def __init__(self, plugin, parent=None):
        super().__init__("GeoFlow 레이어", parent)
        self.plugin = plugin
        self.rows: list[dict] = []
        self._building = False

        body = QWidget(self)
        layout = QVBoxLayout(body)
        self.summary = QLabel("GeoFlow 프로젝트를 열면 레이어가 표시됩니다.")
        self.summary.setWordWrap(True)
        self.search = QLineEdit()
        self.search.setPlaceholderText("레이어 이름·코드 검색")
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["레이어", "객체", "형상"])
        selection_mode = getattr(QAbstractItemView, "SelectionMode", None)
        self.tree.setSelectionMode(
            selection_mode.SingleSelection
            if selection_mode is not None
            else QAbstractItemView.SingleSelection
        )

        self.activate_button = QPushButton("활성화")
        self.add_button = QPushButton("객체 추가")
        self.edit_button = QPushButton("선택 속성 입력·수정")
        self.zoom_button = QPushButton("범위 이동")
        self.table_button = QPushButton("속성표")
        edit_buttons = QHBoxLayout()
        for button in (
            self.activate_button,
            self.add_button,
            self.edit_button,
        ):
            edit_buttons.addWidget(button)
        view_buttons = QHBoxLayout()
        for button in (
            self.zoom_button,
            self.table_button,
        ):
            view_buttons.addWidget(button)
        self.form_help = QLabel(
            "신규 객체는 도형 작성 후 속성 폼이 열립니다. 기존 객체는 지도에서 하나를 선택해 수정하세요."
        )
        self.form_help.setWordWrap(True)

        layout.addWidget(self.summary)
        layout.addWidget(self.search)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.form_help)
        layout.addLayout(edit_buttons)
        layout.addLayout(view_buttons)
        self.setWidget(body)

        self.search.textChanged.connect(self._rebuild)
        self.tree.currentItemChanged.connect(self._update_actions)
        self.tree.itemChanged.connect(self._visibility_changed)
        self.tree.itemDoubleClicked.connect(lambda *_args: self._activate())
        self.activate_button.clicked.connect(self._activate)
        self.add_button.clicked.connect(self._add_feature)
        self.edit_button.clicked.connect(self._edit_selected_feature)
        self.zoom_button.clicked.connect(self._zoom)
        self.table_button.clicked.connect(self._show_table)
        self._update_actions()

    def set_project(self, manifest: dict) -> None:
        project = manifest.get("project") or {}
        transport = manifest.get("transport") or {}
        self.rows = list(manifest.get("layers") or [])
        sync = (
            "저장 즉시 동기화"
            if transport.get("auto_sync_on_qgis_save")
            else "읽기 전용"
        )
        self.summary.setText(
            f"{project.get('code') or project.get('name') or 'GeoFlow'} · "
            f"레이어 {len(self.rows)}개 · {sync}"
        )
        self._rebuild()

    def _layer_for_item(self, item=None):
        item = item or self.tree.currentItem()
        if item is None or item.parent() is None:
            return None
        layer_id = str(item.data(0, _USER_ROLE) or "")
        return QgsProject.instance().mapLayer(layer_id) if layer_id else None

    def _rebuild(self) -> None:
        self._building = True
        self.tree.clear()
        managed = {
            str(layer.customProperty("geoflow/standard_name") or ""): layer
            for layer in self.plugin._managed_layers()
        }
        for domain, rows in grouped_layer_rows(self.rows, self.search.text()).items():
            parent = QTreeWidgetItem([domain_label(domain), str(len(rows)), ""])
            self.tree.addTopLevelItem(parent)
            for row in rows:
                standard_name = str(row.get("standard_name") or "")
                layer = managed.get(standard_name)
                count = (
                    layer.featureCount()
                    if layer is not None
                    else row.get("row_count", 0)
                )
                item = QTreeWidgetItem(
                    [
                        str(row.get("label") or standard_name),
                        str(count if count is not None else "-"),
                        str(row.get("geometry_kind") or ""),
                    ]
                )
                item.setToolTip(0, f"{standard_name} · {row.get('physical_name') or ''}")
                if layer is not None:
                    item.setData(0, _USER_ROLE, layer.id())
                    node = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
                    visible = bool(node and node.isVisible())
                    item.setCheckState(0, _CHECKED if visible else _UNCHECKED)
                parent.addChild(item)
            parent.setExpanded(True)
        self.tree.resizeColumnToContents(0)
        self._building = False
        self._update_actions()

    def _update_actions(self, *_args) -> None:
        layer = self._layer_for_item()
        ready = layer is not None
        self.activate_button.setEnabled(ready)
        self.zoom_button.setEnabled(
            ready and layer.featureCount() > 0 if ready else False
        )
        self.table_button.setEnabled(ready)
        self.add_button.setEnabled(
            ready
            and setting_enabled(layer.customProperty("geoflow/local_editing"))
        )
        self.edit_button.setEnabled(
            ready
            and layer.featureCount() > 0
            and setting_enabled(layer.customProperty("geoflow/local_editing"))
        )

    def _visibility_changed(self, item, _column) -> None:
        if self._building:
            return
        layer = self._layer_for_item(item)
        if layer is None:
            return
        node = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
        if node is not None:
            node.setItemVisibilityChecked(item.checkState(0) == _CHECKED)

    def _activate(self) -> None:
        layer = self._layer_for_item()
        if layer is not None:
            self.plugin.iface.setActiveLayer(layer)

    def _add_feature(self) -> None:
        layer = self._layer_for_item()
        if layer is None or not setting_enabled(
            layer.customProperty("geoflow/local_editing")
        ):
            return
        self.plugin.iface.setActiveLayer(layer)
        if not layer.isEditable() and not layer.startEditing():
            self.plugin.iface.messageBar().pushMessage(
                "GeoFlow",
                "레이어 편집을 시작하지 못했습니다.",
                level=Qgis.Warning,
                duration=5,
            )
            return
        action = getattr(self.plugin.iface, "actionAddFeature", lambda: None)()
        if action is not None:
            action.trigger()

    def _edit_selected_feature(self) -> None:
        layer = self._layer_for_item()
        if layer is None or not setting_enabled(
            layer.customProperty("geoflow/local_editing")
        ):
            return
        selected = list(layer.selectedFeatures())
        if len(selected) != 1:
            self.plugin.iface.messageBar().pushMessage(
                "GeoFlow",
                "지도에서 수정할 객체 하나를 선택하세요.",
                level=Qgis.Info,
                duration=5,
            )
            return
        self.plugin.iface.setActiveLayer(layer)
        if not layer.isEditable() and not layer.startEditing():
            self.plugin.iface.messageBar().pushMessage(
                "GeoFlow",
                "레이어 편집을 시작하지 못했습니다.",
                level=Qgis.Warning,
                duration=5,
            )
            return
        opener = getattr(self.plugin.iface, "openFeatureForm", None)
        if callable(opener):
            opener(layer, selected[0], False)
        else:
            self.plugin.iface.showAttributeTable(layer)

    def _zoom(self) -> None:
        layer = self._layer_for_item()
        if layer is not None and layer.featureCount() > 0:
            self.plugin.iface.mapCanvas().setExtent(layer.extent())
            self.plugin.iface.mapCanvas().refresh()

    def _show_table(self) -> None:
        layer = self._layer_for_item()
        if layer is not None:
            self.plugin.iface.showAttributeTable(layer)


class LayerWorkspaceMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._layer_workspace = None
        self._layer_workspace_action = None
        self._reference_catalog = {"bindings": [], "groups": []}

    def initGui(self):
        super().initGui()
        self._layer_workspace_action = QAction(
            "GeoFlow 레이어 패널",
            self.iface.mainWindow(),
        )
        self._layer_workspace_action.setEnabled(False)
        self._layer_workspace_action.triggered.connect(self._show_layer_workspace)
        self.iface.addPluginToMenu("GeoFlow", self._layer_workspace_action)

    def unload(self):
        if self._layer_workspace is not None:
            self.iface.removeDockWidget(self._layer_workspace)
            self._layer_workspace.deleteLater()
            self._layer_workspace = None
        if self._layer_workspace_action is not None:
            self.iface.removePluginMenu("GeoFlow", self._layer_workspace_action)
            self._layer_workspace_action.deleteLater()
            self._layer_workspace_action = None
        super().unload()

    def _show_layer_workspace(self):
        if self._layer_workspace is not None:
            self._layer_workspace.show()
            self._layer_workspace.raise_()

    def _load_reference_catalog(self, manifest: dict, client) -> None:
        url = str(
            (manifest.get("transport") or {}).get("reference_catalog_url") or ""
        )
        self._reference_catalog = {"bindings": [], "groups": []}
        if not url:
            return
        try:
            payload = client.get_json(url)
            if payload.get("ok"):
                self._reference_catalog = payload
        except Exception as exc:
            self.iface.messageBar().pushMessage(
                "GeoFlow 코드 카탈로그를 불러오지 못했습니다.",
                str(exc),
                level=Qgis.Warning,
                duration=6,
            )

    def _configure_layer_fields(
        self,
        layer,
        layer_def: dict,
        project_id: str,
        can_write: bool,
    ) -> None:
        super()._configure_layer_fields(layer, layer_def, project_id, can_write)
        standard_name = str(layer_def.get("standard_name") or "")
        groups = reference_groups(self._reference_catalog)
        bindings = {
            str(row.get("field_name") or ""): row
            for row in layer_reference_bindings(
                self._reference_catalog,
                standard_name,
            )
        }
        for field in layer_def.get("fields") or []:
            field_name = str(field.get("name") or "")
            idx = self._field_index(layer, field_name)
            label = form_field_label(field)
            if idx >= 0 and label and hasattr(layer, "setFieldAlias"):
                layer.setFieldAlias(idx, label)
            if idx < 0:
                continue
            binding = bindings.get(field_name) or {}
            binding_label = str(binding.get("field_label") or "")
            if binding_label and hasattr(layer, "setFieldAlias"):
                layer.setFieldAlias(
                    idx,
                    form_field_label({**field, "label": binding_label}),
                )
            values = groups.get(str(binding.get("code_group_key") or ""), [])
            widget_name, widget_config = editor_widget_spec(field, values)
            if widget_name and hasattr(layer, "setEditorWidgetSetup"):
                layer.setEditorWidgetSetup(
                    idx,
                    QgsEditorWidgetSetup(widget_name, widget_config),
                )
            if can_write and bool(field.get("required")):
                self._set_not_null_constraint(layer, idx)
        if can_write:
            self._force_attribute_form_on_add(layer)

    @staticmethod
    def _set_not_null_constraint(layer, field_index: int) -> None:
        constraint_enum = getattr(QgsFieldConstraints, "Constraint", None)
        constraint = (
            getattr(constraint_enum, "ConstraintNotNull", None)
            if constraint_enum is not None
            else None
        ) or getattr(QgsFieldConstraints, "ConstraintNotNull", None)
        strength_enum = getattr(QgsFieldConstraints, "ConstraintStrength", None)
        strength = (
            getattr(strength_enum, "ConstraintStrengthHard", None)
            if strength_enum is not None
            else None
        ) or getattr(QgsFieldConstraints, "ConstraintStrengthHard", None)
        if constraint is None or not hasattr(layer, "setFieldConstraint"):
            return
        try:
            if strength is None:
                layer.setFieldConstraint(field_index, constraint)
            else:
                layer.setFieldConstraint(field_index, constraint, strength)
        except Exception:
            pass

    @staticmethod
    def _force_attribute_form_on_add(layer) -> None:
        try:
            config = layer.editFormConfig()
            suppress_enum = getattr(Qgis, "FeatureFormSuppress", None)
            suppress_off = (
                getattr(suppress_enum, "SuppressOff", None)
                if suppress_enum is not None
                else None
            )
            if suppress_off is None:
                legacy_enum = getattr(QgsEditFormConfig, "Suppress", None)
                suppress_off = (
                    getattr(legacy_enum, "SuppressOff", None)
                    if legacy_enum is not None
                    else None
                ) or getattr(QgsEditFormConfig, "SuppressOff", None)
            if suppress_off is not None and hasattr(config, "setSuppress"):
                config.setSuppress(suppress_off)
                layer.setEditFormConfig(config)
        except Exception:
            pass

    def _materialize_project(self, manifest: dict, client, **kwargs) -> dict:
        self._load_reference_catalog(manifest, client)
        result = super()._materialize_project(manifest, client, **kwargs)
        if self._layer_workspace is None:
            self._layer_workspace = GeoFlowLayerWorkspace(self, self.iface.mainWindow())
            self.iface.addDockWidget(_RIGHT_DOCK, self._layer_workspace)
        self._layer_workspace.set_project(manifest)
        self._layer_workspace.show()
        if self._layer_workspace_action is not None:
            self._layer_workspace_action.setEnabled(True)
        return result
