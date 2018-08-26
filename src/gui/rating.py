from math import ceil

from PyQt5 import QtCore
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPainter
from PyQt5.QtWidgets import (QWidget, QSizePolicy)

from src.globals import GV
from src.gui.icons import Icons


class RatingBar(QWidget):
    def __init__(self, *args, on_change=None, **kwargs):
        super().__init__(*args, **kwargs)

        size_policy = QSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setSizePolicy(size_policy)
        self.setMouseTracking(True)
        self._value = 0
        self.maximum = 10
        self._padding = 1

        x, y = GV.StarSize
        self.setFixedWidth((x + self._padding)*5)
        self.setFixedHeight(y)

        self.on_change = on_change

        self.full_star = Icons.FullStar
        self.half_star = Icons.HalfStar
        self.empty_star = Icons.EmptyStar
        self.scale_stars()

    def scale_stars(self):
        star_width = int((self.width() - self.padding*5)/5)
        self.full_star = self.full_star.scaledToWidth(star_width, Qt.SmoothTransformation)
        self.half_star = self.half_star.scaledToWidth(star_width, Qt.SmoothTransformation)
        self.empty_star = self.empty_star.scaledToWidth(star_width, Qt.SmoothTransformation)

    @property
    def value(self):
        return self._value

    @property
    def padding(self):
        return self._padding

    def set_value(self, value, update=True):
        if isinstance(value, int):
            self._value = value
            if update:
                self.update()

        else:
            raise TypeError('Rating value must be int')

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if event.buttons() == Qt.LeftButton:
            self.set_value(int(ceil(event.x() / self.width() * self.maximum)))

    def mousePressEvent(self, event):
        if event.button() == 1:
            self.set_value(int(ceil(event.x() / self.width() * self.maximum)))

    def mouseReleaseEvent(self, event):
        if event.button() == 1 and callable(self.on_change):
            self.on_change(self.value)

    def paintEvent(self, event):
        rect = event.rect()

        x = rect.x()
        y = rect.y()
        star_width = int((self.width() - self.padding*5)/5)
        pos = 0

        painter = QPainter(self)
        full_stars, half_stars = divmod(self.value, 2)
        empty_stars = int((self.maximum - self.value)/2)

        def draw_pixmap(pixmap):
            nonlocal pos
            target = QtCore.QPointF(x + pos, y)
            painter.drawPixmap(target, pixmap)
            pos += star_width + self.padding

        while full_stars > 0:
            draw_pixmap(self.full_star)
            full_stars -= 1

        while half_stars > 0:
            draw_pixmap(self.half_star)
            half_stars -= 1

        while empty_stars > 0:
            draw_pixmap(self.empty_star)
            empty_stars -= 1
