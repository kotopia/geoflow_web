"""Single extensible registry for field annotation icons."""
from qgis.PyQt.QtCore import QPointF, QRectF
from qgis.PyQt.QtGui import QBrush, QColor, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

ICON_NAMES = {
    "arrow": "화살표", "location": "위치 표시", "check": "체크",
    "warning": "주의", "star": "별표", "pipe": "관로 방향",
    "camera": "촬영 방향", "start": "시작점", "end": "끝점",
    **{f"number_{n}": f"번호 {n}" for n in range(1, 10)},
}


def feather_icon(name):
    """Return an icon already compiled into the plugin's Feather resource."""
    return QIcon(f":/geoflow/feather/{name}.svg")


def annotation_icon(name, size=32):
    image = QImage(size + 8, size + 8, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    draw_icon(painter, name, QPointF((size + 8) / 2, (size + 8) / 2), size)
    painter.end()
    return QIcon(QPixmap.fromImage(image))


def draw_icon(painter, name, center, size=48):
    """Render a registry icon with QPainter primitives, independent of DPI/resources."""
    x, y, r = center.x(), center.y(), size / 2
    painter.save()
    painter.setRenderHint(painter.RenderHint.Antialiasing, True)
    painter.setPen(QPen(QColor("#ef4444"), max(3, int(size / 12))))
    painter.setBrush(QBrush(QColor(255, 255, 255, 210)))
    if name.startswith("number_"):
        painter.drawEllipse(QPointF(x, y), r, r)
        painter.drawText(QRectF(x-r, y-r, size, size), 0x84, name.split("_")[1])
    elif name == "check":
        painter.drawLine(QPointF(x-r*.7, y), QPointF(x-r*.15, y+r*.6))
        painter.drawLine(QPointF(x-r*.15, y+r*.6), QPointF(x+r*.8, y-r*.65))
    elif name in {"arrow", "pipe", "camera"}:
        painter.drawLine(QPointF(x-r, y), QPointF(x+r*.55, y))
        painter.drawPolygon(QPolygonF([QPointF(x+r*.55, y-r*.45), QPointF(x+r, y), QPointF(x+r*.55, y+r*.45)]))
    elif name == "location":
        path = QPainterPath(QPointF(x, y+r))
        path.cubicTo(QPointF(x-r, y), QPointF(x-r, y-r), QPointF(x, y-r))
        path.cubicTo(QPointF(x+r, y-r), QPointF(x+r, y), QPointF(x, y+r))
        painter.drawPath(path)
        painter.drawEllipse(QPointF(x, y-r*.25), r*.22, r*.22)
    elif name == "warning":
        painter.drawPolygon(QPolygonF([QPointF(x, y-r), QPointF(x+r, y+r), QPointF(x-r, y+r)]))
        painter.drawText(QRectF(x-r, y-r*.35, size, size), 0x84, "!")
    elif name in {"start", "end"}:
        painter.drawEllipse(QPointF(x, y), r, r)
        painter.drawText(QRectF(x-r, y-r, size, size), 0x84, "S" if name == "start" else "E")
    else:
        points = []
        import math
        for i in range(10):
            angle = -math.pi/2 + i*math.pi/5
            radius = r if i % 2 == 0 else r*.42
            points.append(QPointF(x + math.cos(angle)*radius, y + math.sin(angle)*radius))
        painter.drawPolygon(QPolygonF(points))
    painter.restore()
