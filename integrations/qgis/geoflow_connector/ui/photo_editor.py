"""Small non-destructive raster editor for GIS field evidence photos."""
import json

from qgis.PyQt.QtCore import QByteArray, QBuffer, QIODevice, QPointF, QRectF, Qt
from qgis.PyQt.QtGui import (
    QBrush, QColor, QImage, QPainter, QPainterPath, QPen, QPixmap, QPolygonF,
    QTransform,
)
from qgis.PyQt.QtWidgets import (
    QComboBox, QDialog, QGraphicsEllipseItem, QGraphicsLineItem,
    QGraphicsPathItem, QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene,
    QGraphicsSimpleTextItem, QGraphicsView, QHBoxLayout, QInputDialog,
    QPushButton, QVBoxLayout,
)

from .photo_icons import ICON_NAMES, draw_icon


class EditorScene(QGraphicsScene):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor, self.start, self.preview = editor, None, None

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self.editor.tool == "pan":
            return super().mousePressEvent(event)
        self.editor.push_undo()
        self.start = event.scenePos()
        if self.editor.tool == "text":
            value, ok = QInputDialog.getText(self.editor, "텍스트", "사진에 표시할 내용")
            if ok and value:
                item = QGraphicsSimpleTextItem(value)
                item.setBrush(QBrush(QColor("#ef4444")))
                font = item.font()
                font.setPointSize(18)
                font.setBold(True)
                item.setFont(font)
                item.setPos(self.start)
                item.setFlag(item.GraphicsItemFlag.ItemIsMovable, True)
                self.addItem(item)
            self.start = None
        elif self.editor.tool.startswith("icon:"):
            self.editor.insert_icon(self.editor.tool.split(":", 1)[1], self.start)
            self.start = None
        else:
            self.preview = self.editor.create_shape(self.editor.tool, self.start, self.start)
            if self.preview:
                self.addItem(self.preview)

    def mouseMoveEvent(self, event):
        if self.start is not None and self.preview is not None:
            self.editor.update_shape(self.preview, self.editor.tool, self.start, event.scenePos())
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.start is not None and self.preview is not None:
            self.editor.update_shape(self.preview, self.editor.tool, self.start, event.scenePos())
            self.preview.setFlag(self.preview.GraphicsItemFlag.ItemIsMovable, True)
        self.start, self.preview = None, None
        super().mouseReleaseEvent(event)


class PhotoEditorDialog(QDialog):
    def __init__(self, raw, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GeoFlow · 사진 편집")
        self.resize(1100, 800)
        self.output_bytes, self.edit_data = b"", {}
        self.tool, self.undo_stack, self.redo_stack = "pan", [], []
        pixmap = QPixmap()
        if not pixmap.loadFromData(raw):
            raise ValueError("사진을 읽을 수 없습니다.")
        self.scene = EditorScene(self)
        self.base_item = QGraphicsPixmapItem(pixmap)
        self.scene.addItem(self.base_item)
        self.scene.setSceneRect(self.base_item.boundingRect())
        self.view = QGraphicsView(self.scene, self)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        root = QVBoxLayout(self)
        tools = QHBoxLayout()
        for text, name in (("이동", "pan"), ("선", "line"), ("화살표", "arrow"),
                           ("사각형", "rect"), ("원", "ellipse"), ("텍스트", "text")):
            button = QPushButton(text)
            button.clicked.connect(lambda _=False, n=name: self.set_tool(n))
            tools.addWidget(button)
        self.icons = QComboBox()
        self.icons.addItem("아이콘 선택", "")
        for key, label in ICON_NAMES.items():
            self.icons.addItem(label, key)
        self.icons.currentIndexChanged.connect(
            lambda: self.set_tool("icon:" + self.icons.currentData()) if self.icons.currentData() else None
        )
        tools.addWidget(self.icons)
        for text, slot in (("좌 90°", lambda: self.rotate(-90)), ("우 90°", lambda: self.rotate(90)),
                           ("Undo", self.undo), ("Redo", self.redo), ("화면 맞춤", self.fit)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            tools.addWidget(button)
        tools.addStretch(1)
        root.addLayout(tools)
        root.addWidget(self.view, 1)
        actions = QHBoxLayout()
        reset = QPushButton("원본으로")
        reset.clicked.connect(lambda: self.restore(pixmap))
        save, cancel = QPushButton("저장"), QPushButton("취소")
        save.clicked.connect(self.save)
        cancel.clicked.connect(self.reject)
        actions.addWidget(reset)
        actions.addStretch(1)
        actions.addWidget(save)
        actions.addWidget(cancel)
        root.addLayout(actions)
        self.fit()

    def set_tool(self, name):
        self.tool = name
        self.view.setDragMode(
            QGraphicsView.DragMode.ScrollHandDrag if name == "pan"
            else QGraphicsView.DragMode.NoDrag
        )

    def create_shape(self, tool, start, end):
        pen = QPen(QColor("#ef4444"), 5)
        if tool == "line":
            return QGraphicsLineItem(start.x(), start.y(), end.x(), end.y())
        if tool == "arrow":
            return QGraphicsPathItem()
        if tool == "rect":
            return QGraphicsRectItem(QRectF(start, end).normalized())
        if tool == "ellipse":
            return QGraphicsEllipseItem(QRectF(start, end).normalized())
        return None

    def update_shape(self, item, tool, start, end):
        pen = QPen(QColor("#ef4444"), 5)
        item.setPen(pen)
        if tool == "line":
            item.setLine(start.x(), start.y(), end.x(), end.y())
        elif tool in {"rect", "ellipse"}:
            item.setRect(QRectF(start, end).normalized())
        elif tool == "arrow":
            import math
            dx, dy = end.x()-start.x(), end.y()-start.y()
            angle = math.atan2(dy, dx)
            length = 24
            left = QPointF(end.x()-length*math.cos(angle-.55), end.y()-length*math.sin(angle-.55))
            right = QPointF(end.x()-length*math.cos(angle+.55), end.y()-length*math.sin(angle+.55))
            path = QPainterPath(start)
            path.lineTo(end)
            path.moveTo(left)
            path.lineTo(end)
            path.lineTo(right)
            item.setPath(path)

    def insert_icon(self, name, center):
        size = 64
        image = QImage(size+12, size+12, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        draw_icon(painter, name, QPointF((size+12)/2, (size+12)/2), size)
        painter.end()
        item = QGraphicsPixmapItem(QPixmap.fromImage(image))
        item.setOffset(-(size+12)/2, -(size+12)/2)
        item.setPos(center)
        item.setFlag(item.GraphicsItemFlag.ItemIsMovable, True)
        self.scene.addItem(item)

    def render_image(self):
        bounds = self.scene.sceneRect()
        image = QImage(max(1, int(bounds.width())), max(1, int(bounds.height())),
                       QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.white)
        painter = QPainter(image)
        self.scene.render(painter, QRectF(image.rect()), bounds)
        painter.end()
        return image

    def snapshot(self):
        return self.render_image()

    def push_undo(self):
        self.undo_stack.append(self.snapshot())
        self.undo_stack = self.undo_stack[-20:]
        self.redo_stack.clear()

    def restore(self, value):
        image = value.toImage() if isinstance(value, QPixmap) else value
        self.scene.clear()
        self.base_item = QGraphicsPixmapItem(QPixmap.fromImage(image))
        self.scene.addItem(self.base_item)
        self.scene.setSceneRect(self.base_item.boundingRect())
        self.fit()

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(self.snapshot())
            self.restore(self.undo_stack.pop())

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(self.snapshot())
            self.restore(self.redo_stack.pop())

    def rotate(self, degrees):
        self.push_undo()
        image = self.render_image().transformed(QTransform().rotate(degrees),
                                                Qt.TransformationMode.SmoothTransformation)
        self.restore(image)

    def fit(self):
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def save(self):
        image = self.render_image()
        data = QByteArray()
        buffer = QBuffer(data)
        mode = getattr(getattr(QIODevice, "OpenModeFlag", QIODevice), "WriteOnly")
        buffer.open(mode)
        image.save(buffer, "PNG")
        self.output_bytes = bytes(data)
        self.edit_data = {"version": 1, "format": "raster-png", "width": image.width(),
                          "height": image.height()}
        self.accept()
