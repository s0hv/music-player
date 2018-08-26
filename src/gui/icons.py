import os

from PyQt5.QtGui import QPixmap, QIcon
from PyQt5.QtCore import Qt


class Icons:
    IconDir = os.path.join(os.getcwd(), 'icons')
    FullStar = None
    HalfStar = None
    EmptyStar = None
    Menu = None

    Paused = 'icons/play_white.png'
    Next = 'icons/next_white.png'
    Previous = 'icons/previous_white.png'
    Playing = 'icons/pause_white.png'

    @classmethod
    def create_icons(cls):
        Icons.FullStar = QPixmap(os.path.join(Icons.IconDir, 'star_white.png'))
        Icons.HalfStar = QPixmap(os.path.join(Icons.IconDir, 'star_half_white.png'))
        Icons.EmptyStar = QPixmap(os.path.join(Icons.IconDir, 'star_border.png'))
        Icons.Menu = QIcon(os.path.join(Icons.IconDir, 'menu.png'))


class IconManager:
    def __init__(self, icons, default_size=(80, 80)):
        self.icons = icons or {}
        self.default_size = default_size

    def load_icon(self, img, size=None):
        icon = self.icons.get(img)
        if icon is None:
            pixmap = QPixmap(img)
            if size is None:
                size = self.default_size

            pixmap = pixmap.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            icon = QIcon(pixmap)
            self.icons[img] = (icon, 1)
            return icon

        else:
            self.icons[img] = (icon[0], icon[1] + 1)
            return icon[0]

    def unload_icon(self, img):
        icon = self.icons.get(img)
        if icon is None:
            return print('icon not loaded')

        else:
            icon, count = icon
            count -= 1

            if count <= 0:
                del self.icons[img]
                del icon

            else:
                self.icons[img] = (icon, count)
