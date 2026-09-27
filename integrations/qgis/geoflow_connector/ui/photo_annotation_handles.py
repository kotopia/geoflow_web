"""View-independent editing handles for Photo Studio annotations."""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QBrush, QColor, QFont, QPainter, QPen
from qgis.PyQt.QtWidgets import QGraphicsEllipseItem


class AnnotationHandle(QGraphicsEllipseItem):
    """A small scene handle that delegates geometry changes to its owner."""

    def __init__(self, owner, role, index=None):
        super().__init__(-6, -6, 12, 12, owner)
        self.owner, self.role, self.index = owner, role, index
        self.setBrush(QBrush(QColor("#ffffff")))
        self.setPen(QPen(QColor("#2563eb"), 2))
        self.setZValue(10000)
        self.setFlag(self.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setFlag(self.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setVisible(False)
        if role == "vertex":
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif role == "rotate":
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        elif role in {"top_right", "bottom_left"}:
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        else:
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setToolTip({"vertex": "점 이동", "rotate": "회전"}.get(role, "크기 조절"))

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self.role == "vertex":
            painter.setBrush(QBrush(QColor("#ffffff")))
            painter.setPen(QPen(QColor("#2563eb"), 2))
            painter.drawEllipse(self.rect())
            return
        if self.role == "rotate":
            painter.setBrush(QBrush(QColor("#ecfdf5")))
            painter.setPen(QPen(QColor("#059669"), 2))
            painter.drawEllipse(self.rect())
            font = QFont(painter.font()); font.setPixelSize(10); font.setBold(True)
            painter.setFont(font); painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "↻")
            return
        painter.setBrush(QBrush(QColor("#fff7ed")))
        painter.setPen(QPen(QColor("#ea580c"), 2))
        painter.drawRoundedRect(self.rect(), 2, 2)
        descending = self.role not in {"top_right", "bottom_left"}
        if descending:
            painter.drawLine(-3, -3, 3, 3)
            painter.drawLine(-3, -3, -3, 0); painter.drawLine(-3, -3, 0, -3)
            painter.drawLine(3, 3, 3, 0); painter.drawLine(3, 3, 0, 3)
        else:
            painter.drawLine(-3, 3, 3, -3)
            painter.drawLine(-3, 3, -3, 0); painter.drawLine(-3, 3, 0, 3)
            painter.drawLine(3, -3, 3, 0); painter.drawLine(3, -3, 0, -3)

    def mousePressEvent(self, event):
        self.owner.studio.begin_change()
        self.setSelected(True)
        event.accept()

    def mouseMoveEvent(self, event):
        self.owner.handle_drag(self.role, self.index, event.scenePos())
        event.accept()

    def mouseReleaseEvent(self, event):
        self.owner.studio.commit_change()
        event.accept()
