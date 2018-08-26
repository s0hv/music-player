from threading import Lock, Thread

from PyQt5 import QtCore, QtGui
from PyQt5.QtCore import QSize, pyqtSignal, QRectF, Qt, QPoint, QTimer
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QImage, QColor, QPen, QBrush
from PyQt5.QtWidgets import (QWidget, QLabel, QPushButton, QApplication,
                             QSizePolicy, QHBoxLayout, QSlider, QGridLayout,
                             QGraphicsDropShadowEffect, QGraphicsPixmapItem,
                             QGraphicsScene, QListWidget, QListWidgetItem, QStyledItemDelegate,
                             QMenu, QDialog, QLineEdit, QVBoxLayout, QFrame, QMessageBox,
                             QMainWindow, QProxyStyle, QStyle, QDockWidget,
                             QStackedWidget)


from src.gui.icons import Icons
from src.gui.rating import RatingBar
from src.utils import parse_duration


def apply_effect_to_pixmap(src: QPixmap, effect, extent=0, size: QSize=None):
    if src.isNull():
        return src

    scene = QGraphicsScene()
    item = QGraphicsPixmapItem()
    item.setPixmap(src)
    item.setGraphicsEffect(effect)
    scene.addItem(item)

    size = src.size() if size is None else size
    res = QImage(size + QSize(extent * 2, extent * 2), QImage.Format_ARGB32)
    res.fill(Qt.transparent)
    ptr = QPainter(res)
    scene.render(ptr, QRectF(), QRectF(-extent, -extent, size.width() + extent * 2, size.height() + extent*2))
    return res


class DurationSlider(QSlider):
    def __init__(self, on_pos_change, *args):
        super().__init__(*args)
        self.setSingleStep(0)
        self.setPageStep(0)
        self.dragging = False
        self.on_change = on_pos_change

        self.setStyleSheet(self.stylesheet())

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == 1:
            self.setSliderPosition(int(event.x() / self.width() * self.maximum()))

    def mouseMoveEvent(self, event):
        if int(event.buttons()) == 1:
            self.dragging = True
            self.setSliderPosition(int(event.x() / self.width() * self.maximum()))

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == 1:
            self.dragging = False
            self.on_change(self)

    @staticmethod
    def stylesheet():
        # Inspiration from
        # http://thesmithfam.org/blog/2010/03/10/fancy-qslider-stylesheet/
        return """
            QSlider{
            background-color: transparent;
            border-style: outset;
            border-radius: 10px;
            }

            QSlider::groove:horizontal {
            border: 1px solid #bbb;
            background: white;
            height: 1px;
            margin-left: -10px; margin-right: -10px;
            }

            QSlider::groove:horizontal:hover {
            height: 5px;
            }

            QSlider::sub-page:horizontal {
            background: #304FFE;
            height: 3px;
            border-radius: 9px;
            }

            QSlider::handle:horizontal {
            background: transparent;
            border: none;
            }"""


class Button(QPushButton):
    hovered = pyqtSignal('QEnterEvent')
    left = pyqtSignal('QEvent')
    mouse_hovered = False

    def __init__(self, icon, on_click, size, *args):
        super().__init__(*args)

        self.src = icon
        self.on_click = lambda x: on_click(self)
        self.clicked.connect(self.on_click)

        self.setIconSize(QSize(*map(lambda i: i*0.90, size)))
        self.set_icon(icon)
        self.setMouseTracking(True)
        self.hovered.connect(lambda x: self.mouse_hover(x))
        self.left.connect(lambda x: self.mouse_leave(x))
        self.setStyleSheet(self.stylesheet())

    def enterEvent(self, event):
        self.hovered.emit(event)

    def leaveEvent(self, event):
        self.left.emit(event)

    def mouse_hover(self, event):
        self.mouse_hovered = True
        self.set_icon(self.icon(), True)

    def mouse_leave(self, event):
        self.mouse_hovered = False
        self.set_icon(self.icon(), False)

    @staticmethod
    def set_glow(src):
        effect = QGraphicsDropShadowEffect()
        effect.setBlurRadius(50)
        effect.setOffset(0, 0)
        effect.setEnabled(True)
        effect.setColor(QColor('#0000CC'))
        image = apply_effect_to_pixmap(QPixmap(src), effect)
        icon = QIcon(QPixmap().fromImage(image))
        return icon

    def set_icon(self, icon, effect=None):
        if effect is None:
            effect = self.mouse_hovered

        if isinstance(icon, str):
            self.src = icon
            icon = self.set_glow(icon) if effect else QIcon(icon)
        else:
            icon = self.set_glow(self.src) if effect else QIcon(self.src)

        self.setIcon(icon)
        self.setIconSize(self.iconSize())
        self.update()

    @staticmethod
    def stylesheet():
        return """
            QPushButton:pressed {
                background: transparent;
                border: none;
            }
            QPushButton {
                background: transparent;
                border: none;
            }
        
            QPushButton:disabled {
                background: transparent;
            }"""


class MediaControls(QHBoxLayout):
    def __init__(self, player, session ,*args):
        super().__init__(*args)

        self.player = player
        self.session = session
        self.player.duration_fn = self.update_duration
        self.player.on_start = self.player_start
        self.seek_lock = Lock()
        self.playing = False
        self.current = None

        size_policy = QSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        size = (35, 35)

        self.play = Button(Icons.Paused, self.play_pause, size)
        self.next = Button(Icons.Next, self.next, size)
        self.previous = Button(Icons.Previous, self.previous, size)

        self.play.setSizePolicy(size_policy)
        self.next.setSizePolicy(size_policy)
        self.previous.setSizePolicy(size_policy)

        self.addWidget(self.previous)
        self.addWidget(self.play)
        self.addWidget(self.next)

        self.title = QLabel()
        self.title.setStyleSheet('QLabel { font-weight: bold; }')
        self.rating = RatingBar(on_change=self.change_rating)

        slider = DurationSlider(self.seek)
        slider.setMinimumHeight(20)
        slider.setMinimumWidth(100)
        slider.setMaximum(2000)
        slider.setBaseSize(QtCore.QSize(800, 20))
        slider.setSizePolicy(QSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Fixed))
        slider.setOrientation(QtCore.Qt.Horizontal)
        self.slider = slider

        duration = QLabel()
        self.total_dur = '00:00/00:00'
        duration.setText(self.total_dur)
        duration.setBaseSize(QtCore.QSize(70, 30))
        duration.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.duration = duration

        mid_layout = QGridLayout()
        mid_layout.addWidget(self.title, 0, 0, Qt.AlignLeft)
        mid_layout.addWidget(self.rating, 0, 1, Qt.AlignRight)
        mid_layout.addWidget(self.duration, 0, 2, Qt.AlignRight)
        mid_layout.addWidget(self.slider, 1, 0, 1, 3)

        w = QWidget()
        w.setLayout(mid_layout)
        self.addWidget(w)

    def play_pause(self, button):
        self.playing = self.player.pause()
        self.player.unpaused.set()
        self.set_play_icon(button)

    def set_play_icon(self, button):
        if self.playing is None or self.playing is False:
            button.set_icon(Icons.Paused)
            self.playing = False

        else:
            button.set_icon(Icons.Playing) # , False)
            self.playing = True

    def next(self, button):
        self.player.play_next_song()
        self.player.unpaused.set()
        self.set_play_icon(self.play)

    def previous(self, button):
        index = self.session.index - 1

        if index < 0:
            return

        self.player.skip_to(index)
        self.playing = False
        self.set_play_icon(self.play)

    def change_rating(self, rating):
        if self.player.current is not None:
            try:
                rating = int(rating)
            except (ValueError, TypeError):
                return

            self.player.current.rating = rating

    def song_changed(self, song):
        self.total_dur = song.duration_formatted
        self.duration.setText('00:00/{}'.format(self.total_dur))
        title, author = song.get_name_and_author()
        self.title.setText('{} - {}'.format(author, title))
        self.rating.set_value(song.rating)

    def player_start(self, player):
        self.playing = True
        self.set_play_icon(self.play)

    def update_duration(self, stream_player):
        iteration = stream_player.duration
        total = self.player.current.duration
        if total is None:
            total = 1

        self.duration.setText(parse_duration(iteration) + '/' + self.total_dur)
        if not self.slider.dragging:
            self.slider.setSliderPosition(int(self.slider.maximum()*(iteration/total)))

    def seek(self, slider):
        if self.player.not_playing.is_set():
            return

        if self.seek_lock.acquire(False):
            t = Thread(target=self._seek, args=(slider, self.seek_lock))
            t.start()

    def _seek(self, slider, lock):
        try:
            print(slider.value(), slider.maximum())
            if slider.value() == slider.maximum():
                return self.player.play_next_song()

            total = self.player.current.duration
            seconds = slider.value()/slider.maximum()*total
            print(total, seconds)
            self.player.stream_player.seek(seconds, self.player.current.ffmpeg)
        except Exception as e:
            print('Seeking exception. %s' % e)
        finally:
            lock.release()
