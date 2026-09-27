"""Unified viewer/editor for GeoFlow GIS photos."""
import math
import os

from qgis.PyQt.QtCore import QPointF, QRectF, Qt, QTimer
from qgis.PyQt.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap, QTransform
try:
    from qgis.PyQt.QtGui import QAction
except ImportError:  # QAction lives in QtWidgets on the QGIS 3 / Qt 5 stack.
    from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtWidgets import (
    QFileDialog, QGraphicsEllipseItem, QGraphicsLineItem,
    QGraphicsPathItem, QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene,
    QGraphicsSimpleTextItem, QGraphicsView, QInputDialog, QMenu, QMessageBox,
    QToolButton, QDialog,
)
from qgis.PyQt.uic import loadUiType

from .photo_icons import ICON_NAMES, annotation_icon, draw_icon, feather_icon
from .photo_normalizer import encode_qimage, normalize_photo


FORM_CLASS, _ = loadUiType(os.path.join(os.path.dirname(__file__), "forms", "photo_studio.ui"))


class StudioView(QGraphicsView):
    def wheelEvent(self, event):
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        self.scale(factor, factor)

    def keyPressEvent(self, event):
        scene = self.scene()
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter} and hasattr(scene, "finish_polyline"):
            scene.finish_polyline()
            return
        if event.key() == Qt.Key.Key_Escape and hasattr(scene, "cancel_drawing"):
            scene.cancel_drawing()
            return
        super().keyPressEvent(event)


class StudioScene(QGraphicsScene):
    def __init__(self, studio):
        super().__init__(studio)
        self.studio = studio
        self.start = self.preview = None
        self.points = []

    def cancel_drawing(self):
        if self.preview is not None:
            self.removeItem(self.preview)
        self.start = self.preview = None
        self.points = []

    def finish_polyline(self):
        if self.studio.tool != "polyline" or len(self.points) < 2:
            self.cancel_drawing()
            return
        self.preview.setFlag(self.preview.GraphicsItemFlag.ItemIsMovable, True)
        self.start = self.preview = None
        self.points = []

    def mouseDoubleClickEvent(self, event):
        if self.studio.tool == "polyline":
            self.finish_polyline()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        tool = self.studio.tool
        if event.button() != Qt.MouseButton.LeftButton or tool == "pan":
            return super().mousePressEvent(event)
        if tool == "polyline":
            if not self.points:
                self.studio.push_undo()
                self.preview = QGraphicsPathItem()
                self.preview.setPen(self.studio.pen())
                self.addItem(self.preview)
            self.points.append(event.scenePos())
            self._polyline_preview(event.scenePos())
            return
        self.studio.push_undo()
        self.start = event.scenePos()
        if tool == "text":
            value, ok = QInputDialog.getText(self.studio, "텍스트", "사진에 표시할 내용")
            if ok and value:
                item = QGraphicsSimpleTextItem(value)
                item.setBrush(QColor("#ef4444"))
                font = item.font(); font.setPointSize(18); font.setBold(True); item.setFont(font)
                item.setPos(self.start); item.setFlag(item.GraphicsItemFlag.ItemIsMovable, True)
                self.addItem(item)
            self.start = None
        elif tool.startswith("icon:"):
            self.studio.insert_annotation(tool.split(":", 1)[1], self.start)
            self.start = None
        elif tool == "freehand":
            self.points = [self.start]
            self.preview = QGraphicsPathItem(); self.preview.setPen(self.studio.pen()); self.addItem(self.preview)
        else:
            self.preview = self.studio.create_shape(tool, self.start, self.start)
            if self.preview is not None:
                self.preview.setPen(self.studio.pen()); self.addItem(self.preview)

    def _polyline_preview(self, cursor):
        path = QPainterPath(self.points[0])
        for point in self.points[1:]: path.lineTo(point)
        if cursor != self.points[-1]: path.lineTo(cursor)
        self.preview.setPath(path)

    def mouseMoveEvent(self, event):
        if self.studio.tool == "polyline" and self.preview is not None:
            self._polyline_preview(event.scenePos()); return
        if self.studio.tool == "freehand" and self.start is not None:
            point = event.scenePos()
            if not self.points or math.hypot(point.x()-self.points[-1].x(), point.y()-self.points[-1].y()) >= 3:
                self.points.append(point)
                path = QPainterPath(self.points[0])
                for sampled in self.points[1::2]: path.lineTo(sampled)
                if self.points[-1] != self.points[1::2][-1]: path.lineTo(self.points[-1])
                self.preview.setPath(path)
            return
        if self.start is not None and self.preview is not None:
            self.studio.update_shape(self.preview, self.studio.tool, self.start, event.scenePos()); return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.studio.tool in {"polyline", "pan"}:
            return super().mouseReleaseEvent(event)
        if self.start is not None and self.preview is not None:
            if self.studio.tool != "freehand":
                self.studio.update_shape(self.preview, self.studio.tool, self.start, event.scenePos())
            self.preview.setFlag(self.preview.GraphicsItemFlag.ItemIsMovable, True)
        self.start = self.preview = None
        self.points = []
        super().mouseReleaseEvent(event)


class PhotoStudioDialog(QDialog, FORM_CLASS):
    def __init__(self, client, photos, selected, *, can_write=False,
                 save_callback=None, replace_callback=None, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.client, self.photos, self.can_write = client, photos, can_write
        self.save_callback, self.replace_callback = save_callback, replace_callback
        self.index = next((i for i, row in enumerate(photos)
                           if str(row.get("id")) == str(selected.get("id"))), 0)
        self.tool, self.undo_stack, self.redo_stack = "pan", [], []
        self._source_pixmap = QPixmap()
        self.scene = StudioScene(self)
        replacement = StudioView(self)
        self.rootLayout.replaceWidget(self.graphicsView, replacement)
        self.graphicsView.deleteLater(); self.graphicsView = replacement
        self.graphicsView.setScene(self.scene)
        self.graphicsView.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.graphicsView.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._build_toolbar()
        self._button(self.replaceButton, "refresh-cw", "사진 변경", self.replace_photo)
        self._button(self.saveButton, "save", "편집본 저장", self.save_edit)
        self._button(self.cancelButton, "x", "닫기", self.reject)
        self.replaceButton.setEnabled(can_write)
        self.saveButton.setEnabled(can_write)
        self.originalButton.clicked.connect(lambda: self.load_current("original"))
        self.editedButton.clicked.connect(lambda: self.load_current("edited"))
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
        self._action("rotate-ccw", "왼쪽 90도 회전", lambda: self.rotate(-90))
        self._action("rotate-cw", "오른쪽 90도 회전", lambda: self.rotate(90))
        self.studioToolbar.addSeparator()
        self._action("move", "이동", lambda: self.set_tool("pan"))
        line_button = QToolButton(self)
        line_button.setIcon(feather_icon("minus")); line_button.setToolTip("선 도구")
        line_button.setAccessibleName("선 도구"); line_button.setPopupMode(QToolButton.ToolButtonPopupMode.DelayedPopup)
        menu = QMenu(line_button)
        for label, tool, icon in (("직선", "line", "minus"), ("폴리선", "polyline", "activity"),
                                  ("자유선", "freehand", "edit-2")):
            action = menu.addAction(feather_icon(icon), label)
            action.triggered.connect(lambda _=False, value=tool: self.set_tool(value))
        line_button.setMenu(menu); line_button.clicked.connect(lambda: self.set_tool("line"))
        self.studioToolbar.addWidget(line_button)
        self._action("square", "사각형", lambda: self.set_tool("rect"))
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
        self._action("corner-up-left", "실행 취소", self.undo)
        self._action("corner-up-right", "다시 실행", self.redo)

    def pen(self): return QPen(QColor("#ef4444"), 5)

    def set_tool(self, name):
        self.scene.cancel_drawing(); self.tool = name
        self.graphicsView.setDragMode(QGraphicsView.DragMode.ScrollHandDrag if name == "pan"
                                      else QGraphicsView.DragMode.NoDrag)

    def _photo_url(self, photo, representation):
        if representation == "original":
            return str(photo.get("original_download_url") or photo.get("download_url") or "")
        return str(photo.get("display_download_url") or photo.get("download_url") or "")

    def load_current(self, representation="edited"):
        if not self.photos: return
        photo = self.photos[self.index]
        url = self._photo_url(photo, representation)
        pixmap = QPixmap(); pixmap.loadFromData(self.client.get_bytes(url))
        if pixmap.isNull(): raise ValueError("사진을 읽을 수 없습니다.")
        self._source_pixmap = pixmap; self.restore(pixmap)
        self.statusLabel.setText(f"{self.index+1} / {len(self.photos)} · {photo.get('original_name') or '사진'}")
        self.originalButton.setChecked(representation == "original")
        self.editedButton.setChecked(representation == "edited")
        QTimer.singleShot(0, self.fit_to_window)

    def showEvent(self, event):
        super().showEvent(event); QTimer.singleShot(0, self.fit_to_window)

    def fit_to_window(self):
        if not self.scene.sceneRect().isEmpty():
            self.graphicsView.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def actual_size(self): self.graphicsView.setTransform(QTransform())
    def previous(self): self.index = (self.index - 1) % len(self.photos); self.load_current()
    def next(self): self.index = (self.index + 1) % len(self.photos); self.load_current()

    def create_shape(self, tool, start, end):
        if tool == "line": return QGraphicsLineItem(start.x(), start.y(), end.x(), end.y())
        if tool == "rect": return QGraphicsRectItem(QRectF(start, end).normalized())
        if tool == "ellipse": return QGraphicsEllipseItem(QRectF(start, end).normalized())
        return None

    def update_shape(self, item, tool, start, end):
        if tool == "line": item.setLine(start.x(), start.y(), end.x(), end.y())
        elif tool in {"rect", "ellipse"}: item.setRect(QRectF(start, end).normalized())

    def insert_annotation(self, name, center):
        from qgis.PyQt.QtGui import QImage
        image = QImage(76, 76, QImage.Format.Format_ARGB32_Premultiplied); image.fill(0)
        painter = QPainter(image); draw_icon(painter, name, QPointF(38, 38), 64); painter.end()
        item = QGraphicsPixmapItem(QPixmap.fromImage(image)); item.setOffset(-38, -38)
        item.setPos(center); item.setFlag(item.GraphicsItemFlag.ItemIsMovable, True); self.scene.addItem(item)

    def render_image(self):
        from qgis.PyQt.QtGui import QImage
        bounds = self.scene.sceneRect()
        image = QImage(max(1, int(bounds.width())), max(1, int(bounds.height())), QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.white); painter = QPainter(image)
        self.scene.render(painter, QRectF(image.rect()), bounds); painter.end(); return image

    def snapshot(self): return self.render_image()
    def push_undo(self): self.undo_stack.append(self.snapshot()); self.undo_stack = self.undo_stack[-20:]; self.redo_stack.clear()
    def restore(self, value):
        image = value.toImage() if isinstance(value, QPixmap) else value
        self.scene.clear(); self.base_item = QGraphicsPixmapItem(QPixmap.fromImage(image)); self.scene.addItem(self.base_item)
        self.scene.setSceneRect(self.base_item.boundingRect()); QTimer.singleShot(0, self.fit_to_window)
    def undo(self):
        if self.undo_stack: self.redo_stack.append(self.snapshot()); self.restore(self.undo_stack.pop())
    def redo(self):
        if self.redo_stack: self.undo_stack.append(self.snapshot()); self.restore(self.redo_stack.pop())
    def rotate(self, degrees):
        self.push_undo(); self.restore(self.render_image().transformed(QTransform().rotate(degrees),
                                             Qt.TransformationMode.SmoothTransformation))

    def save_edit(self):
        if not self.save_callback: return
        data, width, height, quality = encode_qimage(self.render_image())
        self.save_callback(self.photos[self.index], data, "image/jpeg", {
            "version": 2, "format": "raster-jpeg", "width": width, "height": height,
            "quality": quality, "max_bytes": 500 * 1024,
        })
        self.accept()

    def replace_photo(self):
        if not self.replace_callback: return
        if QMessageBox.question(self, "사진 변경", "사진을 변경하면 기존 편집본이 초기화됩니다. 계속하시겠습니까?") != QMessageBox.StandardButton.Yes:
            return
        path, _ = QFileDialog.getOpenFileName(self, "GIS 사진 변경", "", "Images (*.jpg *.jpeg *.png *.webp)")
        if not path: return
        normalized = normalize_photo(path)
        self.replace_callback(self.photos[self.index], path, normalized)
        self.accept()
