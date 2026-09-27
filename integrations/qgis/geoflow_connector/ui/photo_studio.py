"""Unified Photo Studio with persistent, re-editable annotation objects."""

import json
import math
import os

from qgis.PyQt.QtCore import QPointF, QRectF, Qt, QTimer
from qgis.PyQt.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap, QTransform
try:
    from qgis.PyQt.QtGui import QAction
except ImportError:  # QAction lives in QtWidgets on the QGIS 3 / Qt 5 stack.
    from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtWidgets import (
    QColorDialog, QFileDialog, QGraphicsPathItem, QGraphicsScene, QGraphicsView,
    QInputDialog, QMenu, QMessageBox, QToolButton, QDialog,
)
from qgis.PyQt.uic import loadUiType

from .photo_annotations import (
    MAX_ANNOTATIONS, IconAnnotationItem, PathAnnotationItem, TextAnnotationItem,
    annotation_document, create_annotation, is_editable_document,
)
from .photo_icons import ICON_NAMES, annotation_icon, feather_icon
from .photo_normalizer import encode_qimage, normalize_photo


FORM_CLASS, _ = loadUiType(os.path.join(os.path.dirname(__file__), "forms", "photo_studio.ui"))


class StudioView(QGraphicsView):
    def __init__(self, studio):
        super().__init__(studio)
        self.studio = studio

    def wheelEvent(self, event):
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        self.scale(factor, factor)

    def keyPressEvent(self, event):
        if self.studio.handle_key(event):
            return
        super().keyPressEvent(event)


class AnnotationScene(QGraphicsScene):
    """Scene drawing controller; completed objects become annotation items."""

    def __init__(self, studio):
        super().__init__(studio)
        self.studio = studio
        self.start = self.preview = None
        self.points = []

    def cancel_drawing(self):
        if self.preview is not None and self.preview.scene() is self:
            self.removeItem(self.preview)
        self.start = self.preview = None
        self.points = []
        self.studio.cancel_change()

    def _preview_path(self, cursor=None):
        if not self.points:
            return
        path = QPainterPath(self.points[0])
        for point in self.points[1:]:
            path.lineTo(point)
        if cursor is not None and cursor != self.points[-1]:
            path.lineTo(cursor)
        self.preview.setPath(path)

    def _shape_rect(self, end, modifiers):
        if not (modifiers & Qt.KeyboardModifier.ShiftModifier):
            return QRectF(self.start, end).normalized()
        dx, dy = end.x() - self.start.x(), end.y() - self.start.y()
        size = max(abs(dx), abs(dy))
        constrained = QPointF(
            self.start.x() + (size if dx >= 0 else -size),
            self.start.y() + (size if dy >= 0 else -size),
        )
        return QRectF(self.start, constrained).normalized()

    def finish_polyline(self):
        if self.studio.tool != "polyline" or len(self.points) < 2:
            self.cancel_drawing(); return
        points = [[p.x(), p.y()] for p in self.points]
        if self.preview is not None and self.preview.scene() is self:
            self.removeItem(self.preview)
        self.studio.add_annotation({"type": "polyline", "points": points})
        self.start = self.preview = None; self.points = []
        self.studio.commit_change()

    def mouseDoubleClickEvent(self, event):
        if self.studio.tool == "polyline":
            self.finish_polyline(); event.accept(); return
        item = self.itemAt(event.scenePos(), self.studio.graphicsView.transform())
        owner = item.parentItem() if item is not None and item.parentItem() is not None else item
        if self.studio.tool == "select" and isinstance(owner, PathAnnotationItem) \
                and owner.annotation_type == "polyline":
            self.studio.begin_change(); owner.add_vertex(event.scenePos()); self.studio.commit_change()
            event.accept(); return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        tool = self.studio.tool
        if event.button() != Qt.MouseButton.LeftButton or tool in {"pan", "select"}:
            return super().mousePressEvent(event)
        if not self.studio.ensure_editable():
            return
        point = event.scenePos()
        if tool == "polyline":
            if not self.points:
                self.studio.begin_change()
                self.preview = QGraphicsPathItem(); self.preview.setPen(self.studio.pen())
                self.addItem(self.preview)
            self.points.append(point); self._preview_path(point); event.accept(); return
        self.studio.begin_change(); self.start = point
        if tool == "text":
            value, ok = QInputDialog.getText(self.studio, "텍스트", "사진에 표시할 내용")
            if ok and value:
                self.studio.add_annotation({"type": "text", "text": value,
                    "x": point.x(), "y": point.y(), "font_size": self.studio.default_font_size})
                self.studio.commit_change()
            else:
                self.studio.cancel_change()
            self.start = None; event.accept(); return
        if tool.startswith("icon:"):
            self.studio.add_annotation({"type": "icon", "icon": tool.split(":", 1)[1],
                "x": point.x(), "y": point.y(), "size": self.studio.default_icon_size})
            self.studio.commit_change(); self.start = None; event.accept(); return
        self.preview = QGraphicsPathItem(); self.preview.setPen(self.studio.pen()); self.addItem(self.preview)
        self.points = [point]
        event.accept()

    def mouseMoveEvent(self, event):
        if self.studio.tool == "polyline" and self.preview is not None:
            self._preview_path(event.scenePos()); event.accept(); return
        if self.start is not None and self.preview is not None:
            point = event.scenePos()
            if self.studio.tool == "freehand":
                if len(self.points) < 2000 and (not self.points or
                        math.hypot(point.x()-self.points[-1].x(), point.y()-self.points[-1].y()) >= 3):
                    self.points.append(point)
            else:
                self.points = [self.start, point]
            path = QPainterPath(self.points[0])
            if self.studio.tool in {"rectangle", "ellipse"}:
                rect = self._shape_rect(point, event.modifiers())
                path.addRect(rect) if self.studio.tool == "rectangle" else path.addEllipse(rect)
            else:
                for sampled in self.points[1:]: path.lineTo(sampled)
            self.preview.setPath(path); event.accept(); return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        tool = self.studio.tool
        if tool in {"polyline", "pan", "select"} or self.start is None:
            return super().mouseReleaseEvent(event)
        end = event.scenePos()
        if self.preview is not None and self.preview.scene() is self:
            self.removeItem(self.preview)
        if tool == "line":
            data = {"type": "line", "start": [self.start.x(), self.start.y()], "end": [end.x(), end.y()]}
        elif tool in {"rectangle", "ellipse"}:
            rect = self._shape_rect(end, event.modifiers())
            data = {"type": tool, "x": rect.x(), "y": rect.y(), "width": rect.width(), "height": rect.height(),
                    "fill": "#00000000"}
        elif tool == "freehand":
            data = {"type": "freehand", "points": [[p.x(), p.y()] for p in self.points]}
        else:
            data = None
        if data and (tool not in {"line", "freehand"} or len(self.points) > 1 or self.start != end):
            self.studio.add_annotation(data); self.studio.commit_change()
        else:
            self.studio.cancel_change()
        self.start = self.preview = None; self.points = []
        event.accept()


class PhotoStudioDialog(QDialog, FORM_CLASS):
    COLORS = (("빨강", "#ef4444"), ("노랑", "#facc15"), ("파랑", "#2563eb"),
              ("초록", "#16a34a"), ("검정", "#111827"), ("흰색", "#ffffff"))

    def __init__(self, client, photos, selected, *, can_write=False,
                 save_callback=None, replace_callback=None, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.client, self.photos, self.can_write = client, photos, can_write
        self.save_callback, self.replace_callback = save_callback, replace_callback
        self.index = next((i for i, row in enumerate(photos)
                           if str(row.get("id")) == str(selected.get("id"))), 0)
        self.tool, self.undo_stack, self.redo_stack = "select", [], []
        self._change_before = None
        self._source_pixmap = QPixmap()
        self._legacy_edit, self._showing_original = False, False
        self._loaded_state = None
        self._allow_reject = False
        self.default_color, self.default_width = "#ef4444", 5
        self.default_font_size, self.default_icon_size = 28, 76
        self.scene = AnnotationScene(self)
        replacement = StudioView(self)
        self.studioSplitter.replaceWidget(0, replacement)
        self.graphicsView.deleteLater(); self.graphicsView = replacement
        self.graphicsView.setScene(self.scene)
        self.graphicsView.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._build_toolbar(); self._setup_properties()
        self._button(self.replaceButton, "refresh-cw", "사진 변경", self.replace_photo)
        self._button(self.saveButton, "check", "편집 적용", self.save_edit)
        self.saveButton.setText("편집 적용")
        self._button(self.cancelButton, "x", "닫기", self.reject)
        self.replaceButton.setEnabled(can_write); self.saveButton.setEnabled(can_write)
        self.originalButton.clicked.connect(lambda: self.set_representation("original"))
        self.editedButton.clicked.connect(lambda: self.set_representation("edited"))
        self.load_current("edited")

    def _button(self, button, icon, tooltip, slot):
        button.setIcon(feather_icon(icon)); button.setToolTip(tooltip)
        button.setAccessibleName(tooltip); button.clicked.connect(slot)

    def _action(self, icon, tooltip, slot, checkable=False):
        action = QAction(feather_icon(icon), "", self)
        action.setToolTip(tooltip); action.setStatusTip(tooltip); action.setCheckable(checkable)
        action.triggered.connect(slot); self.studioToolbar.addAction(action)
        return action

    def _build_toolbar(self):
        self._action("chevron-left", "이전 사진", self.previous)
        self._action("chevron-right", "다음 사진", self.next)
        self._action("zoom-in", "확대", lambda: self.graphicsView.scale(1.25, 1.25))
        self._action("zoom-out", "축소", lambda: self.graphicsView.scale(.8, .8))
        self._action("maximize", "화면 맞춤", self.fit_to_window)
        self._action("target", "100%", self.actual_size)
        self.studioToolbar.addSeparator()
        self._action("mouse-pointer", "선택", lambda: self.set_tool("select"))
        self._action("move", "화면 이동", lambda: self.set_tool("pan"))
        line_button = QToolButton(self); line_button.setIcon(feather_icon("minus"))
        line_button.setToolTip("선 도구"); line_button.setAccessibleName("선 도구")
        line_button.setPopupMode(QToolButton.ToolButtonPopupMode.DelayedPopup)
        menu = QMenu(line_button)
        for label, tool, icon in (("직선", "line", "minus"), ("폴리선", "polyline", "activity"),
                                  ("자유선", "freehand", "edit-2")):
            action = menu.addAction(feather_icon(icon), label)
            action.triggered.connect(lambda _=False, value=tool: self.set_tool(value))
        line_button.setMenu(menu); line_button.clicked.connect(lambda: self.set_tool("line"))
        self.studioToolbar.addWidget(line_button)
        self._action("square", "사각형", lambda: self.set_tool("rectangle"))
        self._action("circle", "원", lambda: self.set_tool("ellipse"))
        self._action("type", "텍스트", lambda: self.set_tool("text"))
        icon_button = QToolButton(self); icon_button.setIcon(feather_icon("grid"))
        icon_button.setToolTip("아이콘"); icon_button.setAccessibleName("아이콘")
        icon_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        icon_menu = QMenu(icon_button)
        for name, label in ICON_NAMES.items():
            action = icon_menu.addAction(annotation_icon(name), label)
            action.triggered.connect(lambda _=False, value=name: self.set_tool("icon:" + value))
        icon_button.setMenu(icon_menu); self.studioToolbar.addWidget(icon_button)
        self.studioToolbar.addSeparator()
        self._action("rotate-ccw", "선택 객체 왼쪽 90도", lambda: self.rotate_selected(-90))
        self._action("rotate-cw", "선택 객체 오른쪽 90도", lambda: self.rotate_selected(90))
        self._action("corner-up-left", "실행 취소", self.undo)
        self._action("corner-up-right", "다시 실행", self.redo)

    def _setup_properties(self):
        for label, color in self.COLORS: self.colorCombo.addItem(label, color)
        self.colorCombo.addItem("기타 색상…", "custom")
        self.colorCombo.currentIndexChanged.connect(self.change_color)
        self.strokeWidthSpin.valueChanged.connect(self.change_width)
        self.opacitySpin.valueChanged.connect(self.change_opacity)
        self.fontSizeSpin.valueChanged.connect(self.change_font_size)
        self.boldCheck.toggled.connect(self.change_bold)
        self.rotationSpin.valueChanged.connect(self.change_rotation)
        self.fillButton.clicked.connect(self.change_fill)
        self.frontButton.clicked.connect(lambda: self.change_z(1))
        self.backButton.clicked.connect(lambda: self.change_z(-1))
        self.deleteAnnotationButton.clicked.connect(self.delete_selected)
        self.propertyPanel.setVisible(False)

    def selected_annotation(self):
        for item in self.scene.selectedItems():
            owner = item.parentItem() if item.parentItem() is not None else item
            if hasattr(owner, "annotation_type"): return owner
        return None

    def annotation_selection_changed(self, item=None):
        selected = self.selected_annotation() or item
        visible = bool(selected and self.can_write and not self._showing_original)
        self.propertyPanel.setVisible(visible)
        self.propertyPanel.setEnabled(visible)
        if not selected: return
        widgets = (self.colorCombo, self.strokeWidthSpin, self.opacitySpin,
                   self.fontSizeSpin, self.rotationSpin, self.boldCheck)
        for widget in widgets: widget.blockSignals(True)
        index = next((i for i in range(self.colorCombo.count())
                      if self.colorCombo.itemData(i) == selected.stroke), 0)
        self.colorCombo.setCurrentIndex(index)
        self.strokeWidthSpin.setValue(selected.stroke_width)
        self.opacitySpin.setValue(selected.opacity())
        kind = selected.annotation_type
        is_text = isinstance(selected, TextAnnotationItem)
        is_icon = isinstance(selected, IconAnnotationItem)
        has_stroke = kind in {"line", "polyline", "freehand", "rectangle", "ellipse"}
        has_rotation = kind in {"rectangle", "ellipse", "text", "icon"}
        for widget in (self.strokeLabel, self.strokeWidthSpin): widget.setVisible(has_stroke)
        for widget in (self.fontLabel, self.fontSizeSpin): widget.setVisible(is_text or is_icon)
        for widget in (self.boldLabel, self.boldCheck): widget.setVisible(is_text)
        for widget in (self.rotationLabel, self.rotationSpin): widget.setVisible(has_rotation)
        self.fillButton.setVisible(kind in {"rectangle", "ellipse"})
        self.fontLabel.setText("아이콘 크기" if is_icon else "글자 크기")
        self.fontSizeSpin.setMaximum(400 if is_icon else 160)
        if isinstance(selected, TextAnnotationItem):
            self.fontSizeSpin.setValue(selected.font_size); self.boldCheck.setChecked(selected.bold)
        elif isinstance(selected, IconAnnotationItem):
            self.fontSizeSpin.setValue(selected.icon_size)
        self.rotationSpin.setValue(selected.rotation())
        for widget in widgets: widget.blockSignals(False)

    def _mutate_selected(self, callback):
        item = self.selected_annotation()
        if item:
            self.begin_change(); callback(item); item.update_handles(); self.commit_change()
        return item

    def change_color(self):
        value = self.colorCombo.currentData()
        if value == "custom":
            picked = QColorDialog.getColor(QColor(self.default_color), self, "색상 선택")
            if not picked.isValid(): return
            value = picked.name()
        if not value: return
        self.default_color = value
        self._mutate_selected(lambda item: item.set_annotation_color(value))

    def change_width(self, value):
        self.default_width = int(value)
        self._mutate_selected(lambda item: item.set_stroke_width(value))

    def change_opacity(self, value): self._mutate_selected(lambda item: item.setOpacity(float(value)))
    def change_rotation(self, value): self._mutate_selected(lambda item: item.setRotation(float(value)))

    def change_font_size(self, value):
        self.default_font_size = int(value)
        def apply(item):
            if isinstance(item, TextAnnotationItem):
                item.font_size = int(value); item.apply_text_style()
            elif isinstance(item, IconAnnotationItem):
                item.icon_size = max(20, min(400, int(value))); item.refresh_pixmap()
        self._mutate_selected(apply)

    def change_bold(self, checked):
        def apply(item):
            if isinstance(item, TextAnnotationItem): item.bold = bool(checked); item.apply_text_style()
        self._mutate_selected(apply)

    def change_fill(self):
        item = self.selected_annotation()
        initial = QColor(getattr(item, "fill", "#00000000")) if item else QColor(0, 0, 0, 0)
        color = QColorDialog.getColor(initial, self, "채우기 색상", QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if color.isValid(): self._mutate_selected(lambda selected: selected.set_fill_color(color.name(QColor.NameFormat.HexArgb)))

    def change_z(self, delta):
        self._mutate_selected(lambda item: item.setZValue(item.zValue() + delta))

    def pen(self):
        return QPen(QColor(self.default_color), self.default_width, Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)

    def set_tool(self, name):
        if name not in {"select", "pan"} and not self.ensure_editable(): return
        self.scene.cancel_drawing(); self.tool = name
        self.graphicsView.setDragMode(QGraphicsView.DragMode.ScrollHandDrag if name == "pan"
                                      else QGraphicsView.DragMode.NoDrag)

    def _photo_url(self, photo, representation):
        if representation == "original":
            return str(photo.get("original_download_url") or photo.get("download_url") or "")
        return str(photo.get("display_download_url") or photo.get("download_url") or "")

    def _download_pixmap(self, url):
        pixmap = QPixmap(); pixmap.loadFromData(self.client.get_bytes(url))
        if pixmap.isNull(): raise ValueError("사진을 읽을 수 없습니다.")
        return pixmap

    def _photo_pixmap(self, photo, representation):
        key = "_local_original_bytes" if representation == "original" else "_local_display_bytes"
        data = photo.get(key)
        if data:
            pixmap = QPixmap(); pixmap.loadFromData(data)
            if pixmap.isNull(): raise ValueError("로컬 사진을 읽을 수 없습니다.")
            return pixmap
        return self._download_pixmap(self._photo_url(photo, representation))

    def load_current(self, representation="edited"):
        if not self.photos: return
        photo = self.photos[self.index]
        edit_data = photo.get("edit_data") or {}
        if isinstance(edit_data, str):
            try: edit_data = json.loads(edit_data)
            except ValueError: edit_data = {}
        editable = is_editable_document(edit_data)
        self._legacy_edit = bool(photo.get("edited_object_key") and not editable)
        original = self._photo_pixmap(photo, "original")
        self.restore_canvas(original, edit_data if editable else None)
        if self._legacy_edit and representation == "edited":
            self.restore_canvas(self._photo_pixmap(photo, "edited"), None)
        self._showing_original = representation == "original"
        self.set_annotation_visibility(not self._showing_original)
        self.undo_stack.clear(); self.redo_stack.clear(); self._change_before = None
        suffix = " · 기존 raster 편집본(새 편집 시작 시 객체 편집 가능)" if self._legacy_edit else ""
        self.statusLabel.setText(f"{self.index+1} / {len(self.photos)} · {photo.get('original_name') or '사진'}{suffix}")
        self.originalButton.setChecked(self._showing_original); self.editedButton.setChecked(not self._showing_original)
        self.annotation_selection_changed(); QTimer.singleShot(0, self.fit_to_window)
        self._loaded_state = self.annotation_state()

    def set_representation(self, representation):
        photo = self.photos[self.index]
        if self._legacy_edit:
            pixmap = self._photo_pixmap(photo, representation)
            self.restore_canvas(pixmap, None)
        self._showing_original = representation == "original"
        self.set_annotation_visibility(not self._showing_original)
        self.originalButton.setChecked(self._showing_original)
        self.editedButton.setChecked(not self._showing_original)
        self.annotation_selection_changed()

    def ensure_editable(self):
        if not self.can_write: return False
        if self._legacy_edit:
            answer = QMessageBox.question(self, "새 편집 시작",
                "기존 편집본은 개별 객체 정보가 없어 직접 수정할 수 없습니다. 새 편집을 시작하시겠습니까?")
            if answer != QMessageBox.StandardButton.Yes: return False
            photo = self.photos[self.index]
            self.restore_canvas(self._photo_pixmap(photo, "original"), None)
            self._legacy_edit = False
        self._showing_original = False; self.set_annotation_visibility(True)
        self.originalButton.setChecked(False); self.editedButton.setChecked(True)
        return True

    def restore_canvas(self, pixmap, document=None):
        self.scene.clear(); self._source_pixmap = pixmap
        from qgis.PyQt.QtWidgets import QGraphicsPixmapItem
        self.base_item = QGraphicsPixmapItem(pixmap); self.base_item.setZValue(-10000)
        self.scene.addItem(self.base_item); self.scene.setSceneRect(self.base_item.boundingRect())
        if is_editable_document(document): self.restore_state(document)

    def annotations(self):
        return sorted((item for item in self.scene.items() if hasattr(item, "annotation_type")),
                      key=lambda item: item.zValue())

    def add_annotation(self, data):
        if len(self.annotations()) >= MAX_ANNOTATIONS:
            QMessageBox.warning(self, "사진 편집", "사진에는 최대 200개의 편집 객체를 추가할 수 있습니다.")
            return None
        data = dict(data); data.setdefault("stroke", self.default_color)
        data.setdefault("stroke_width", self.default_width)
        data.setdefault("z", max([item.zValue() for item in self.annotations()] or [0]) + 1)
        item = create_annotation(self, data); self.scene.addItem(item)
        self.scene.clearSelection(); item.setSelected(True); item.update_handles(); return item

    def annotation_state(self):
        bounds = self.base_item.boundingRect()
        return annotation_document(bounds.width(), bounds.height(),
                                   [item.to_json() for item in self.annotations()])

    def restore_state(self, document):
        for item in list(self.annotations()): self.scene.removeItem(item)
        for row in (document.get("annotations") or [])[:MAX_ANNOTATIONS]:
            try: self.scene.addItem(create_annotation(self, row))
            except (TypeError, ValueError, KeyError): continue
        self.scene.clearSelection(); self.annotation_selection_changed()

    def begin_change(self):
        if self._change_before is None:
            self._change_before = self.annotation_state()

    def cancel_change(self): self._change_before = None

    def commit_change(self):
        if self._change_before is None: return
        before, after = self._change_before, self.annotation_state(); self._change_before = None
        if before != after:
            self.undo_stack.append(before); self.undo_stack = self.undo_stack[-50:]
            self.redo_stack.clear()

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(self.annotation_state()); self.restore_state(self.undo_stack.pop())

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(self.annotation_state()); self.restore_state(self.redo_stack.pop())

    def delete_selected(self):
        handles = [item for item in self.scene.selectedItems() if hasattr(item, "role")]
        if handles:
            handle = handles[0]; owner = handle.owner
            if handle.role == "vertex" and isinstance(owner, PathAnnotationItem):
                self.begin_change()
                if owner.delete_vertex(handle.index): self.commit_change()
                else: self.cancel_change()
                return
        item = self.selected_annotation()
        if item:
            self.begin_change(); self.scene.removeItem(item); self.commit_change(); self.annotation_selection_changed()

    def rotate_selected(self, degrees):
        self._mutate_selected(lambda item: item.setRotation(item.rotation() + degrees))

    def handle_key(self, event):
        modifiers = event.modifiers()
        if modifiers & Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_Z:
            self.redo() if modifiers & Qt.KeyboardModifier.ShiftModifier else self.undo(); return True
        if modifiers & Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_Y:
            self.redo(); return True
        if event.key() == Qt.Key.Key_Delete:
            self.delete_selected(); return True
        if event.key() == Qt.Key.Key_Escape:
            if self.scene.preview is not None: self.scene.cancel_drawing()
            else: self.scene.clearSelection()
            return True
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter} and self.tool == "polyline":
            self.scene.finish_polyline(); return True
        return False

    def keyPressEvent(self, event):
        if self.handle_key(event): return
        super().keyPressEvent(event)

    def set_annotation_visibility(self, visible):
        for item in self.annotations(): item.setVisible(bool(visible))

    def showEvent(self, event):
        super().showEvent(event); QTimer.singleShot(0, self.fit_to_window)

    def fit_to_window(self):
        if not self.scene.sceneRect().isEmpty():
            self.graphicsView.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def actual_size(self): self.graphicsView.setTransform(QTransform())
    def previous(self): self.index = (self.index - 1) % len(self.photos); self.load_current()
    def next(self): self.index = (self.index + 1) % len(self.photos); self.load_current()

    def render_image(self):
        from qgis.PyQt.QtGui import QImage
        selected = [item.annotation_id for item in self.annotations() if item.isSelected()]
        for item in self.annotations(): item.set_handles_visible(False); item.setSelected(False)
        bounds = self.base_item.boundingRect()
        image = QImage(max(1, int(bounds.width())), max(1, int(bounds.height())), QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.white); painter = QPainter(image)
        self.scene.render(painter, QRectF(image.rect()), bounds); painter.end()
        for item in self.annotations():
            if item.annotation_id in selected: item.setSelected(True)
        return image

    def save_edit(self):
        if not self.save_callback or not self.ensure_editable(): return
        data, width, height, quality = encode_qimage(self.render_image())
        document = self.annotation_state()
        document["render"] = {"format": "image/jpeg", "width": width, "height": height,
                              "quality": quality, "max_bytes": 500 * 1024}
        self.save_callback(self.photos[self.index], data, "image/jpeg", document)
        self._loaded_state = document
        self._allow_reject = True
        self.accept()

    def replace_photo(self):
        if not self.replace_callback: return
        if QMessageBox.question(self, "사진 변경",
                "사진을 변경하면 기존 편집 객체와 편집본이 초기화됩니다. 계속하시겠습니까?") != QMessageBox.StandardButton.Yes:
            return
        path, _ = QFileDialog.getOpenFileName(self, "GIS 사진 변경", "", "Images (*.jpg *.jpeg *.png *.webp)")
        if not path: return
        self.replace_callback(self.photos[self.index], path, normalize_photo(path))
        self._allow_reject = True
        self.accept()

    def has_unapplied_changes(self):
        return self.can_write and self._loaded_state is not None \
            and self.annotation_state() != self._loaded_state

    def reject(self):
        if self._allow_reject or not self.has_unapplied_changes():
            return super().reject()
        dialog = QMessageBox(self)
        dialog.setWindowTitle("사진 편집")
        dialog.setText("사진 편집 내용을 적용하지 않았습니다.")
        apply_button = dialog.addButton("적용 후 닫기", QMessageBox.ButtonRole.AcceptRole)
        discard_button = dialog.addButton("편집 취소", QMessageBox.ButtonRole.DestructiveRole)
        dialog.addButton("계속 편집", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        if dialog.clickedButton() is apply_button:
            self.save_edit()
        elif dialog.clickedButton() is discard_button:
            self._allow_reject = True
            super().reject()

    def closeEvent(self, event):
        if self._allow_reject or not self.has_unapplied_changes():
            event.accept()
            return super().closeEvent(event)
        event.ignore()
        self.reject()
