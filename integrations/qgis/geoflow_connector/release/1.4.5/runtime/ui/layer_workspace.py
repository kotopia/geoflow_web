"""GeoFlow layer workspace backed by QGIS' native layer tree."""
from pathlib import Path

from qgis.PyQt.QtCore import QSize, Qt
from qgis.PyQt.QtGui import QIcon
try:
    from qgis.PyQt.QtGui import QAction
except ImportError:
    from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtWidgets import QDockWidget, QToolButton, QWidget
from qgis.PyQt.uic import loadUi
from qgis.core import (
    QgsEditFormConfig,
    QgsEditorWidgetSetup,
    QgsFieldConstraints,
    Qgis,
)

from ..api.definitions import DefinitionService
from ..api.photos import PhotoPolicyService
from ..api.references import ReferenceService, field_options
from ..layers.model import (
    editor_widget_spec,
    form_field_label,
    layer_reference_bindings,
)
from .main_style import apply_main_style


_RIGHT_DOCK = Qt.DockWidgetArea.RightDockWidgetArea


class GeoFlowLayerWorkspace(QWidget):
    """GeoFlow styling and form controls around a QgsLayerTreeView."""

    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        self.model = plugin._workspace_model
        self.integrated = False

        loadUi(
            str(Path(__file__).resolve().parent / "designer" / "layer_workspace.ui"),
            self,
        )
        # Designer cannot construct a plugin-parameterized tree, so replace its
        # neutral placeholder with the real QGIS view at the same layout slot.
        from .native_layer_tree import GeoFlowNativeLayerTree
        placeholder = self.tree
        self.tree = GeoFlowNativeLayerTree(plugin, self)
        self.tree.setObjectName("tree")
        self.workspace_layout.replaceWidget(placeholder, self.tree)
        placeholder.deleteLater()
        self._install_tree_toolbar()
        apply_main_style(self)

        self.model.rowsChanged.connect(self._refresh_tree)
        self.model.selectionChanged.connect(self._model_selection_changed)
        self.model.revealRequested.connect(self._reveal)
        self.model.visibilityChanged.connect(self.tree.refresh_presentation)
        self.model.symbologyChanged.connect(self.tree.refresh_symbology)
        self.search.textChanged.connect(self.tree.set_filter_text)
        self.form_edge.clicked.connect(self._toggle_form)

    def _tree_button(self, icon, tooltip, *, checkable=False):
        button = QToolButton(self)
        button.setAutoRaise(True)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setIcon(QIcon(str(
            Path(__file__).resolve().parents[1]
            / "resources" / "icons" / "feather" / icon
        )))
        button.setIconSize(QSize(18, 18))
        button.setFixedSize(28, 28)
        button.setToolTip(tooltip)
        button.setCheckable(checkable)
        return button

    def _install_tree_toolbar(self):
        self.expand_groups_button = self._tree_button(
            "folder-plus.svg", "그룹 펼치기 (레이어 legend는 유지)"
        )
        self.collapse_all_button = self._tree_button(
            "folder-minus.svg", "전체 접기"
        )
        self.count_toggle_button = self._tree_button(
            "hash.svg", "수량 표시/숨김", checkable=True
        )
        self.count_toggle_button.setChecked(True)
        for offset, button in enumerate((
            self.expand_groups_button,
            self.collapse_all_button,
            self.count_toggle_button,
        ), start=1):
            self.searchLayout.insertWidget(offset, button)
        self.expand_groups_button.clicked.connect(self.tree.expand_groups_only)
        self.collapse_all_button.clicked.connect(self.tree.collapse_all_rows)
        self.count_toggle_button.toggled.connect(self.tree.set_count_visible)

    def set_project(self, manifest: dict) -> None:
        del manifest
        self.tree.install_project_model()
        self.model.refresh()

    def set_integrated(self, enabled):
        self.integrated = bool(enabled)
        self.form_edge.setVisible(self.integrated)

    def _toggle_form(self):
        from .presentation import PanelMode
        presentation = self.plugin.presentation
        presentation.set_mode(
            PanelMode.LAYERS
            if presentation.mode == PanelMode.FULL
            else PanelMode.FULL
        )

    def _refresh_tree(self, *args):
        self.tree.install_project_model()
        self.tree.set_counts(self.model.rows)
        self.tree.set_filter_text(self.search.text())

    def _model_selection_changed(self, layer_id):
        self.tree.set_current_layer_id(layer_id)

    def _reveal(self, layer_id):
        layer = self.model.layers().get(layer_id)
        if layer is None:
            return
        if self.search.text() and not self.tree._managed_match(layer):
            self.search.clear()
        self.tree.set_current_layer_id(layer_id)
        if self.tree.currentIndex().isValid():
            self.tree.scrollTo(self.tree.currentIndex())

    def shutdown(self):
        for signal, slot in (
            (self.model.rowsChanged, self._refresh_tree),
            (self.model.selectionChanged, self._model_selection_changed),
            (self.model.revealRequested, self._reveal),
            (self.model.visibilityChanged, self.tree.refresh_presentation),
            (self.model.symbologyChanged, self.tree.refresh_symbology),
        ):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self.tree.shutdown()


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
            "GeoFlow 레이어 패널", self.iface.mainWindow()
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
            self._layer_workspace = QDockWidget(
                "GeoFlow 레이어", self.iface.mainWindow()
            )
            self._workspace_panel = GeoFlowLayerWorkspace(
                self, self._layer_workspace
            )
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
        callback = getattr(self, "_integration_changed", None)
        if callback is not None:
            callback()

    def _reference_changed(self):
        service = self._reference_service
        self._reference_catalog = (
            service.catalog
            if service.state == "ready"
            else {"bindings": [], "groups": []}
        )
        context = getattr(self, "active_context", None) or {}
        project_id = str(
            ((context.get("manifest") or {}).get("project") or {}).get("id")
            or ""
        )
        if (
            service.state != "ready"
            or not service.scope
            or service.scope[2] != project_id
        ):
            return
        if "current_user" in service.catalog:
            context["user"] = dict(service.catalog["current_user"])
        for layer in self._managed_layers():
            definition = self._layer_def(layer) or {}
            standard = definition.get("standard_name", "")
            for field in definition.get("fields") or []:
                index = self._field_index(layer, field["name"])
                if index < 0:
                    continue
                widget, config = editor_widget_spec(
                    field,
                    field_options(self._reference_catalog, standard, field),
                )
                if widget:
                    layer.setEditorWidgetSetup(
                        index, QgsEditorWidgetSetup(widget, config)
                    )

    def refresh_reference_catalog(self):
        self._reference_service.refresh()
        self._definition_service.refresh()
        self._photo_policy_service.refresh()

    def _configure_layer_fields(
        self, layer, layer_def: dict, project_id: str, can_write: bool
    ) -> None:
        super()._configure_layer_fields(layer, layer_def, project_id, can_write)
        standard_name = str(layer_def.get("standard_name") or "")
        bindings = {
            str(row.get("field_name") or ""): row
            for row in layer_reference_bindings(
                self._reference_catalog, standard_name
            )
        }
        for field in layer_def.get("fields") or []:
            field_name = str(field.get("name") or "")
            index = self._field_index(layer, field_name)
            label = form_field_label(field)
            if index >= 0 and label and hasattr(layer, "setFieldAlias"):
                layer.setFieldAlias(index, label)
            if index < 0:
                continue
            binding_label = str(
                (bindings.get(field_name) or {}).get("field_label") or ""
            )
            if binding_label and hasattr(layer, "setFieldAlias"):
                layer.setFieldAlias(
                    index,
                    form_field_label({**field, "label": binding_label}),
                )
            values = field_options(
                self._reference_catalog, standard_name, field
            )
            widget_name, widget_config = editor_widget_spec(field, values)
            if widget_name and hasattr(layer, "setEditorWidgetSetup"):
                layer.setEditorWidgetSetup(
                    index,
                    QgsEditorWidgetSetup(widget_name, widget_config),
                )
            if can_write and bool(field.get("required")):
                self._set_not_null_constraint(layer, index)
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
        strength_enum = getattr(
            QgsFieldConstraints, "ConstraintStrength", None
        )
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
        self.log("project_materialize_reference_catalog_start")
        self._load_reference_catalog(manifest, client)
        self.log("project_materialize_reference_catalog_done")
        result = super()._materialize_project(manifest, client, **kwargs)
        self.log("project_materialize_sync_bind_start")
        panel = self._ensure_layer_workspace()
        panel.set_project(manifest)
        if self._workspace_host is None and self._layer_workspace is not None:
            self._layer_workspace.show()
        if self._layer_workspace_action is not None:
            self._layer_workspace_action.setEnabled(True)
        self.log("project_materialize_sync_bind_done")
        return result
