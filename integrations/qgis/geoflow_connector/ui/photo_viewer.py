"""GeoFlow in-plugin image viewer; private photo URLs never leave QGIS."""
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QPixmap, QTransform
from qgis.PyQt.QtWidgets import (
    QDialog, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView,
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)


class PanZoomView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)

    def wheelEvent(self, event):
        self.scale(1.2 if event.angleDelta().y() > 0 else 1 / 1.2,
                   1.2 if event.angleDelta().y() > 0 else 1 / 1.2)


class PhotoViewerDialog(QDialog):
    def __init__(self, client, photos, selected, parent=None):
        super().__init__(parent)
        self.client, self.photos = client, photos
        self.index = next((i for i, row in enumerate(photos)
                           if str(row.get("id")) == str(selected.get("id"))), 0)
        self.rotation = 0
        self.setWindowTitle("GeoFlow · 원본 사진")
        self.resize(1000, 760)
        root = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        for text, slot in (
            ("이전", self.previous), ("다음", self.next), ("확대", lambda: self.view.scale(1.25, 1.25)),
            ("축소", lambda: self.view.scale(.8, .8)), ("화면 맞춤", self.fit),
            ("100%", self.actual), ("좌 90°", lambda: self.rotate(-90)),
            ("우 90°", lambda: self.rotate(90)),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        root.addLayout(toolbar)
        self.scene = QGraphicsScene(self)
        self.view = PanZoomView(self)
        self.view.setScene(self.scene)
        root.addWidget(self.view, 1)
        self.caption = QLabel()
        self.caption.setWordWrap(True)
        root.addWidget(self.caption)
        self._load()

    def _load(self):
        if not self.photos:
            self.caption.setText("표시할 사진이 없습니다.")
            return
        photo = self.photos[self.index]
        url = str(photo.get("original_download_url") or photo.get("download_url") or "")
        pixmap = QPixmap()
        pixmap.loadFromData(self.client.get_bytes(url))
        self.scene.clear()
        self.item = QGraphicsPixmapItem(pixmap)
        self.scene.addItem(self.item)
        self.scene.setSceneRect(self.item.boundingRect())
        self.rotation = 0
        self.caption.setText(f"{self.index + 1} / {len(self.photos)} · {photo.get('original_name') or '사진'}")
        self.fit()

    def fit(self):
        if getattr(self, "item", None):
            self.view.fitInView(self.item, Qt.AspectRatioMode.KeepAspectRatio)

    def actual(self):
        self.view.setTransform(QTransform())
        if self.rotation:
            self.view.rotate(self.rotation)

    def rotate(self, degrees):
        self.rotation = (self.rotation + degrees) % 360
        self.view.rotate(degrees)

    def previous(self):
        if self.photos:
            self.index = (self.index - 1) % len(self.photos)
            self._load()

    def next(self):
        if self.photos:
            self.index = (self.index + 1) % len(self.photos)
            self._load()
