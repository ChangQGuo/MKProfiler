"""Small vector icons for the main visualization actions."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def action_icon(name: str, dark: bool) -> QIcon:
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor("#e3edf5" if dark else "#3f5165"), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    if name == "fit":
        for x, y, sx, sy in ((3, 3, 1, 1), (21, 3, -1, 1), (3, 21, 1, -1), (21, 21, -1, -1)):
            painter.drawLine(QPointF(x, y + 5 * sy), QPointF(x, y))
            painter.drawLine(QPointF(x, y), QPointF(x + 5 * sx, y))
    elif name == "overlay":
        painter.drawRoundedRect(QRectF(3, 4, 14, 13), 2, 2)
        painter.drawRoundedRect(QRectF(7, 8, 14, 13), 2, 2)
    elif name == "median":
        path = QPainterPath(QPointF(3, 16))
        path.cubicTo(7, 4, 11, 5, 12, 12)
        path.cubicTo(14, 19, 18, 17, 21, 7)
        painter.drawPath(path)
        painter.drawLine(QPointF(3, 20), QPointF(21, 20))
    elif name == "ruler":
        painter.drawRoundedRect(QRectF(3, 8, 18, 8), 1, 1)
        for x in (7, 10, 13, 16):
            painter.drawLine(QPointF(x, 8), QPointF(x, 11 if x % 2 else 13))
    elif name == "pca":
        painter.drawLine(QPointF(4, 4), QPointF(4, 20))
        painter.drawLine(QPointF(4, 20), QPointF(21, 20))
        for x, y in ((8, 15), (11, 10), (14, 14), (17, 7), (20, 10)):
            painter.drawEllipse(QPointF(x, y), 1.2, 1.2)
    elif name == "vae":
        for y, x in ((6, 8), (12, 16), (18, 11)):
            painter.drawLine(QPointF(3, y), QPointF(21, y))
            painter.setBrush(QColor("#e3edf5" if dark else "#3f5165"))
            painter.drawEllipse(QPointF(x, y), 2, 2)
    elif name == "distribution":
        for x, h in ((5, 5), (9, 10), (13, 15), (17, 8)):
            painter.drawRect(QRectF(x, 20 - h, 2.5, h))
    painter.end()
    return QIcon(pixmap)
