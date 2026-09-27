"""View-independent editing handles for Photo Studio annotations."""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QBrush, QColor, QPen
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

