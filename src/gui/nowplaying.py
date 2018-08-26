from PyQt5 import QtCore, QtGui
from PyQt5.QtCore import QRect, QSize, pyqtSignal, QRectF, Qt, QPoint, QTimer
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QImage, QColor, QPen, QBrush
from PyQt5.QtWidgets import (QWidget, QLabel, QPushButton, QApplication,
                             QSizePolicy, QHBoxLayout, QSlider, QGridLayout,
                             QGraphicsDropShadowEffect, QGraphicsPixmapItem,
                             QGraphicsScene, QListWidget, QListWidgetItem, QStyledItemDelegate,
                             QMenu, QDialog, QLineEdit, QVBoxLayout, QFrame, QMessageBox,
                             QMainWindow, QProxyStyle, QStyle, QDockWidget,
                             QStackedWidget)

from src.queues import ScrollingIconPage
from src.gui.icons import IconManager
from src.globals import GV
from src.song import Song
import sys
import os
import logging

logger = logging.getLogger('debug')


class BaseListWidget(QListWidget):
    unchecked_color = QBrush(QColor(0, 0, 0, 0))
    checked_color = QBrush(QColor('#304FFE'))
    hover_color = QBrush(QColor(48, 79, 254, 150))

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.hovered = None
        self.currently_selected = None

        self.setMouseTracking(True)
        self.setUniformItemSizes(True)

    def mouseMoveEvent(self, event):
        self._change_hovered(event)

    def _change_hovered(self, event):
        item = self.itemAt(event.pos())
        if item == self.hovered:
            return

        self.change_hovered(item)

    def change_hovered(self, item):
        def set_hovered(_item):
            self.hovered = _item
            if _item.checkState() == Qt.Checked:
                return
            _item.setBackground(self.hover_color)

        if item is None:
            if self.hovered is None:
                return

            color = self.checked_color if self.hovered.checkState() == Qt.Checked else self.unchecked_color
            self.hovered.setBackground(color)
            self.hovered = None
            return

        if self.hovered is None:
            set_hovered(item)
        else:
            color = self.checked_color if self.hovered.checkState() == Qt.Checked else self.unchecked_color
            self.hovered.setBackground(color)
            set_hovered(item)

    def wheelEvent(self, event):
        super().wheelEvent(event)
        self._change_hovered(event)

    def leaveEvent(self, event):
        self.change_hovered(None)

    def change_selected(self, item):
        if self.currently_selected is not None:
            self.currently_selected.setBackground(self.unchecked_color)
            self.currently_selected.setCheckState(Qt.Unchecked)

        self.currently_selected = item
        if item is not None:
            item.setCheckState(Qt.Checked)
            item.setBackground(self.checked_color)

    def on_item_clicked(self, item):
        if item is not None:
            if item.checkState() == Qt.Unchecked:
                self.change_selected(item)
            else:
                if self.currently_selected is item:
                    return

                item.setCheckState(Qt.Unchecked)
                item.setBackground(self.unchecked_color)

                if self.currently_selected is not None:
                    self.currently_selected.setCheckState(Qt.Unchecked)
                    self.currently_selected = None


class SongQueue(BaseListWidget):
    def __init__(self, player, session, settings, database, parent=None):
        super().__init__(parent)
        self.settings_manager = settings
        self.db = database
        self.player = player
        self.session = session

        self.last_doubleclicked = None
        self.setItemDelegate(SongItemDelegate(parent=self, paint_icons=self.settings.value('paint_icons', True)))
        self.itemClicked.connect(self.on_item_clicked)
        self.itemDoubleClicked.connect(self.on_doubleclick)
        self.verticalScrollBar().valueChanged.connect(self.on_scroll)

        self.current_queue = self.settings.value('queue', GV.MainQueue)

        self.song_timer = QTimer()
        self.song_timer.setSingleShot(True)
        self.song_timer.timeout.connect(self.change_song)

        self.icon_timer = QTimer()
        self.icon_timer.setSingleShot(True)
        self.icon_timer.timeout.connect(self.load_current_index)

        self.pages = ScrollingIconPage(None)
        self.icon_manager = IconManager(None)

    @property
    def settings(self):
        return self.settings_manager.get_settings_instance()

    def on_doubleclick(self, item):
        if item is not None:
            self.song_timer.stop()
            self.last_doubleclicked = item
            self.song_timer.start(200)

    def load_songs(self, queue):
        _queue = []
        for item in queue:
            _queue.append(self.add_list_item(item))

        return _queue

    def load_current_queue(self):
        self.clear_items()
        q = self.session.queues[self.current_queue]
        for song in q:
            self.add_list_item(song)

        self.load_current_index()
        self.player.update_queue(self.current_queue)

    def load_current_index(self):
        try:
            page_index = int(self.verticalScrollBar().value() / self.pages.part_length)
            self.pages.load_pages(page_index)
        except Exception as e:
            print('dawdad', e)

    def clear_current_queue(self):
        # TODO Might not be used
        self.clear_items()
        current = self.current_queue
        queue = self.session.queues.get(current, [])
        queue.clear()

    def clear_items(self):
        self.currently_selected = None
        self.pages.clear_pages()
        self.pages.set_collection(None)
        while self.count() > 0:
            self.takeItem(0)

    def scroll_to_selected(self):
        current = self.player.current
        if current is not None:
            self.scroll_to_item(current)

    def scroll_to_item(self, item):
        self.scrollToItem(item)
        self.pages.load_pages(item.song.index)

    def item_list(self, list_type=list):
        q = list_type()
        for i in range(self.count()):
            q.append(self.item(i))

        return q

    def load_last_queue(self):
        self.change_selected(None)
        if self.current_queue == GV.MainQueue:
            self.current_queue = GV.SecondaryQueue
            index = self.session.secondary_index
            self.session.main_index = self.session.index
        else:
            self.current_queue = GV.MainQueue
            index = self.session.main_index
            self.session.secondary_index = self.session.index

        self.session.index = index

        self.settings.setValue('queue', self.current_queue)
        self.load_current_queue()
        self.player.skip_to(index, self.item(index))
        self.pages.load_pages(index)
        self.scrollToItem(self.item(index))

    def shuffle_queue(self):
        self.session.database.shuffle_queue()

        self.clear_items()
        queue = self.session.queues[self.current_queue]
        queue = sorted(queue, key=lambda i: i.sort_order)
        self.session.queues[self.current_queue] = queue
        self.load_current_queue()

    def change_song(self):
        if self.last_doubleclicked is not None:
            settings = self.settings
            index = self.indexFromItem(self.last_doubleclicked).row()
            self.player.skip_to(index, self.last_doubleclicked)
            self.session.index = index
            settings.setValue('index', index)

            if self.current_queue == GV.MainQueue:
                self.session.main_index = index
                settings.setValue('main_index', index)
            elif self.current_queue == GV.SecondaryQueue:
                self.session.secondary_index = index
                settings.setValue('secondary_index', index)

    def addItem(self, item, *args):
        super().addItem(item, *args)
        if self.currently_selected is None:
            self.currently_selected = item
            item.setBackground(self.checked_color)
            item.setCheckState(Qt.Checked)

    def _add_item(self, item, is_selected=False):
        song = item.song
        name, author = song.get_name_and_author()

        item.setText('{}\r\n{}'.format(name, author))
        item.setData(Qt.UserRole, song.duration_formatted)

        if is_selected:
            item.setCheckState(Qt.Checked)
            item.setBackground(self.checked_color)
            self.change_selected(item)

        song.index = self.count()
        self.addItem(item)
        self.pages.append_item(item)
        return item

    def on_scroll(self, value):
        self.icon_timer.stop()
        self.icon_timer.start(250)

    def add_from_item(self, item, is_selected=False):
        return self._add_item(item, is_selected)

    def add_list_item(self, song, is_selected=False):
        item = SongItem(song, self.icon_manager)
        return self._add_item(item, is_selected)


class SongItem(QListWidgetItem):
    Background = QBrush(QColor(167, 218, 245, 0))
    Size = QSize(150, 80)

    def __init__(self, song, icon_manager, icon_displayed=False, *args):
        super().__init__(*args)
        self.setFlags(self.flags() | Qt.ItemIsUserCheckable)
        self.setCheckState(Qt.Unchecked)
        self.setBackground(self.Background)
        self.setSizeHint(self.Size)

        self.song = song
        self.icon_manager = icon_manager
        self.img = None
        self.icon_displayed = icon_displayed

        self.song.on_cover_art_changed = self.update_icon
        self.song.after_download = self.update_info
        self.loaded = False

    def _load_icon(self):
        img = self.song.cover_art
        if img is None or self.img == img:
            return

        self._unload_icon(self.img)
        self.img = img
        icon = self.icon_manager.load_icon(self.img, size=QSize(80, 80))
        self.setIcon(icon)

    def load_icon(self):
        self._load_icon()
        self.loaded = True

    def _unload_icon(self, img):
        self.setIcon(QIcon())
        self.icon_manager.unload_icon(img)

    def unload_icon(self):
        self.loaded = False
        self._unload_icon(self.img)
        self.img = None

    def update_icon(self, song=None):
        if self.loaded:
            self._load_icon()

    def update_info(self, song=None):
        self.setText('{}\r\n{}'.format(*self.song.get_name_and_author()))
        self.setData(Qt.UserRole, self.song.duration_formatted)
        self.update_icon()


class SongItemDelegate(QStyledItemDelegate):
    def __init__(self, paint_icons=True, padding=5, parent=None):
        super().__init__(parent)
        self.padding = padding
        self.paint_icons = paint_icons

    @staticmethod
    def _check_width(fontmetrics, s, max_width):
        text_width = fontmetrics.width(s)
        average = fontmetrics.averageCharWidth()
        characters = int(max_width / average)
        offset = 0

        while text_width > max_width:
            if offset > 3:
                break

            s = s[:characters - offset]
            text_len = len(s)

            if text_len > 3:
                s = s[:-3] + '...'

            text_width = fontmetrics.width(s)
            offset += 1

        return s

    def paint(self, painter, option, index):
        painter.setPen(QPen(Qt.NoPen))
        bg_brush = index.data(Qt.BackgroundRole)
        painter.setBrush(bg_brush)
        painter.drawRect(option.rect)

        width = min(option.rect.width(), painter.device().width())
        height = option.rect.height()
        x = option.rect.x()
        y = option.rect.y()
        title, author = index.data().split('\r\n', maxsplit=1)

        pixmap_width = 0
        if self.paint_icons:
            icon = index.data(Qt.DecorationRole)
            if icon is not None:
                painter.setPen(QPen(Qt.NoPen))
                pixmap = icon.pixmap(QSize(height, height))
                pixmap_y = y + (height - pixmap.height())/2
                painter.drawPixmap(QPoint(x, pixmap_y), pixmap)
                pixmap_width = pixmap.width()

        used_width = x + pixmap_width + self.padding

        duration = str(index.data(Qt.UserRole))
        dur_width = painter.fontMetrics().width(duration) + self.padding*3
        usable_width = width - pixmap_width - dur_width

        title = self._check_width(painter.fontMetrics(), title, usable_width)
        author = self._check_width(painter.fontMetrics(), author, usable_width)

        font_height = painter.fontMetrics().height()
        painter.setPen(QPen(Qt.white))
        painter.drawText(QRectF(used_width, y, usable_width, height), Qt.AlignLeft, title)

        painter.setPen(QPen(Qt.gray))
        painter.drawText(QRectF(used_width, y + font_height + self.padding, usable_width - self.padding, height - self.padding - font_height),
                         Qt.AlignLeft, author)

        painter.drawText(QRectF(width - dur_width, y, dur_width - self.padding, height),
                         Qt.AlignRight, duration)


class CoverArt(QLabel):
    def __init__(self, *args):
        super().__init__(*args)
        self.pixmap = QPixmap(GV.DefaultCoverArt)

    def paintEvent(self, event):
        try:
            size = self.size()
            painter = QPainter(self)
            point = QPoint(0, 0)
            scaledPix = self.pixmap.scaled(size, QtCore.Qt.KeepAspectRatio,
                                           QtCore.Qt.SmoothTransformation)

            point.setX((size.width() - scaledPix.width())/2)
            point.setY((size.height() - scaledPix.height())/2)
            painter.drawPixmap(point, scaledPix)

        except Exception as e:
            print('cover art exc %s' % e)

    def change_pixmap(self, img, update=True):
        if img is None:
            img = self.default_image

        self.pixmap = QPixmap(img)

        if update:
            self.update()

    def change_pixmap_from_data(self, data, update=True):
        self.pixmap = QPixmap()
        self.pixmap.loadFromData(data)

        if update:
            self.update()

    def heightForWidth(self, width):
        return width


class SongInfoBox(QFrame):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.setLineWidth(0)
        self.setMidLineWidth(1)
        self.setFrameShape(QFrame.Box | QFrame.Plain)

        self.setMinimumHeight(10)
        self.setMaximumHeight(150)

        size_policy = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.setSizePolicy(size_policy)

        layout = QGridLayout()
        layout.setSpacing(3)

        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        self.artist = QLabel()
        self.artist.setWordWrap(True)
        self.artist.setAlignment(Qt.AlignBottom | Qt.AlignLeft)

        self.duration = QLabel()
        self.duration.setAlignment(Qt.AlignBottom | Qt.AlignRight)

        layout.addWidget(self.title, 0, 0, 1, 2)
        layout.addWidget(self.artist, 1, 0, 1, 2)
        layout.addWidget(self.duration, 1, 2, 1, 1)
        self.setLayout(layout)

    def update_info(self, song):
        title, author = song.get_name_and_author()
        self.title.setText(title)
        self.artist.setText(author)
        self.duration.setText(song.duration_formatted)


class NowPlaying(QWidget):
    song_changed = pyqtSignal(object, bool, int, bool)

    def __init__(self, settings_manager, database, player, session,
                 media_controls, *args, **kwargs):

        super().__init__(*args, **kwargs)

        self.settings_manager = settings_manager
        self.db = database
        self.player = player
        self.player.on_next = self.song_changed
        self.session = session

        self.media_controls = media_controls
        self.media_controls.set_rating = self.change_rating

        self.song_info = SongInfoBox()

        self.cover_art = CoverArt()
        self.cover_art.setBaseSize(400, 400)
        self.cover_art.setMinimumSize(100, 100)
        size_policy = QSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.MinimumExpanding)
        size_policy.setHorizontalStretch(6)
        self.cover_art.setSizePolicy(size_policy)
        self.cover_art.setScaledContents(True)

        song_list = SongQueue(self.player, self.session, self.settings_manager, self.db)
        size_policy = QSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Preferred)
        size_policy.setHorizontalStretch(3)
        size_policy.setVerticalStretch(10)
        song_list.setMinimumWidth(350)
        song_list.setSizePolicy(size_policy)
        song_list.setIconSize(QSize(75, 75))
        song_list.setResizeMode(song_list.Adjust)
        song_list.setSpacing(3)
        self.song_queue = song_list

        index = self.settings.value('index', 0)
        queue_mode = self.settings.value('queue_mode', self.player.IN_ORDER)
        queue = self.db.get_queue()

        songs = []
        for idx, item in enumerate(queue):
            songs.append((Song(item, self.session.downloader, idx)))

        self.song_queue.current_queue = self.settings.value('queue', GV.MainQueue)
        self.session.queues[self.song_queue.current_queue] = songs
        self.song_queue.load_current_queue()
        self.player.update_queue(self.song_queue.current_queue, index)

        try:
            item = self.song_queue.item(index)
        except IndexError:
            pass
        else:
            if item is not None:
                self.song_queue.scroll_to_item(item)
                self.song_queue.change_selected(item)
                logger.debug('Scrolled to index %s' % index)
                if item.song.cover_art is not None:
                    self.cover_art.change_pixmap(item.song.cover_art)

                self.media_controls.song_changed(item.song)
                self.song_info.update_info(item.song)
                self.player.skip_to(index, item)

        self.song_box = QVBoxLayout()
        self.song_box.addWidget(self.song_queue)
        self.song_box.addWidget(self.song_info)

        layout = QGridLayout()
        layout.setGeometry(QRect())
        horizontal = QHBoxLayout()

        horizontal.addWidget(self.cover_art)
        horizontal.addLayout(self.song_box, 4)

        layout.addLayout(horizontal, 0, 0, 1, 4)
        self.setLayout(layout)
        self.song_changed.connect(self.on_change)

    @property
    def settings(self):
        return self.settings_manager.get_settings_instance()

    def change_rating(self, score):
        index = self.session.index
        if index is None:
            return

        item1 = self.player.current
        item2 = self.song_queue.item(index)
        if item1 is not None and item1 is item2:
            item1.song.rating = score

    def on_change(self, song, in_list=False, index=0, force_repaint=True):
        logger.debug('start')
        song.set_cover_art()
        item = None

        if in_list:
            item = self.song_queue.item(index)
            if item is not None and item != 0:
                encoding = sys.stdout.encoding or 'utf-8'
                print(index, song.index, song.title.encode('utf-8').decode(encoding, errors='replace'))

                self.song_queue.change_selected(item)

                item.setData(Qt.UserRole, song.duration_formatted)
                item.setText('{}\r\n{}'.format(*song.get_name_and_author()))

                self.session.index = index
                self.settings.setValue('index', index)

        self.media_controls.song_changed(song)
        self.song_info.update_info(song)

        if song.cover_art is None:
            logger.debug('cover_art is None')
            img = song.info.get('thumbnail', None)

            if img is None:
                img = os.path.join(os.getcwd(), 'icons', 'download.png')
                logger.debug('Changing cover_art to %s' % img)
                self.cover_art.change_pixmap(img, force_repaint)
            else:
                logger.debug('Changing cover_art to %s' % img)
                self.cover_art.change_pixmap_from_data(self.dl_img(img), force_repaint)

        else:
            img = song.cover_art
            logger.debug('Changing cover_art to %s' % img)
            self.cover_art.change_pixmap(img, force_repaint)

        self.session.cover_art = img

        if force_repaint:
            logger.debug('Updating window')
            self.update()

        # scrollToItem has to be called after self.update() or the program crashes
        if self.settings.value('scroll_on_change', True) and item is not None:
            self.song_queue.scrollToItem(item)

        logger.debug('Items added and cover art changed')
