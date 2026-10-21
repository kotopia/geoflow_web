"""GeoFlow presentation around QGIS' native layer-tree model and view."""
from __future__ import annotations

from pathlib import Path

from qgis.PyQt.QtCore import QModelIndex, QPoint, QRect, QSize, Qt
from qgis.PyQt.QtGui import QFont, QFontMetrics, QIcon, QPalette
from qgis.PyQt.QtWidgets import (
    QMenu,
    QMessageBox,
    QStyle,
    QStyleOptionViewItem,
    QStyledItemDelegate,
)
from qgis.core import QgsLayerTreeGroup, QgsLayerTreeLayer, QgsLayerTreeModel, QgsProject
from qgis.gui import QgsLayerTreeView


_ICON_ROOT = Path(__file__).resolve().parents[1] / "resources" / "icons" / "feather"


class GeoFlowLayerTreeModel(QgsLayerTreeModel):
    """Native QGIS tree model with GeoFlow's eye as the layer toggle UI."""

    def _direct_layer_node(self, index):
        node = self.index2node(index) if index.isValid() else None
        if (isinstance(node, QgsLayerTreeLayer)
                and self.node2index(node) == index):
            return node
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if (self._direct_layer_node(index) is not None
                and role == Qt.ItemDataRole.CheckStateRole):
            return None
        return super().data(index, role)

    def flags(self, index):
        value = super().flags(index)
        if self._direct_layer_node(index) is not None:
            value &= ~Qt.ItemFlag.ItemIsUserCheckable
        return value


class GeoFlowLayerTreeDelegate(QStyledItemDelegate):
    """Add the GeoFlow eye/count presentation without copying tree data."""

    EYE_WIDTH = 22

    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.eye_on = QIcon(str(_ICON_ROOT / "eye.svg"))
        self.eye_off = QIcon(str(_ICON_ROOT / "eye-off.svg"))

    @staticmethod
    def _small_font(font):
        result = QFont(font)
        if font.pointSizeF() > 0:
            result.setPointSizeF(max(1.0, font.pointSizeF() - 1.0))
        return result

    def _typed_option(self, option, index, node):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        if isinstance(node, QgsLayerTreeLayer):
            opt.font.setBold(True)
        elif isinstance(node, QgsLayerTreeGroup):
            opt.font.setWeight(QFont.Weight.DemiBold)
        else:
            opt.font = self._small_font(opt.font)
            opt.font.setBold(False)
        return opt

    def eye_rect(self, option):
        size = min(16, max(12, option.rect.height() - 6))
        return QRect(
            option.rect.left() + 2,
            option.rect.center().y() - size // 2,
            size,
            size,
        )

    def paint(self, painter, option, index):
        node = self.view.node_for_index(index)
        if not isinstance(node, QgsLayerTreeLayer):
            return super().paint(
                painter, self._typed_option(option, index, node), index
            )

        count = self.view.feature_count(node.layerId())
        count_text = f"  {count}" if self.view.count_visible else ""
        layer_option = self._typed_option(option, index, node)
        small = self._small_font(layer_option.font)
        count_width = (
            QFontMetrics(small).horizontalAdvance(count_text) + 7
            if count_text else 0
        )

        opt = layer_option
        check_feature = getattr(QStyleOptionViewItem.ViewItemFeature, "HasCheckIndicator", None)
        if check_feature is not None:
            opt.features &= ~check_feature
        opt.rect = opt.rect.adjusted(self.EYE_WIDTH, 0, -count_width, 0)
        super().paint(painter, opt, index)

        visible = bool(node.isVisible())
        icon = self.eye_on if visible else self.eye_off
        icon.paint(painter, self.eye_rect(option), Qt.AlignmentFlag.AlignCenter)

        if not count_text:
            return
        painter.save()
        painter.setFont(small)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        palette_role = (
            QPalette.ColorRole.HighlightedText
            if selected
            else QPalette.ColorRole.Text
        )
        color = option.palette.color(palette_role)
        if not selected:
            color.setAlpha(165)
        painter.setPen(color)
        metrics = QFontMetrics(small)
        baseline = option.rect.center().y() + (metrics.ascent() - metrics.descent()) // 2
        painter.drawText(option.rect.right() - count_width + 4, baseline, count_text)
        painter.restore()

    def sizeHint(self, option, index):
        node = self.view.node_for_index(index)
        typed = self._typed_option(option, index, node)
        result = super().sizeHint(typed, index)
        return QSize(result.width(), max(20, result.height()))


class GeoFlowNativeLayerTree(QgsLayerTreeView):
    """QGIS layer tree scoped to the active GeoFlow project group."""

    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        self.workspace_state = plugin._workspace_model
        self.native_model = None
        self._root = None
        self._counts = {}
        self._query = ""
        self.count_visible = True
        self._active_project_id = ""
        self._expansion_by_project = {}
        self._applying_expansion = False
        self.setHeaderHidden(True)
        self.setIndentation(12)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setItemDelegate(GeoFlowLayerTreeDelegate(self))
        self.customContextMenuRequested.connect(self._context_menu)
        self.currentLayerChanged.connect(self._layer_clicked)

    def _project_group(self):
        # QGIS 4.2 binds QgsLayerTreeModel specifically to QgsLayerTree (the
        # project root), not an arbitrary QgsLayerTreeGroup. Non-GeoFlow rows
        # are hidden at the view level below, while the source remains the
        # project's one authoritative tree.
        return QgsProject.instance().layerTreeRoot()

    def install_project_model(self):
        root = self._project_group()
        if root is self._root and self.native_model is not None:
            self.refresh_presentation()
            return
        previous = self.native_model
        self._root = root
        self.native_model = GeoFlowLayerTreeModel(root, self)
        flags = (
            QgsLayerTreeModel.Flag.ShowLegend
            | QgsLayerTreeModel.Flag.ShowLegendAsTree
            | QgsLayerTreeModel.Flag.AllowNodeChangeVisibility
            | QgsLayerTreeModel.Flag.AllowLegendChangeState
        )
        self.native_model.setFlags(flags)
        self.setLayerTreeModel(self.native_model)
        self.setModel(self.native_model)
        if previous is not None:
            previous.deleteLater()
        self.refresh_presentation()

    def _context_group(self, project_id):
        def visit(group):
            for child in group.children():
                if isinstance(child, QgsLayerTreeGroup):
                    if str(child.customProperty("geoflow/context_owner", "")) == project_id:
                        return child
                    match = visit(child)
                    if match is not None:
                        return match
            return None
        return visit(self._root) if self._root is not None and project_id else None

    def _set_scope_root(self, project_id):
        group = self._context_group(project_id)
        if group is None:
            self.setRootIndex(QModelIndex())
            return
        source = self.native_model.node2index(group)
        self.setRootIndex(self.layerTreeModelIndexToViewIndex(source))

    def _disable_native_counts(self):
        if self._root is None:
            return
        for layer in self._root.findLayers():
            layer.setCustomProperty("showFeatureCount", False)

    def node_for_index(self, view_index):
        if self.native_model is None or not view_index.isValid():
            return None
        source = self.viewIndexToLayerTreeModelIndex(view_index)
        node = self.native_model.index2node(source)
        if (isinstance(node, QgsLayerTreeLayer)
                and self.native_model.node2index(node) != source):
            return None
        return node

    @staticmethod
    def _node_key(node):
        if isinstance(node, QgsLayerTreeLayer):
            return "layer:" + str(node.layerId())
        if not isinstance(node, QgsLayerTreeGroup):
            return ""
        parts = []
        current = node
        while isinstance(current, QgsLayerTreeGroup) and current.parent() is not None:
            parts.append(str(current.name()))
            current = current.parent()
        return "group:" + "/".join(reversed(parts))

    def _walk_indexes(self, parent=None):
        parent = parent if parent is not None else self.rootIndex()
        model = self.model()
        for row in range(model.rowCount(parent)):
            index = model.index(row, 0, parent)
            yield index
            yield from self._walk_indexes(index)

    def _apply_project_expansion(self, project_id):
        state = self._expansion_by_project.get(project_id)
        target_state = self._expansion_by_project.setdefault(project_id, {})
        self._applying_expansion = True
        try:
            for index in self._walk_indexes():
                node = self.node_for_index(index)
                key = self._node_key(node)
                if not key:
                    continue
                expanded = state.get(key) if state is not None and key in state else None
                if expanded is None:
                    expanded = isinstance(node, QgsLayerTreeGroup)
                self.setExpanded(index, bool(expanded))
                target_state[key] = bool(expanded)
        finally:
            self._applying_expansion = False

    def _expansion_changed(self, index):
        if self._applying_expansion or not self._active_project_id:
            return
        key = self._node_key(self.node_for_index(index))
        if key:
            self._expansion_by_project.setdefault(
                self._active_project_id, {}
            )[key] = bool(self.isExpanded(index))

    def setExpanded(self, index, expanded):
        super().setExpanded(index, expanded)
        if not self._applying_expansion:
            self._expansion_changed(index)

    def feature_count(self, layer_id):
        return int(self._counts.get(str(layer_id), 0))

    def set_counts(self, rows):
        self._counts = {
            str(row.get("layer_id") or ""): int(row.get("row_count") or 0)
            for row in rows
        }
        self.refresh_presentation()

    def set_count_visible(self, visible):
        self.count_visible = bool(visible)
        self.viewport().update()

    def expand_groups_only(self):
        self._applying_expansion = True
        try:
            for index in self._walk_indexes():
                node = self.node_for_index(index)
                if isinstance(node, QgsLayerTreeGroup):
                    self.setExpanded(index, True)
                elif isinstance(node, QgsLayerTreeLayer):
                    self.setExpanded(index, False)
        finally:
            self._applying_expansion = False

    def collapse_all_rows(self):
        self.collapseAll()

    def set_filter_text(self, text):
        self._query = str(text or "").strip().casefold()
        self._apply_filter()

    def _managed_match(self, layer):
        if layer is None or not bool(layer.customProperty("geoflow/managed", False)):
            return False
        context = self.plugin.active_context or {}
        if str(layer.customProperty("geoflow/project_id", "")) != str(context.get("project_id") or ""):
            return False
        if not self._query:
            return True
        values = (
            layer.name(),
            layer.customProperty("geoflow/standard_name", ""),
            layer.customProperty("geoflow/physical_name", ""),
        )
        return self._query in " ".join(str(value) for value in values).casefold()

    def _filter_children(self, parent, owner_visible=None):
        model = self.model()
        any_visible = False
        for row in range(model.rowCount(parent)):
            index = model.index(row, 0, parent)
            node = self.node_for_index(index)
            if isinstance(node, QgsLayerTreeLayer):
                visible = self._managed_match(node.layer())
                self._filter_children(index, visible)
            elif isinstance(node, QgsLayerTreeGroup):
                visible = self._filter_children(index, None)
            else:
                # Legend rows belong to the nearest layer row.
                visible = bool(owner_visible)
                self._filter_children(index, visible)
            self.setRowHidden(row, parent, not visible)
            any_visible = any_visible or visible
        return any_visible

    def _apply_filter(self):
        if self.model() is not None:
            self._filter_children(self.rootIndex())

    def refresh_presentation(self):
        project_id = str((self.plugin.active_context or {}).get("project_id") or "")
        changed_project = project_id != self._active_project_id
        if changed_project:
            self._active_project_id = project_id
            self._set_scope_root(project_id)
        self._disable_native_counts()
        self._apply_filter()
        if changed_project:
            self._apply_project_expansion(project_id)
        self.viewport().update()

    def refresh_symbology(self, layer_id):
        if self.native_model is None:
            return
        node = self._root.findLayer(str(layer_id)) if self._root is not None else None
        if node is not None:
            before = self.layerTreeModelIndexToViewIndex(
                self.native_model.node2index(node)
            )
            was_expanded = bool(before.isValid() and self.isExpanded(before))
            self.native_model.refreshLayerLegend(node)
            self.refreshLayerSymbology(str(layer_id))
            after = self.layerTreeModelIndexToViewIndex(
                self.native_model.node2index(node)
            )
            if after.isValid():
                self._applying_expansion = True
                try:
                    self.setExpanded(after, was_expanded)
                finally:
                    self._applying_expansion = False
                self._expansion_by_project.setdefault(
                    self._active_project_id, {}
                )[self._node_key(node)] = was_expanded
        self.refresh_presentation()

    def set_current_layer_id(self, layer_id):
        layer = QgsProject.instance().mapLayer(str(layer_id))
        if layer is not None and self._managed_match(layer):
            self.setCurrentLayer(layer)

    def _layer_clicked(self, layer):
        index = self.currentIndex()
        if isinstance(self.node_for_index(index), QgsLayerTreeLayer) and layer is not None:
            self.workspace_state.select_layer(layer.id())

    def mousePressEvent(self, event):
        position = event.position().toPoint() if hasattr(event, "position") else event.pos()
        index = self.indexAt(position)
        node = self.node_for_index(index)
        if isinstance(node, QgsLayerTreeLayer):
            option = QStyleOptionViewItem()
            option.rect = self.visualRect(index)
            if self.itemDelegate().eye_rect(option).contains(position):
                checked = not node.isVisible()
                node.setItemVisibilityChecked(checked)
                if checked:
                    node.setItemVisibilityCheckedParentRecursive(True)
                self.viewport().update()
                self.plugin.iface.mapCanvas().refresh()
                event.accept()
                return
        super().mousePressEvent(event)
        if index.isValid():
            self._expansion_changed(index)

    def _context_menu(self, position: QPoint):
        index = self.indexAt(position)
        node = self.node_for_index(index)
        if not isinstance(node, QgsLayerTreeLayer) or not self._managed_match(node.layer()):
            return
        layer = node.layer()
        menu = QMenu(self)
        menu.addAction("레이어로 확대", lambda: self._zoom_layer(layer))
        menu.addAction("선택 객체로 확대", lambda: self._zoom_selected(layer))
        menu.addSeparator()
        menu.addAction("레이어 스타일 새로고침", lambda: self.refresh_symbology(layer.id()))
        menu.addAction("객체 수 새로고침", self.workspace_state.refresh)
        menu.addAction("속성 테이블 열기", lambda: self.plugin.iface.showAttributeTable(layer))
        menu.addSeparator()
        menu.addAction("레이어 정보", lambda: self._layer_info(layer))
        menu.exec(self.viewport().mapToGlobal(position))

    def _zoom_layer(self, layer):
        if layer.featureCount() > 0:
            self.plugin.iface.mapCanvas().setExtent(layer.extent())
            self.plugin.iface.mapCanvas().refresh()

    def _zoom_selected(self, layer):
        if layer.selectedFeatureCount() and hasattr(self.plugin.iface.mapCanvas(), "zoomToSelected"):
            self.plugin.iface.mapCanvas().zoomToSelected(layer)

    def _layer_info(self, layer):
        QMessageBox.information(
            self,
            "GeoFlow 레이어 정보",
            f"{layer.name()}\n"
            f"{layer.customProperty('geoflow/standard_name', '')}\n"
            f"객체 수: {self.feature_count(layer.id())}",
        )

    def shutdown(self):
        if self.native_model is not None:
            self.setModel(None)
            self.native_model.deleteLater()
            self.native_model = None
        self._root = None
