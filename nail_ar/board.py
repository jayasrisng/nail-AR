from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget
from raven_framework.helpers.font_utils import create_font

class SudokuBoard(QWidget):
    """Paint all 81 cells as one board; Raven buttons handle individual editable cells."""

    def __init__(self, game, check_errors):
        super().__init__()
        self.game = game
        self.errors = game.errors if check_errors else set()
        self.setAccessibleName("Full 9 by 9 Sudoku board")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width() / 9, self.height() / 9
        painter.fillRect(self.rect(), QColor("#171321"))
        for index, digit in enumerate(self.game.cells):
            row, col = divmod(index, 9)
            cell = QRectF(col * width, row * height, width, height)
            if index == self.game.selected:
                painter.fillRect(cell, QColor("#58354e"))
            if digit:
                font = create_font("inter", max(1, round(height * .57)),
                                   "bold" if self.game.givens[index] else "normal")
                font.setPixelSize(max(1, round(height * .57)))
                painter.setFont(font)
                painter.setPen(QColor("#ff9caa" if index in self.errors else
                                      "#fff3ec" if self.game.givens[index] else "#ffc3dd"))
                painter.drawText(cell, Qt.AlignmentFlag.AlignCenter, str(digit))
        for i in range(10):
            main = i % 3 == 0
            painter.setPen(QPen(QColor("#d9c9ff" if main else "#63536f"), 2.5 if main else 1))
            x, y = min(i * width, self.width() - 1), min(i * height, self.height() - 1)
            painter.drawLine(QPointF(x, 0), QPointF(x, self.height()))
            painter.drawLine(QPointF(0, y), QPointF(self.width(), y))
