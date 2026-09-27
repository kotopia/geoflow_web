"""Editable QGraphicsItems and JSON serialization for Photo Studio."""

import math
from uuid import uuid4

from qgis.PyQt.QtCore import QPointF, QRectF, Qt
from qgis.PyQt.QtGui import (
    QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPixmap,
)
from qgis.PyQt.QtWidgets import (
    QGraphicsEllipseItem, QGraphicsLineItem, QGraphicsPathItem,
    QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsSimpleTextItem,
    QInputDialog,
)

from .photo_annotation_handles import AnnotationHandle
from .photo_icons import draw_icon


ANNOTATION_TYPES = frozenset({
    "line", "polyline", "freehand", "rectangle", "ellipse", "text", "icon",
})
MAX_ANNOTATIONS = 200
MAX_POINTS = 2000


def _point(value):
    return QPointF(float(value[0]), float(value[1]))


def _pair(value):
    return [round(float(value.x()), 3), round(float(value.y()), 3)]


def annotation_document(width, height, rows, render=None):
    return {
        "version": 2,
        "format": "annotation-json",
        "canvas": {"width": int(width), "height": int(height)},
        "annotations": rows[:MAX_ANNOTATIONS],
        "render": dict(render or {}),
    }


def is_editable_document(value):
    return (
        isinstance(value, dict)
        and value.get("version") == 2
        and value.get("format") == "annotation-json"
        and isinstance(value.get("annotations"), list)
    )


class AnnotationMixin:
    """Shared selection, movement, style, handle, and serialization behavior."""

    def setup_annotation(self, studio, data, annotation_type):
        self.studio = studio
        self.annotation_id = str(data.get("id") or uuid4())
        self.annotation_type = annotation_type
        self.stroke = str(data.get("stroke") or data.get("color") or "#ef4444")
        self.stroke_width = max(1, min(40, int(data.get("stroke_width") or 5)))
        self.fill = str(data.get("fill") or "#00000000")
        self.setOpacity(max(0.05, min(1.0, float(data.get("opacity", 1.0)))))
        self._stored_rotation = float(data.get("rotation") or 0.0)
        self.setZValue(float(data.get("z") or 0.0))
        self.handles = []
        self.setFlag(self.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(self.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(self.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.apply_style()

    def finish_setup(self):
        self.setTransformOriginPoint(self.boundingRect().center())
        self.setRotation(self._stored_rotation)

    def add_handle(self, role, index=None):
        handle = AnnotationHandle(self, role, index)
        self.handles.append(handle)
        return handle

    def apply_style(self):
        if hasattr(self, "setPen"):
            self.setPen(QPen(QColor(self.stroke), self.stroke_width,
                             Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                             Qt.PenJoinStyle.RoundJoin))
        if hasattr(self, "setBrush") and self.annotation_type in {"rectangle", "ellipse"}:
            self.setBrush(QBrush(QColor(self.fill)))

    def base_json(self):
        return {
            "id": self.annotation_id,
            "type": self.annotation_type,
            "stroke": self.stroke,
            "stroke_width": self.stroke_width,
            "opacity": round(float(self.opacity()), 3),
            "rotation": round(float(self.rotation()), 3),
            "z": round(float(self.zValue()), 3),
        }

    def set_annotation_color(self, value):
        self.stroke = str(value)
        self.apply_style()
        if self.annotation_type == "text":
            self.setBrush(QBrush(QColor(self.stroke)))
        if self.annotation_type == "icon":
            self.refresh_pixmap()

    def set_stroke_width(self, value):
        self.stroke_width = max(1, min(40, int(value)))
        self.apply_style()

    def set_fill_color(self, value):
        self.fill = str(value)
        self.apply_style()

    def set_handles_visible(self, visible):
        for handle in self.handles:
            handle.setVisible(bool(visible))
        if visible:
            self.update_handles()

    def itemChange(self, change, value):
        result = super().itemChange(change, value)
        selected_change = self.GraphicsItemChange.ItemSelectedHasChanged
        if change == selected_change and hasattr(self, "studio"):
            self.set_handles_visible(bool(value))
            self.studio.annotation_selection_changed(self if value else None)
        return result

    def mousePressEvent(self, event):
        self.studio.begin_change()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.studio.commit_change()
        self.update_handles()

    def rotate_from_scene(self, point):
        center = self.mapToScene(self.boundingRect().center())
        angle = math.degrees(math.atan2(point.y() - center.y(), point.x() - center.x())) + 90
        self.setTransformOriginPoint(self.boundingRect().center())
        self.setRotation(angle)
        self.update_handles()


class LineAnnotationItem(AnnotationMixin, QGraphicsLineItem):
    def __init__(self, studio, data):
        start, end = _point(data.get("start", [0, 0])), _point(data.get("end", [1, 1]))
        super().__init__(0, 0, end.x() - start.x(), end.y() - start.y())
        self.setPos(start)
        self.setup_annotation(studio, data, "line")
        self.finish_setup()
        self.add_handle("vertex", 0); self.add_handle("vertex", 1)

    def update_handles(self):
        line = self.line()
        self.handles[0].setPos(line.p1()); self.handles[1].setPos(line.p2())

    def handle_drag(self, role, index, scene_point):
        local = self.mapFromScene(scene_point); line = self.line()
        self.setLine(local, line.p2()) if index == 0 else self.setLine(line.p1(), local)
        self.update_handles()

    def to_json(self):
        row = self.base_json(); line = self.line()
        row.update(start=_pair(self.mapToScene(line.p1())), end=_pair(self.mapToScene(line.p2())))
        row["rotation"] = 0
        return row


class PathAnnotationItem(AnnotationMixin, QGraphicsPathItem):
    def __init__(self, studio, data, annotation_type):
        points = [_point(p) for p in data.get("points", [])[:MAX_POINTS]]
        if len(points) < 2:
            points = [QPointF(0, 0), QPointF(1, 1)]
        origin = points[0]
        self.points = [p - origin for p in points]
        super().__init__()
        self.setPos(origin)
        self.setup_annotation(studio, data, annotation_type)
        self.rebuild_path()
        self.finish_setup()
        if annotation_type == "polyline":
            for index in range(len(self.points)):
                self.add_handle("vertex", index)
        else:
            self.add_handle("scale")

    def rebuild_path(self):
        path = QPainterPath(self.points[0])
        for point in self.points[1:]:
            path.lineTo(point)
        self.setPath(path)
        self.update_handles()

    def update_handles(self):
        if self.annotation_type == "polyline":
            for handle, point in zip(self.handles, self.points):
                handle.setPos(point)
        elif self.handles:
            self.handles[0].setPos(self.boundingRect().bottomRight())

    def handle_drag(self, role, index, scene_point):
        local = self.mapFromScene(scene_point)
        if role == "vertex" and index is not None:
            self.points[index] = local
        elif role == "scale":
            bounds = self.path().boundingRect()
            if bounds.width() and bounds.height():
                factor = max(.1, min(10.0, max(
                    abs(local.x() - bounds.left()) / bounds.width(),
                    abs(local.y() - bounds.top()) / bounds.height(),
                )))
                self.setScale(factor)
        self.rebuild_path()

    def add_vertex(self, scene_point):
        if self.annotation_type != "polyline" or len(self.points) >= MAX_POINTS:
            return
        point = self.mapFromScene(scene_point)
        best_index, best_distance = 1, float("inf")
        for index in range(len(self.points) - 1):
            a, b = self.points[index], self.points[index + 1]
            dx, dy = b.x() - a.x(), b.y() - a.y()
            length = dx * dx + dy * dy
            t = 0 if not length else max(0, min(1, ((point.x()-a.x())*dx + (point.y()-a.y())*dy) / length))
            projected = QPointF(a.x()+t*dx, a.y()+t*dy)
            distance = math.hypot(point.x()-projected.x(), point.y()-projected.y())
            if distance < best_distance:
                best_index, best_distance = index + 1, distance
        self.points.insert(best_index, point)
        self.add_handle("vertex", len(self.handles))
        for index, handle in enumerate(self.handles):
            handle.index = index
        self.rebuild_path()

    def delete_vertex(self, index):
        if self.annotation_type != "polyline" or len(self.points) <= 2:
            return False
        self.points.pop(index)
        handle = self.handles.pop(index)
        if handle.scene(): self.scene().removeItem(handle)
        for position, remaining in enumerate(self.handles): remaining.index = position
        self.rebuild_path(); return True

    def to_json(self):
        row = self.base_json()
        row["points"] = [_pair(self.mapToScene(point)) for point in self.points]
        row["rotation"] = 0
        return row


class ShapeAnnotationItem(AnnotationMixin):
    def shape_setup(self, studio, data, annotation_type):
        self.setup_annotation(studio, data, annotation_type)
        self.setPos(float(data.get("x", 0)), float(data.get("y", 0)))
        self.finish_setup()
        for role in ("top_left", "top_right", "bottom_right", "bottom_left"):
            self.add_handle(role)
        self.add_handle("rotate")

    def update_handles(self):
        rect = self.rect()
        for handle, point in zip(self.handles[:4], (
                rect.topLeft(), rect.topRight(), rect.bottomRight(), rect.bottomLeft())):
            handle.setPos(point)
        self.handles[4].setPos(QPointF(rect.center().x(), rect.top() - 30))

    def handle_drag(self, role, index, scene_point):
        if role == "rotate":
            self.rotate_from_scene(scene_point); return
        point, rect = self.mapFromScene(scene_point), QRectF(self.rect())
        if role == "top_left": rect.setTopLeft(point)
        elif role == "top_right": rect.setTopRight(point)
        elif role == "bottom_right": rect.setBottomRight(point)
        elif role == "bottom_left": rect.setBottomLeft(point)
        self.setRect(rect.normalized()); self.update_handles()

    def shape_json(self):
        row, rect = self.base_json(), self.rect()
        row.update(x=round(self.pos().x()+rect.x(), 3), y=round(self.pos().y()+rect.y(), 3),
                   width=round(rect.width(), 3), height=round(rect.height(), 3), fill=self.fill)
        return row


class RectAnnotationItem(ShapeAnnotationItem, QGraphicsRectItem):
    def __init__(self, studio, data):
        super().__init__(0, 0, max(1, float(data.get("width", 1))), max(1, float(data.get("height", 1))))
        self.shape_setup(studio, data, "rectangle")
    def to_json(self): return self.shape_json()


class EllipseAnnotationItem(ShapeAnnotationItem, QGraphicsEllipseItem):
    def __init__(self, studio, data):
        super().__init__(0, 0, max(1, float(data.get("width", 1))), max(1, float(data.get("height", 1))))
        self.shape_setup(studio, data, "ellipse")
    def to_json(self): return self.shape_json()


class TextAnnotationItem(AnnotationMixin, QGraphicsSimpleTextItem):
    def __init__(self, studio, data):
        super().__init__(str(data.get("text") or "텍스트"))
        self.font_size = max(8, min(160, int(data.get("font_size") or 28)))
        self.bold = bool(data.get("bold", True))
        self.setPos(float(data.get("x", 0)), float(data.get("y", 0)))
        self.setup_annotation(studio, data, "text")
        self.apply_text_style()
        self.finish_setup()
        self.add_handle("scale"); self.add_handle("rotate")

    def apply_text_style(self):
        font = QFont(self.font()); font.setPointSize(self.font_size); font.setBold(self.bold)
        self.setFont(font); self.setBrush(QBrush(QColor(self.stroke))); self.update_handles()

    def update_handles(self):
        if not self.handles: return
        rect = self.boundingRect(); self.handles[0].setPos(rect.bottomRight())
        self.handles[1].setPos(QPointF(rect.center().x(), rect.top()-30))

    def handle_drag(self, role, index, scene_point):
        if role == "rotate": self.rotate_from_scene(scene_point); return
        local = self.mapFromScene(scene_point)
        self.font_size = max(8, min(160, int(max(local.x(), local.y()) / 3)))
        self.apply_text_style()

    def mouseDoubleClickEvent(self, event):
        value, ok = QInputDialog.getText(self.studio, "텍스트 수정", "사진에 표시할 내용", text=self.text())
        if ok and value:
            self.studio.begin_change(); self.setText(value); self.update_handles(); self.studio.commit_change()
        event.accept()

    def to_json(self):
        row = self.base_json(); row.update(text=self.text(), x=round(self.pos().x(), 3),
            y=round(self.pos().y(), 3), font_size=self.font_size, bold=self.bold,
            color=self.stroke)
        return row


class IconAnnotationItem(AnnotationMixin, QGraphicsPixmapItem):
    def __init__(self, studio, data):
        self.icon_name = str(data.get("icon") or "warning")
        self.icon_size = max(20, min(400, int(data.get("size") or 76)))
        super().__init__()
        self.setPos(float(data.get("x", 0)), float(data.get("y", 0)))
        self.setup_annotation(studio, data, "icon")
        self.refresh_pixmap()
        self.finish_setup()
        self.add_handle("scale"); self.add_handle("rotate")

    def refresh_pixmap(self):
        from qgis.PyQt.QtGui import QImage
        image = QImage(self.icon_size, self.icon_size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0); painter = QPainter(image)
        draw_icon(painter, self.icon_name, QPointF(self.icon_size/2, self.icon_size/2),
                  self.icon_size-10, self.stroke)
        painter.end(); self.setPixmap(QPixmap.fromImage(image)); self.setOffset(-self.icon_size/2, -self.icon_size/2)
        self.update_handles()

    def update_handles(self):
        if not self.handles: return
        rect = self.boundingRect(); self.handles[0].setPos(rect.bottomRight())
        self.handles[1].setPos(QPointF(rect.center().x(), rect.top()-30))

    def handle_drag(self, role, index, scene_point):
        if role == "rotate": self.rotate_from_scene(scene_point); return
        local = self.mapFromScene(scene_point)
        self.icon_size = max(20, min(400, int(2*max(abs(local.x()), abs(local.y())))))
        self.refresh_pixmap()

    def to_json(self):
        row = self.base_json(); row.update(icon=self.icon_name, x=round(self.pos().x(), 3),
            y=round(self.pos().y(), 3), size=self.icon_size, color=self.stroke)
        return row


def create_annotation(studio, data):
    kind = str(data.get("type") or "")
    if kind == "line": return LineAnnotationItem(studio, data)
    if kind == "polyline": return PathAnnotationItem(studio, data, "polyline")
    if kind == "freehand": return PathAnnotationItem(studio, data, "freehand")
    if kind == "rectangle": return RectAnnotationItem(studio, data)
    if kind == "ellipse": return EllipseAnnotationItem(studio, data)
    if kind == "text": return TextAnnotationItem(studio, data)
    if kind == "icon": return IconAnnotationItem(studio, data)
    raise ValueError("지원하지 않는 사진 annotation 형식입니다.")
