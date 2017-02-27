#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import threading
from collections import deque
from math import ceil
from random import shuffle

import pythoncom
import qdarkstyle
import requests
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

from src import settings as _settings
from src.database import DBHandler, DBSong, attribute_names
from src.downloader import DownloaderPool
from src.globals import GV
from src.gui.table_view import SQLAlchemyTableModel, Column, SongTable
from src.keybinds import KeyBinds, KeyBind, KeyCodes
from src.metadata import MetadataUpdater
from src.player import GUIPlayer
from src.session import SessionManager
from src.song import Song
from src.utils import parse_duration, at_exit, run_on_exit, run_funcs_on_exit


class Icons:
    IconDir = os.path.join(os.getcwd(), 'icons')
    if 'app' in locals():
        FullStar = QPixmap(os.path.join(IconDir, 'star_white.png'))
        HalfStar = QPixmap(os.path.join(IconDir, 'star_half_white.png'))
        EmptyStar = QPixmap(os.path.join(IconDir, 'star_border.png'))
        Menu = QIcon(os.path.join(IconDir, 'menu.png'))
    else:
        FullStar = None
        HalfStar = None
        EmptyStar = None
        Menu = None

    @classmethod
    def create_icons(cls):
        Icons.FullStar = QPixmap(os.path.join(Icons.IconDir, 'star_white.png'))
        Icons.HalfStar = QPixmap(os.path.join(Icons.IconDir, 'star_half_white.png'))
        Icons.EmptyStar = QPixmap(os.path.join(Icons.IconDir, 'star_border.png'))
        Icons.Menu = QIcon(os.path.join(Icons.IconDir, 'menu.png'))


class DurationSlider(QSlider):
    def __init__(self, on_pos_change):
        super().__init__()
        self.setSingleStep(0)
        self.setPageStep(0)
        self.dragging = False
        self.on_change = on_pos_change

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


class MediaButton(QPushButton):
    hovered = pyqtSignal('QEnterEvent')
    left = pyqtSignal('QEvent')
    mouse_hovered = False

    def __init__(self, icon, on_click, size, *args):
        super().__init__(*args)
        self.setIconSize(QSize(*[int(x * 0.85) for x in size]))
        self.set_icon(icon)
        self.setStyleSheet(self.stylesheet())
        self.setMask(QtGui.QRegion(QtCore.QRect(0, 0, *[int(x*0.95) for x in size]), QtGui.QRegion.Ellipse))
        self.setFixedSize(*size)
        self.src = icon
        self.mouse_hovered = False

        self.on_click = lambda x: on_click(self)
        self.clicked.connect(self.on_click)
        self.setMouseTracking(True)
        self.hovered.connect(lambda x: self.mouse_hover(x))
        self.left.connect(lambda x: self.mouse_leave(x))

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
    def __init__(self, player_):
        super().__init__()
        self.player = player_
        self.player.duration_fn = self.update_duration
        self.player.on_start = self.player_start
        self.seek_lock = threading.Lock()
        self.playing = False
        self.current = None

        size_policy = QSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        size = (35, 35)

        play = MediaButton('icons/play_white.png', self.play_pause, size)
        self.play = play

        next_button = MediaButton('icons/next_white.png', self.next, size)

        previous = MediaButton('icons/previous_white.png', self.previous, size)

        play.setSizePolicy(size_policy)
        next_button.setSizePolicy(size_policy)
        previous.setSizePolicy(size_policy)

        self.addWidget(previous)
        self.addWidget(play)
        self.addWidget(next_button)

        mid_layout = QGridLayout()
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
        slider.setStyleSheet(self.stylesheet)

        dur = QLabel()
        self.total_dur = '00:00/00:00'
        dur.setText(self.total_dur)
        dur.setBaseSize(QtCore.QSize(70, 30))
        dur.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        mid_layout.addWidget(self.title, 0, 0, Qt.AlignLeft)
        mid_layout.addWidget(self.rating, 0, 1, Qt.AlignRight)
        mid_layout.addWidget(dur, 0, 2, Qt.AlignRight)
        mid_layout.addWidget(slider, 1, 0, 1, 3)

        w = QWidget()
        w.setLayout(mid_layout)
        self.addWidget(w)

        self.slider = slider
        self.dur = dur

    def play_pause(self, button):
        self.playing = self.player.pause()
        self.player.unpaused.set()
        self.set_play_icon(button)

    def set_play_icon(self, button):
        if self.playing is None or self.playing is False:
            button.set_icon('icons/play_white.png')
            self.playing = False

        else:
            self.playing = True
            button.set_icon('icons/pause_white.png', False)

    def change_rating(self, score):
        if self.current is not None:
            self.current.rating = score

    def next(self, button):
        self.player.play_next_song()
        self.playing = False
        self.set_play_icon(self.play)

    def previous(self, button):
        if self.player.current is None:
            index = self.player.index - 1
        else:
            index = self.player.current.song.index - 1

        self.player.skip_to(index)
        self.playing = False
        self.set_play_icon(self.play)

    def song_changed(self, song):
        self.current = song
        self.total_dur = song.duration_formatted
        self.dur.setText('00:00/{}'.format(self.total_dur))
        name, author = song.get_name_and_author()
        self.title.setText('{} - {}'.format(author, name))
        self.rating.set_value(song.rating)

    def player_start(self, player_):
        self.playing = True
        self.set_play_icon(self.play)

    def update_duration(self, stream_player):
        iteration = stream_player.duration
        total = self.player.current.song.duration
        if total is None:
            total = 1

        self.dur.setText(parse_duration(iteration) + '/' + self.total_dur)
        if not self.slider.dragging:
            self.slider.setSliderPosition(int(self.slider.maximum()*(iteration/total)))

    def seek(self, slider):
        if self.player.not_playing.is_set():
            return

        if self.seek_lock.acquire(False):
            t = threading.Thread(target=self._seek, args=(slider, self.seek_lock,))
            t.start()

    def _seek(self, slider, lock):
        try:
            if slider.value() == slider.maximum():
                self.player.play_next_song()
                return

            total = self.player.current.song.duration
            seconds = slider.value()/slider.maximum()*total
            self.player.stream_player.seek(seconds, self.player.current.song.ffmpeg)
        finally:
            lock.release()

    @property
    def stylesheet(self):
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


class CoverArt(QLabel):
    def __init__(self, default_image='download.png'):
        super().__init__()
        self.pixmap = QtGui.QPixmap(default_image)
        self.default_image = default_image

    def paintEvent(self, event):
        size = self.size()
        painter = QPainter(self)
        point = QPoint(0, 0)
        scaledPix = self.pixmap.scaled(size, QtCore.Qt.KeepAspectRatio,
                                       QtCore.Qt.SmoothTransformation)

        point.setX((size.width() - scaledPix.width())/2)
        point.setY((size.height() - scaledPix.height())/2)
        painter.drawPixmap(point, scaledPix)

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


class PlaylistDialog(QDialog):
    def __init__(self, after_info, *args, extract_flat=True):
        super().__init__(*args)
        self.setMinimumSize(200, 25)
        self.text_edit = QLineEdit(self)
        self.after_info = after_info
        self.text_edit.returnPressed.connect(self.get_playlist)
        self.ready = True
        self.extract_flat = extract_flat

    def get_playlist(self, *args):
        if self.ready is False:
            return

        self.ready = False
        text = self.text_edit.text()
        if text is None or len(text) < 2:
            return

        dl = session.downloader
        future = dl.get_info(text, flat=self.extract_flat)
        future.add_done_callback(self.after_info)
        session.temp_futures.append(future)


class ADialog(QDialog):
    def __init__(self, after_info, *args, extract_flat=True):
        super().__init__(*args)
        self.setMinimumSize(200, 25)
        self.text_edit = QLineEdit(self)
        self.after_info = after_info
        self.text_edit.returnPressed.connect(self.get_playlist)
        self.ready = True
        self.extract_flat = extract_flat

    def get_playlist(self, *args):
        if self.ready is False:
            return

        self.ready = False
        text = self.text_edit.text()

        dl = session.downloader
        future = dl.get_info(text, flat=self.extract_flat)
        future.add_done_callback(self.after_info)
        session.temp_futures.append(future)


class SearchDialog(QDialog):
    def __init__(self, *args):
        super().__init__(*args)
        self.setMinimumSize(200, 385)

        self.list = SearchListWidget()
        self.list.setIconSize(QSize(75, 75))
        size_policy = QSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Preferred)
        size_policy.setHorizontalStretch(3)
        self.list.setSizePolicy(size_policy)

        self.text_edit = QLineEdit()
        self.text_edit.returnPressed.connect(self.on_enter)
        self.text_edit.setBaseSize(150, 25)
        self.text_edit.setMaximumHeight(25)
        size_policy = QSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Preferred)
        self.text_edit.setSizePolicy(size_policy)

        self.box = QVBoxLayout(self)
        self.box.addWidget(self.text_edit)
        self.box.addWidget(self.list)

        self.list.setItemDelegate(SongItemDelegate(True, parent=self))
        self.list.setUniformItemSizes(True)
        self.list.setMinimumSize(150, 250)

        self.downloader = DownloaderPool()

    def on_enter(self, *args):
        text = self.text_edit.text()
        if text is None or len(text) == 0:
            return

        search = 'ytsearch5:%s' % text
        future = self.downloader.get_info(search)
        future.add_done_callback(self.on_ready)

    def on_ready(self, future):
        info = future.result()
        if info is None:
            return

        self.list.hovered = None
        self.list.clear()
        for entry in info['entries']:
            self.list.addItem(SearchItem(entry))


class SearchItem(QListWidgetItem):
    def __init__(self, info, *args):
        super().__init__(*args)
        self.setSizeHint(QSize(150, 75))
        self.info = info
        self.setText('{}\r\n{}'.format(info.get('title', 'Untitled'), info.get('uploader', 'Unknown')))
        self.setData(Qt.UserRole, parse_duration(info.get('duration', 0)))
        self.setBackground(QBrush(QColor(167, 218, 245, 0)))

        if 'thumbnail' in info:
            url = info.get('thumbnail')
            r = requests.get(url, stream=True)
            pixmap = QPixmap()
            pixmap.loadFromData(r.content)
            self.setIcon(QIcon(pixmap.scaled(QSize(80, 80), Qt.KeepAspectRatio,
                                             Qt.SmoothTransformation)))


class BaseListWidget(QListWidget):
    unchecked_color = QBrush(QColor(0, 0, 0, 0))
    checked_color = QBrush(QColor('#304FFE'))
    hover_color = QBrush(QColor(48, 79, 254, 150))

    def __init__(self, *args):
        super().__init__(*args)
        self.hovered = None
        self.currently_selected = None

        self.setMouseTracking(True)
        self.setUniformItemSizes(True)

    def _change_hovered_from_event(self, event):
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
        self._change_hovered_from_event(event)

    def mouseMoveEvent(self, event):
        self._change_hovered_from_event(event)

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


class SearchListWidget(BaseListWidget):
    def __init__(self, *args):
        super().__init__(*args)
        self.itemClicked.connect(self.on_item_clicked)
        self.itemDoubleClicked.connect(self.on_doubleclick)

    @staticmethod
    def on_doubleclick(item):
        player.play_from_search(item.info)


class SongList(BaseListWidget):
    def __init__(self, player_, session_, settings_, icons, cover_art):
        super().__init__()
        self.last_doubleclicked = None
        self.player = player_
        self.settings = settings_
        self.icons = icons
        self.cover_art = cover_art
        self.setItemDelegate(SongItemDelegate(parent=self, paint_icons=self.settings.value('paint_icons', True)))
        self.itemClicked.connect(self.on_item_clicked)
        self.itemDoubleClicked.connect(self.on_doubleclick)
        self.session = session_

        self.timer = QTimer()
        self.icon_timer = QTimer()
        self.icon_timer.setSingleShot(True)
        self.icon_timer.timeout.connect(self.load_current_index)

        self.item_pages = deque()
        self.item_page = 0
        self.page_length = 20
        self.loaded_pages = deque()

        self.current_queue = self.settings.value('queue', GV.MainQueue)

        self.verticalScrollBar().valueChanged.connect(self.on_scroll)

        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.change_song)

    def scroll_to_selected(self):
        current = self.player.current
        if current is not None:
            self.scrollToItem(current)
            self.load_items_by_index(current.song.index)

    def shuffle_queue(self):
        items = self.session.queues.get(self.current_queue, deque())
        shuffle(items)
        self.clear_items()
        db_queue = deque()
        for idx, item in enumerate(items):
            item.song.index = idx
            db_queue.append(item.song.song)
            self.add_from_item(item)

        db.set_queue(db_queue)

    def load_last_queue(self):
        self.change_selected(None)
        if self.current_queue == GV.MainQueue:
            q = self.session.queues.get(GV.SecondaryQueue, deque())
            self.current_queue = GV.SecondaryQueue
            index = self.session.secondary_index
            self.session.main_index = self.session.index
        else:
            q = self.session.queues.get(GV.MainQueue, deque())
            self.current_queue = GV.MainQueue
            index = self.session.main_index
            self.session.secondary_index = self.session.index

        self.session.index = index

        settings.setValue('queue', self.current_queue)
        self.clear_items()

        for item in q:
            self.add_from_item(item)

        self.player.update_queue(self.current_queue, index)
        self.player.skip_to(index, self.item(index))

        self.load_items_by_index(index)
        self.scrollToItem(self.item(index))

    def load_current_queue(self):
        self.reset_item_page()
        q = self.session.queues.get(self.current_queue, deque())
        for item in q:
            self.addItem(item)
            self.add_to_item_page(item)

        self.load_current_index()
        self.player.update_queue(self.current_queue)

    def clear_items(self):
        self.currently_selected = None
        self.reset_item_page()
        while self.count() > 0:
            self.takeItem(0)

    def load_current_index(self):
        self.load_items_by_index(self.verticalScrollBar().value())

    def on_scroll(self, value):
        self.icon_timer.stop()
        self.icon_timer.start(250)

    def contextMenuEvent(self, event):
        item = self.itemAt(event.pos())

        trim_action = None
        cover_art_action = None
        search = None
        menu = QMenu(self)

        if item is not None:
            trim_action = menu.addAction('Trim cover art borders')
            cover_art_action = menu.addAction('Update cover art')
            search = menu.addAction('Search')

        playlist = menu.addAction('Play playlist')
        switch_action = menu.addAction('switch q')
        vid_q = menu.addAction('Add to secondary queue')
        shuffle_action = menu.addAction('Shuffle queue')
        clear_action = menu.addAction('Clear this queue')

        action = menu.exec_(self.mapToGlobal(event.pos()))
        if action == trim_action:
            try:
                item.song.trim_cover_art()
                item.setIcon(QIcon(item.song.cover_art))
                main_window.update()
            except Exception as e:
                print(e)

        elif action == cover_art_action:
            item.song.set_cover_art(forced=True)

        elif action == search:
            dialog = SearchDialog(self.parent())
            dialog.exec_()

        elif action == playlist:
            dia = PlaylistDialog(self._playlist_from_future, self.parent())
            dia.exec_()

        elif action == switch_action:
            self.load_last_queue()

        elif action == vid_q:
            d = ADialog(self.append_to_queue_future, self.parent(), extract_flat=False)
            d.exec_()

        elif action == shuffle_action:
            self.shuffle_queue()

        elif action == clear_action:
            message_box = QMessageBox()
            message_box.setIcon(QMessageBox.Warning)
            message_box.setWindowTitle('Confirm list clearing')
            message_box.setInformativeText('Are you sure you want to clear this list')
            message_box.addButton('Cancel', QMessageBox.RejectRole)
            message_box.addButton('Yes', QMessageBox.AcceptRole)

            if message_box.exec_() == QMessageBox.Accepted:
                self.clear_current_queue()

    def clear_current_queue(self):
        self.clear_items()
        current = self.current_queue
        queue = self.session.queues.get(current, deque())
        queue.clear()

        if current == GV.SecondaryQueue:
            db.clear_second_queue()

        if current == GV.MarkedQueue:
            pass

        if current == GV.MainQueue:
            db.clear_main_queue()

    def append_to_queue_future(self, future):
        info = future.result()
        if info is None:
            return

        if 'entries' not in info:
            return

        songs = deque()
        q = self.session.queues.get(GV.SecondaryQueue, deque())
        l = len(q)
        for idx, entry in enumerate(info['entries']):
                song = db.get_temp_song(entry.get('title', 'Untitled'),
                                        entry.get('webpage_url'), item_type='link')

                db.add_to_second_queue(song)
                item = Song(song, db, self.session.downloader, index=idx + l)
                songs.append(item)

        if self.current_queue == GV.SecondaryQueue:
            items = self.load_songs(songs)
            for item in items:
                q.append(item)

            self.load_items_by_page(self.item_page)
        else:
            for song in songs:
                item = SongItem(song)
                q.append(item)

        print('done')
        metadata_updater.add_to_update(q)

    def _playlist_from_future(self, future):
        info = future.result()
        if info is None:
            return

        if info['extractor_key'].lower() != 'youtubeplaylist':
            return

        if 'entries' not in info:
            return

        songs = deque()
        for idx, entry in enumerate(info['entries']):
                song = db.get_temp_song(entry.get('title', 'Untitled'),
                                        'https://www.youtube.com/watch?v=%s' % entry.get('url'),
                                        item_type='link')

                db.add_to_second_queue(song)
                item = Song(song, db, self.session.downloader, index=idx)
                print(item.name)
                songs.append(item)

        self.clear_items()
        items = self.load_songs(songs)
        q = self.session.queues.get(GV.SecondaryQueue, deque())
        q.clear()
        for item in items:
            q.append(item)

        self.player.update_queue(GV.SecondaryQueue)
        idx = self.session.secondary_index
        self.player.skip_to(idx)
        self.session.index = idx
        self.settings.setValue('index', idx)
        metadata_updater.add_to_update(self.session.queues.get(GV.SecondaryQueue, deque()))

    def load_songs(self, queue):
        _queue = deque()
        for item in queue:
            _queue.append(self.add_list_item(item))

        return _queue

    def leaveEvent(self, event):
        self.change_hovered(None)

    def addItem(self, item, *args):
        super().addItem(item, *args)
        if self.currently_selected is None:
            self.currently_selected = item
            item.setBackground(self.checked_color)
            item.setCheckState(Qt.Checked)

    def change_song(self):
        if self.last_doubleclicked is not None:
            index = self.indexFromItem(self.last_doubleclicked).row()
            self.player.skip_to(index, self.last_doubleclicked)
            self.session.index = index
            self.settings.setValue('index', index)

            if self.current_queue == GV.MainQueue:
                self.session.main_index = index
                self.settings.setValue('main_index', index)
            elif self.current_queue == GV.SecondaryQueue:
                self.session.secondary_index = index
                self.settings.setValue('secondary_index', index)

    def on_doubleclick(self, item):
        if item is not None:
            self.timer.stop()
            self.last_doubleclicked = item
            self.timer.start(200)

    def reset_item_page(self):
        self.item_page = 0
        self.unload_pages()
        self.item_pages.clear()
        self.load_current_index()

    def get_item_page(self):
        if len(self.item_pages) == 0:
            self.item_page = 0
            self.item_pages.append([])
            return self.item_pages[self.item_page]
        else:
            return self.item_pages[self.item_page]

    def add_item_page(self):
        page = []
        self.item_pages.append(page)
        return page

    def add_to_item_page(self, item):
        page = self.get_item_page()
        if len(page) >= self.page_length:
            page = self.add_item_page()
            self.item_page += 1

        page.append(item)

    def load_items_by_page(self, page_index):
        try:
            page = self.item_pages[page_index]
        except IndexError:
            return

        self.loaded_pages.append((page, page_index))
        for item in page:
            item.update_info()
            item.load_icon()

    @staticmethod
    def unload_page(page):
        for item in page:
            item.unload_icon()

    def unload_pages(self, index_whitelist=None):
        if index_whitelist is None:
            index_whitelist = []

        indexes = []
        for idx, p_i in enumerate(self.loaded_pages):
            page, index = p_i
            if index in index_whitelist:
                continue

            indexes.append(idx)
            self.unload_page(page)

        indexes.reverse()
        for idx in indexes:
            del self.loaded_pages[idx]

    def load_items_by_index(self, index):
        page = int(index/self.page_length)
        down = page - 1
        up = page + 1

        try:
            self.load_items_by_page(page)
            if len(self.item_pages) > up:
                self.load_items_by_page(up)

            if down >= 0:
                self.load_items_by_page(down)
        except Exception as e:
            print(e)

        try:
            self.unload_pages([page, up, down])
        except Exception as e:
            print(e)

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
        self.add_to_item_page(item)
        return item

    def add_from_item(self, item, is_selected=False):
        return self._add_item(item, is_selected)

    def add_list_item(self, song, is_selected=False):
        item = SongItem(song)
        return self._add_item(item, is_selected)


class SongItem(QListWidgetItem):
    def __init__(self, song, icon_displayed=False, *args):
        super().__init__(*args)
        self.setFlags(self.flags() | Qt.ItemIsUserCheckable)
        self.setCheckState(Qt.Unchecked)
        self.setBackground(QBrush(QColor(167, 218, 245, 0)))
        self.setSizeHint(QSize(150, 75))
        self.song = song
        self.img = None
        self.icon_displayed = icon_displayed
        self.song.on_cover_art_changed = self.update_icon
        self.song.after_download = self.update_info
        self.loaded = False

    def unload_icon(self):
        self.setIcon(QIcon())
        self.del_from_icons()
        self.img = None
        self.loaded = False

    def del_from_icons(self):
        icons = getattr(session, 'icons', {})
        if self.img in icons:
            uses = icons[self.img][1]
            if uses <= 1:
                del icons[self.img]
            else:
                icons[self.img] = (icons[self.img][0], uses - 1)

    def load_icon(self):
        self._load_icon()
        self.loaded = True

    def _load_icon(self):
        img = self.song.cover_art
        if img is None or self.img == img:
            return

        self.img = img
        icons = getattr(session, 'icons', {})
        if img in icons:
            icon, uses = icons[img]
            icons[img] = (icon, uses + 1)
        else:
            pixmap = QPixmap(img)
            icon = QIcon(pixmap.scaled(QSize(75, 75), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            icons[img] = (icon, 1)

        self.del_from_icons()
        self.setIcon(icon)

    def update_icon(self, song=None):
        if not self.loaded:
            return

        self.load_icon()

    def unload_info(self):
        self.setText('')
        self.setData(Qt.UserRole, None)

    def update_info(self, song=None):
        self.setText('{}\r\n{}'.format(*self.song.get_name_and_author()))
        self.setData(Qt.UserRole, self.song.duration_formatted)
        self.update_icon()


class SongItemDelegate(QStyledItemDelegate):
    def __init__(self, paint_icons=True, padding=5, parent=0):
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


class RatingBar(QWidget):
    def __init__(self, *args, on_change=None):
        super().__init__(*args)

        size_policy = QSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setSizePolicy(size_policy)
        self.setMouseTracking(True)
        self._value = 0
        self.maximum = 10
        self.padding = 1
        self.setFixedWidth((20 + self.padding)*5)
        self.setFixedHeight(20)
        self.on_change = on_change

        self.full_star = Icons.FullStar
        self.half_star = Icons.HalfStar
        self.empty_star = Icons.EmptyStar
        self.scale_stars()

    def scale_stars(self):
        star_width = int((self.width() - self.padding*5)/5)
        self.full_star = Icons.FullStar.scaledToWidth(star_width, Qt.SmoothTransformation)
        self.half_star = Icons.HalfStar.scaledToWidth(star_width, Qt.SmoothTransformation)
        self.empty_star = Icons.EmptyStar.scaledToWidth(star_width, Qt.SmoothTransformation)

    @property
    def value(self):
        return self._value

    def set_value(self, value, update=True):
        if isinstance(value, int):
            self._value = value
            if update:
                self.update()

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


class SongInfoBox(QFrame):
    def __init__(self, *args, set_rating=None, **kwargs):
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


class QueueWidget(QWidget):
    song_changed = pyqtSignal(object, bool, int, bool, bool)

    def __init__(self, settings_, db_, player_, keybinds_, session_, media_controls, *args):
        super().__init__(*args)

        self.db = db_
        self.player = player_
        self.player.on_next = self.song_changed
        self.kb = keybinds_
        self.session = session_
        self.settings = settings_

        logger.debug('Creating widgets')
        self.media_controls = media_controls
        self.media_controls.set_rating = self.change_rating
        logger.debug('Media controls created')

        layout = QGridLayout()
        layout.setGeometry(QtCore.QRect())

        logger.debug('Cover art created')

        h = QHBoxLayout()
        cover_art = CoverArt()
        size_policy = QSizePolicy()
        size_policy.setHorizontalStretch(6)
        cover_art.setSizePolicy(size_policy)
        self.song_info = SongInfoBox(set_rating=self.change_rating)

        icons = {}
        song_list = SongList(player_, session_, settings_, icons, cover_art)
        size_policy = QSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Preferred)
        size_policy.setHorizontalStretch(3)
        size_policy.setVerticalStretch(10)

        song_list.setMinimumWidth(350)
        song_list.setSizePolicy(size_policy)
        song_list.setIconSize(QSize(75, 75))
        song_list.setResizeMode(song_list.Adjust)
        song_list.setSpacing(3)
        self.list = song_list
        logger.debug('Songlist added. now adding songs.')

        queue = deque()
        index = self.settings.value('index', 0)
        logger.debug(vars(session))
        db_queue = getattr(self.db, self.player.queues.get(self.player.queue_mode, 'history'))
        if callable(db_queue):
            db_queue = db_queue()

        for idx, item in enumerate(db_queue):
            song = Song(item, self.db, self.session.downloader, index=idx)
            item = SongItem(song)
            item.update_info()
            queue.append(item)

        queues = self.session.queues
        queues[GV.MainQueue] = queue

        setattr(self.session, 'icons', icons)

        secondary_q = deque()
        for idx, item in enumerate(self.db.secondary_queue()):
            song = Song(item, self.db, session.downloader, index=index)
            item = SongItem(song)
            item.update_info()
            secondary_q.append(item)

        queues[GV.SecondaryQueue] = secondary_q
        self.list.current_queue = settings.value('queue', GV.MainQueue)
        logger.debug('Songs added')
        self.list.load_current_queue()
        player.update_queue(self.list.current_queue)

        song_list = secondary_q if self.list.current_queue == GV.SecondaryQueue else queue
        try:
            item = song_list[index]
        except IndexError:
            pass
        else:
            self.list.scrollToItem(item)
            self.list.load_items_by_index(index)
            self.list.change_selected(item)
            logger.debug('Scrolled to index %s' % index)
            if item.song.cover_art is not None:
                cover_art.change_pixmap(item.song.cover_art)

            self.media_controls.song_changed(item.song)
            self.song_info.update_info(item.song)
            self.player.skip_to(index, item)

        cover_art.setBaseSize(400, 400)
        cover_art.setMinimumSize(100, 100)

        size_policy = QSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.MinimumExpanding)
        size_policy.setHorizontalStretch(4)
        cover_art.setSizePolicy(size_policy)
        cover_art.setScaledContents(True)

        self.cover_art = cover_art

        self.song_box = QVBoxLayout()

        self.song_box.addWidget(self.list)
        self.song_box.addWidget(self.song_info)

        h.addWidget(self.cover_art)
        h.addLayout(self.song_box, 4)

        layout.addLayout(h, 0, 0, 1, 4)
        self.setLayout(layout)
        logger.debug('Layout complete')
        self.song_changed.connect(self.on_change)

    def change_rating(self, score):
        index = getattr(self.session, 'index', None)
        if index is None:
            return

        item1 = self.player.current
        item2 = self.list.item(index)
        if item1 is not None and item1 is item2:
            item1.song.rating = score

    @staticmethod
    def dl_img(url):
        return requests.get(url).content

    def on_change(self, song, in_list=False, index=0, force_repaint=True, add=False):
        song.set_cover_art()
        setattr(self.session, 'cover_art', song.cover_art)

        item = None
        if in_list:
            item = self.list.item(index)
            if item is not None and item != 0:
                encoding = sys.stdout.encoding or 'utf-8'
                print(index, song.index, song.name.encode('utf-8').decode(encoding, errors='replace'))

                self.list.change_selected(item)

                item.setData(Qt.UserRole, song.duration_formatted)
                item.setText('{}\r\n{}'.format(*song.get_name_and_author()))

                setattr(self.session, 'index', index)
                self.settings.setValue('index', index)

        elif add:
            item = self.list.add_list_item(song, is_selected=True)

        self.media_controls.song_changed(song)
        self.song_info.update_info(song)
        logger.debug('changing cover_art in main window')

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

        if item is not None:
            logger.debug('Setting icon to %s' % img)
            item.setIcon(QIcon(img))
            logger.debug('icon set')

        if force_repaint:
            logger.debug('Updating window')
            self.update()

        # scrollToItem has to be called after self.update() or the program crashes
        if settings.value('scroll_on_change', True) and item is not None:
            self.list.scrollToItem(item)

        logger.debug('Items added and cover art changed')


class ProxyStyle(QProxyStyle):
    def __init__(self, *args):
        super().__init__(*args)

    def pixelMetric(self, metric, option=None, widget=None):
        if metric == QStyle.PM_SmallIconSize:
            return 25
        else:
            return super().pixelMetric(metric, option, widget)


class MainWindow(QMainWindow):
    def __init__(self, settings_, db_, player_, keybinds_, session_, *args):
        super().__init__(*args)

        self.db = db_
        self.player = player_
        self.kb = keybinds_
        self.session = session_
        self.settings = settings_
        self.media_controls = MediaControls(self.player)
        self.main_stack = QStackedWidget()

        self.queue_widget = QueueWidget(settings_, db_, player_, keybinds_, session_, self.media_controls)
        self.queue_widget_index = self.main_stack.insertWidget(-1, self.queue_widget)

        columns = [Column(key, getattr(DBSong, key), key, **GV.TableColumns[key])
                   for key in attribute_names(DBSong) if key in GV.TableColumns.keys()]
        model = SQLAlchemyTableModel(db_, columns, self.db.items(DBSong))
        self.table_view = SongTable(model)
        self.table_view_index = self.main_stack.insertWidget(-1, self.table_view)

        self.setCentralWidget(self.main_stack)

        self.bottom_dock = QDockWidget(self)
        self.bottom_dock.setTitleBarWidget(QWidget())  # Removes title bar

        widget = QWidget()
        widget.setLayout(self.media_controls)
        h = self.media_controls.minimumSize().height()
        self.bottom_dock.setMaximumHeight(h)
        self.bottom_dock.setMinimumHeight(h)

        self.bottom_dock.setWidget(widget)
        self.bottom_dock.setAllowedAreas(Qt.BottomDockWidgetArea | Qt.TopDockWidgetArea)
        self.bottom_dock.setFeatures(QDockWidget.DockWidgetMovable)
        self.bottom_dock.show()
        self.addDockWidget(Qt.BottomDockWidgetArea, self.bottom_dock)

        menu = self.menuBar().addMenu(Icons.Menu, 'Preferences')
        action = menu.addAction('test')
        action.triggered.connect(self.change_stack)

        self.restore_position_settings()

    def change_stack(self, checked=False):
        if self.main_stack.currentIndex() == self.table_view_index:
            self.main_stack.setCurrentIndex(self.queue_widget_index)
        else:
            self.main_stack.setCurrentIndex(self.table_view_index)

    # http://stackoverflow.com/a/8736705/6046713
    def save_position_settings(self):
        self.settings.beginGroup('mainwindow')

        self.settings.setValue('geometry', self.saveGeometry())
        self.settings.setValue('savestate', self.saveState())
        self.settings.setValue('maximized', self.isMaximized())
        if not self.isMaximized():
            self.settings.setValue('pos', self.pos())
            self.settings.setValue('size', self.size())

        self.settings.endGroup()

    def restore_position_settings(self):
        self.settings.beginGroup('mainwindow')

        self.restoreGeometry(self.settings.value('geometry', self.saveGeometry()))
        self.restoreState(self.settings.value('savestate', self.saveState()))
        self.move(self.settings.value('pos', self.pos()))
        self.resize(self.settings.value('size', self.size()))
        maximized = self.settings.value('maximized', self.isMaximized())
        if maximized is True or maximized == 'true':
            self.showMaximized()

        self.settings.endGroup()

    def closeEvent(self, event):
        self.save_position_settings()


import logging
logger = logging.getLogger('debug')
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(filename='debug.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)


if __name__ == "__main__":

    app = QApplication(sys.argv)
    app.setApplicationName('Music player')
    app.setOrganizationName('s0hvaperuna')
    app.setStyle(ProxyStyle())

    Icons.create_icons()

    settings = _settings.settings
    session = SessionManager()

    metadata_updater = MetadataUpdater(session)
    metadata_updater.start()
    db = DBHandler('yttest', session)

    player = GUIPlayer(None, None, None, session, GUIPlayer.SHUFFLED, db, 0.2, daemon=True)
    keybinds = KeyBinds(global_binds=True)

    main_window = MainWindow(settings, db, player, keybinds, session)

    def close_event(lock=None):
        player.exit_player(lock)
        main_window.close()

    keybinds.add_keybind(KeyBind(ord('3'), player.play_next_song,
                                 'Skip song', modifiers=(KeyCodes.id_from_key('ctrl'),)))
    keybinds.add_keybind(KeyBind(KeyCodes.id_from_key('subtract'), player.change_volume,
                                 'Volume down'))
    keybinds.add_keybind(KeyBind(KeyCodes.id_from_key('add'), lambda: player.change_volume(True),
                                 'Volume up'))
    keybinds.add_keybind(KeyBind(KeyCodes.id_from_key('numpad 5'), close_event,
                                 'Quit player', threaded=True,
                                 modifiers=(KeyCodes.id_from_key('ctrl'),)))

    player.start()
    session.start()

    app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())
    at_exit(run_funcs_on_exit, [(session.save_session, (), {}), (db.shutdown, (), {})])
    main_window.show()
    db.delete_history()

    timer = QTimer()
    # Message pump has to be on the same thread as Qt or keyboard presses might
    # cause random crashes.
    timer.timeout.connect(keybinds.pump_messages)
    timer.setInterval(10)
    timer.start()

    app.exec_()

    metadata_updater.stop()
    player.exit_player()
    keybinds.stop()
    session.stop()
    session.wait_for_stop(10)

    # All of the preparations for shutting down must be completed before this command
    # The last command is DBHandler.shutdown
    run_on_exit(db.shutdown)
