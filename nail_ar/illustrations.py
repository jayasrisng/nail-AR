from math import cos, pi, sin

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget


def nail_path():
    path = QPainterPath(QPointF(50, 5))
    path.cubicTo(20, 5, 12, 26, 12, 51)
    path.lineTo(17, 108)
    path.cubicTo(20, 137, 26, 151, 50, 151)
    path.cubicTo(74, 151, 80, 137, 83, 108)
    path.lineTo(88, 51)
    path.cubicTo(88, 26, 80, 5, 50, 5)
    return path


def star(painter, x, y, size, color):
    path = QPainterPath(QPointF(x, y - size))
    for dx, dy in ((.22, -.22), (.72, 0), (.22, .22), (0, 1), (-.22, .22), (-.72, 0), (-.22, -.22)):
        path.lineTo(x + dx * size, y + dy * size)
    path.closeSubpath()
    painter.fillPath(path, QColor(color))


def draw_nail(painter, design, layer, stage):
    path = nail_path()
    base = QColor(design.color if layer in ("color", "art") else "#9a686e")
    gradient = QLinearGradient(8, 15, 90, 141)
    gradient.setColorAt(0, base.lighter(159))
    gradient.setColorAt(.55, base)
    gradient.setColorAt(1, base.darker(145))
    painter.fillPath(path, gradient)
    painter.strokePath(path, QPen(QColor("#ffe2ef"), 1.8))
    painter.save()
    painter.setClipPath(path)
    painter.setPen(QPen(QColor(255, 241, 250, 82), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawLine(QPointF(26, 36), QPointF(28, 66))
    if layer == "base":
        star(painter, 54, 62, 17, "#fff2ec")
    if layer == "art":
        if design.name == "Daisy Dreams":
            for i in range(min(5, stage)):
                angle = i * 2 * pi / 5 - pi / 2
                center = QPointF(52 + 16 * cos(angle), 65 + 16 * sin(angle))
                painter.setPen(QPen(QColor("#fff1a6"), 2) if stage == i + 1 else Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#fff9f6"))
                painter.drawEllipse(center, 8, 8)
            if stage >= 6:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#ffe280"))
                painter.drawEllipse(QPointF(52, 65), 7, 7)
        elif design.name == "Classic French":
            tip = QPainterPath(QPointF(10, 37))
            tip.quadTo(25, 53, 50, 51)
            if stage >= 2:
                tip.quadTo(75, 53, 90, 37)
            if stage >= 3:
                tip.lineTo(90, 0)
                tip.lineTo(10, 0)
                tip.closeSubpath()
                painter.fillPath(tip, QColor("#fff8f1"))
            else:
                painter.strokePath(tip, QPen(QColor("#fff8f1"), 4))
        else:
            star(painter, 52, 47, 20, "#f4f1ff")
            if stage >= 2:
                star(painter, 38, 100, 13, "#e1d9ff")
            if stage >= 3:
                for x, y in ((30, 43), (68, 73), (57, 106), (39, 74)):
                    star(painter, x, y, 4, "#f8e9ff")
    painter.restore()
    accent = QColor("#e0d2ff")
    painter.setPen(QPen(accent, 2.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    if layer == "clean":
        painter.save()
        painter.translate(64, 83)
        painter.rotate(-22)
        painter.setBrush(QColor("#fff3ec"))
        painter.drawRoundedRect(-13, -26, 24, 38, 6, 6)
        painter.restore()
    elif layer == "trim":
        painter.setPen(QPen(accent, 2.3, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(12, 42), QPointF(88, 42))
    elif layer == "file":
        guide = QPainterPath(QPointF(8, 55))
        guide.cubicTo(8, -12, 92, -12, 92, 55)
        painter.strokePath(guide, QPen(accent, 2.5, Qt.PenStyle.DashLine))
    elif layer == "soak":
        water = QPainterPath(QPointF(3, 92))
        water.quadTo(25, 76, 50, 92)
        water.quadTo(75, 108, 97, 92)
        painter.drawPath(water)
    elif layer == "dry":
        star(painter, 76, 34, 12, "#fff3ec")
        star(painter, 22, 105, 9, "#fff3ec")


class NailArt(QWidget):
    def __init__(self, design, layer="art", stage=99, trio=False):
        super().__init__()
        self.design, self.layer, self.stage, self.trio = design, layer, stage, trio
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        if self.trio:
            scale = min(self.width() / 302, self.height() / 182)
            painter.scale(scale, scale)
            for offset, angle, size in ((-85, -12, .82), (85, 12, .82), (0, 0, 1)):
                painter.save()
                painter.translate(offset, 5)
                painter.rotate(angle)
                painter.scale(size, size)
                painter.translate(-50, -78)
                draw_nail(painter, self.design, self.layer, self.stage)
                painter.restore()
        else:
            scale = min(self.width() / 112, self.height() / 167)
            painter.scale(scale, scale)
            painter.translate(-50, -78)
            draw_nail(painter, self.design, self.layer, self.stage)


class Sparkles(QWidget):
    def __init__(self):
        super().__init__()
        self.phase = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for x, y, radius in ((.15, .26, 16), (.85, .32, 21), (.25, .72, 9), (.77, .72, 12)):
            scale = .75 + .25 * sin(self.phase + x * 5)
            star(painter, self.width() * x, self.height() * y, radius * scale, "#f9c9e5")
