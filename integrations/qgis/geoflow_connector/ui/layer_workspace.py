# 제목: ui/layer_workspace.py
# 기능: 레이어 트리, 검색, 가시성 버튼 및 manifest 기반 편집 설정
from __future__ import annotations

from qgis.PyQt.QtCore import Qt, QSignalBlocker
try:
    from qgis.PyQt.QtGui import QAction
except ImportError:
    from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QToolButton,
    QWidget,
)
from pathlib import Path
from qgis.PyQt.uic import loadUi
from qgis.PyQt.QtGui import QColor, QIcon, QPainter
from qgis.core import (
    QgsEditFormConfig,
    QgsEditorWidgetSetup,
    QgsFieldConstraints,
    QgsProject,
    Qgis,
)

from ..layers.model import domain_label, editor_widget_spec, form_field_label, grouped_layer_rows, layer_reference_bindings, reference_groups, setting_enabled
from .layer_name_delegate import LayerNameDelegate, COUNT_ROLE
from ..api.references import ReferenceService, field_options
from ..api.definitions import DefinitionService
from ..api.photos import PhotoPolicyService


def _qt_value(enum_name: str, member_name: str, legacy_name: str):
    enum = getattr(Qt, enum_name, None)
    if enum is not None and hasattr(enum, member_name):
        return getattr(enum, member_name)
    return getattr(Qt, legacy_name)


_USER_ROLE = _qt_value("ItemDataRole", "UserRole", "UserRole")
_CHECKED = _qt_value("CheckState", "Checked", "Checked")
_UNCHECKED = _qt_value("CheckState", "Unchecked", "Unchecked")
_RIGHT_DOCK = _qt_value("DockWidgetArea", "RightDockWidgetArea", "RightDockWidgetArea")


class VisibilityButton(QToolButton):
    """Paint only the Designer icon; native button frames and press offsets are omitted."""

    def paintEvent(self, event):
        painter = QPainter(self)
        if self.property('emptyLayer'):
            opacity = self.property('emptyOpacity')
            painter.setOpacity(float(opacity) if opacity is not None else 0.4)
        size = self.iconSize()
        rect = self.rect()
        rect.setSize(size)
        rect.moveCenter(self.rect().center())
        state = QIcon.State.On if self.isChecked() else QIcon.State.Off
        self.icon().paint(painter, rect, Qt.AlignmentFlag.AlignCenter, QIcon.Mode.Normal, state)
        painter.end()


class VisibilityTree(QTreeWidget):
    def mousePressEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        item = self.itemAt(pos)
        if item is not None and item.parent() is not None and self.indexAt(pos).column() == 0:
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        if self.indexAt(pos).column() == 0:
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


# ============================================================
# 레이어 검색·선택·가시성 Workspace
# ============================================================
class GeoFlowLayerWorkspace(QWidget):
    """Metadata-driven layer workspace with one reusable native form."""

    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        self.model = plugin._workspace_model
        self.rows: list[dict] = []
        self.integrated = False
        self._items = {}
        self._building = False

        loadUi(str(Path(__file__).resolve().parents[1] / 'ui' / 'designer' / 'layer_workspace.ui'), self)
        self.tree.setItemDelegateForColumn(1, LayerNameDelegate(self.tree))
        self.model.rowsChanged.connect(self._rebuild)
        self.model.selectionChanged.connect(self._model_selection_changed)
        self.model.revealRequested.connect(self._reveal)
        self.model.visibilityChanged.connect(self._sync_checks)


        self.search.textChanged.connect(self._rebuild)
        self.form_edge.clicked.connect(self._toggle_form)
        self.tree.currentItemChanged.connect(self._selection_requested)
        self.tree.itemChanged.connect(self._visibility_changed)
        self.tree.itemDoubleClicked.connect(lambda *_args: self._activate())

    def set_project(self, manifest: dict) -> None:
        self.model.refresh()

    def set_integrated(self, enabled):
        self.integrated = enabled
        self.form_edge.setVisible(enabled)

    def _toggle_form(self):
        from .presentation import PanelMode
        presentation = self.plugin.presentation
        presentation.set_mode(PanelMode.LAYERS if presentation.mode == PanelMode.FULL else PanelMode.FULL)

    def _layer_for_item(self, item=None):
        if item is None:
            item = self.tree.currentItem()
        if item is None or item.parent() is None:
            return None
        return self.model.layers().get(str(item.data(0, _USER_ROLE) or ''))

    def _rebuild(self, *args) -> None:
        self._building = True
        blocker = QSignalBlocker(self.tree)
        expanded = {self.tree.topLevelItem(i).text(1): self.tree.topLevelItem(i).isExpanded() for i in range(self.tree.topLevelItemCount())}
        self.tree.clear()
        self._items = {}
        self._eyes = {}
        self.rows = self.model.rows
        managed = self.model.layers()
        for domain, rows in grouped_layer_rows(self.rows, self.search.text()).items():
            parent = QTreeWidgetItem(['', domain_label(domain)])
            self.tree.addTopLevelItem(parent)
            for row in rows:
                layer = managed.get(row['layer_id'])
                if layer is None:
                    continue
                item = QTreeWidgetItem(['', str(row['label'])])
                item.setData(1, COUNT_ROLE, str(row['row_count']))
                if row['row_count'] == 0:
                    item.setForeground(1, QColor(self.tree.property('emptyLayerColor')))
                item.setToolTip(1, f"{row['label']} ({row['row_count']})")
                item.setData(1, Qt.ItemDataRole.AccessibleTextRole, f"{row['label']} ({row['row_count']})")
                item.setToolTip(0, str(row['standard_name']))
                item.setData(0, _USER_ROLE, layer.id())
                node = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
                parent.addChild(item)
                eye = loadUi(str(Path(__file__).resolve().parent / 'designer' / 'layer_visibility.ui'))
                eye.setProperty('emptyLayer', row['row_count'] == 0)
                eye.clicked.connect(lambda checked=False, lid=layer.id(): self._toggle_eye(lid))
                self.tree.setItemWidget(item, 0, eye)
                self._eyes[layer.id()] = eye
                self._update_eye(layer.id())
                self._items[layer.id()] = item
            parent.setExpanded(expanded.get(domain_label(domain), True))
        item = self._items.get(self.model.selected_id)
        self.tree.setCurrentItem(item)
        self.tree.setColumnWidth(0, int(self.tree.property('visibilityColumnWidth') or 56))
        self.tree.resizeColumnToContents(1)
        del blocker
        self._building = False
    def _selection_requested(self, current, previous):
        if self._building:
            return
        layer = self._layer_for_item(current)
        if layer is not None:
            self.model.select_layer(layer.id())

    def _model_selection_changed(self, lid):
        blocker = QSignalBlocker(self.tree)
        self.tree.setCurrentItem(self._items.get(lid))
        del blocker

    def _reveal(self, lid):
        if lid not in self._items and self.search.text():
            self.search.clear()  # Explicit external selection reveals the actual current layer.
        item = self._items.get(lid)
        if item is not None:
            self._model_selection_changed(lid)
            self.tree.scrollToItem(item)

    def shutdown(self):
        for signal, slot in ((self.model.rowsChanged, self._rebuild),
                             (self.model.selectionChanged, self._model_selection_changed),
                             (self.model.revealRequested, self._reveal),
                             (self.model.visibilityChanged, self._sync_checks)):
            signal.disconnect(slot)

    def _update_eye(self, lid):
        node = QgsProject.instance().layerTreeRoot().findLayer(lid)
        visible = bool(node and node.isVisible())
        eye = self._eyes[lid]
        eye.setChecked(visible)
        eye.setToolTip('레이어 숨기기' if visible else '레이어 표시')
        eye.setAccessibleName(eye.toolTip())

    def _toggle_eye(self, lid):
        node = QgsProject.instance().layerTreeRoot().findLayer(lid)
        if node is not None:
            node.setItemVisibilityChecked(not node.isVisible())
            if node.itemVisibilityChecked():
                node.setItemVisibilityCheckedParentRecursive(True)
        self._sync_checks()

    def _sync_checks(self):
        for lid in getattr(self, '_eyes', {}):
            self._update_eye(lid)


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
            self.model.select_layer(layer.id())


# ============================================================
# Workspace 생명주기와 중앙 메타데이터 연결
# ============================================================
class LayerWorkspaceMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._layer_workspace = None
        self._workspace_panel = None
        self._workspace_model = None
        self._workspace_host = None
        self._layer_workspace_action = None
        self._reference_catalog = {"bindings": [], "groups": []}
        self._reference_service = ReferenceService()
        self._reference_service.changed.connect(self._reference_changed)
        self._definition_service = DefinitionService()
        self._definition_service.changed.connect(self._definition_changed)
        self._photo_policy_service = PhotoPolicyService()
        self._photo_policy_service.changed.connect(self._definition_changed)

    def initGui(self):
        super().initGui()
        from ..layers.selection import LayerWorkspaceState
        self._workspace_model = LayerWorkspaceState(self)
        self._layer_workspace_action = QAction(
            "GeoFlow 레이어 패널",
            self.iface.mainWindow(),
        )
        self._layer_workspace_action.setEnabled(False)
        self._layer_workspace_action.triggered.connect(self._show_layer_workspace)
        self.iface.addPluginToMenu("GeoFlow", self._layer_workspace_action)

    def unload(self):
        self._reference_service.clear()
        self._definition_service.clear()
        self._photo_policy_service.clear()
        if self._layer_workspace is not None:
            if self._workspace_panel is not None:
                self._workspace_panel.shutdown()
                self._workspace_panel.setParent(self._layer_workspace)
                self._workspace_panel.deleteLater()
                self._workspace_panel = None
            self.iface.removeDockWidget(self._layer_workspace)
            self._layer_workspace.deleteLater()
            self._layer_workspace = None
        if self._layer_workspace_action is not None:
            self.iface.removePluginMenu("GeoFlow", self._layer_workspace_action)
            self._layer_workspace_action.deleteLater()
            self._layer_workspace_action = None
        if self._workspace_model is not None:
            self._workspace_model.close()
            self._workspace_model.deleteLater()
            self._workspace_model = None
        self._workspace_host = None
        super().unload()

    def _ensure_layer_workspace(self):
        if self._layer_workspace is None:
            self._layer_workspace = QDockWidget('GeoFlow 레이어', self.iface.mainWindow())
            self._workspace_panel = GeoFlowLayerWorkspace(self, self._layer_workspace)
            self._layer_workspace.setWidget(self._workspace_panel)
            self.iface.addDockWidget(_RIGHT_DOCK, self._layer_workspace)
        return self._workspace_panel

    def _show_layer_workspace(self):
        if self._workspace_host is not None:
            self._workspace_host.window().show()
            self._workspace_host.window().raise_()
            return
        if self._layer_workspace is not None:
            self._layer_workspace.show()
            self._layer_workspace.raise_()

    def _load_reference_catalog(self, manifest: dict, client) -> None:
        self._reference_service.open(manifest, client)
        self._definition_service.open(manifest, client)
        self._photo_policy_service.open(manifest, client)

    def _definition_changed(self):
        # Form pages rebuild only through the existing project-scoped adapter.
        callback = getattr(self, "_integration_changed", None)
        if callback is not None:
            callback()

    def _reference_changed(self):
        service = self._reference_service
        self._reference_catalog = service.catalog if service.state == 'ready' else {'bindings': [], 'groups': []}
        context = getattr(self, 'active_context', None) or {}
        project_id = str(((context.get('manifest') or {}).get('project') or {}).get('id') or '')
        if service.state != 'ready' or not service.scope or service.scope[2] != project_id:
            return
        if "current_user" in service.catalog:
            context["user"] = dict(service.catalog["current_user"])
        # Catalog arrival is asynchronous. Update native editor choices too,
        # without reapplying permissions, defaults or replacing business forms.
        for layer in self._managed_layers():
            definition = self._layer_def(layer) or {}
            standard = definition.get('standard_name', '')
            for field in definition.get('fields') or []:
                name = field['name']
                index = self._field_index(layer, name)
                if index < 0:
                    continue
                widget, config = editor_widget_spec(field, field_options(self._reference_catalog, standard, field))
                if widget:
                    layer.setEditorWidgetSetup(index, QgsEditorWidgetSetup(widget, config))

    def refresh_reference_catalog(self):
        """One explicit refresh for all open forms, preserving their edit buffers."""
        self._reference_service.refresh()
        self._definition_service.refresh()
        self._photo_policy_service.refresh()

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
            values = field_options(self._reference_catalog, standard_name, field)
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
        panel = self._ensure_layer_workspace()
        panel.set_project(manifest)
        if self._workspace_host is None and self._layer_workspace is not None:
            self._layer_workspace.show()
        if self._layer_workspace_action is not None:
            self._layer_workspace_action.setEnabled(True)
        return result
