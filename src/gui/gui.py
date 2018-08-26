import sys

import qdarkstyle
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (QWidget, QApplication,
                             QMainWindow, QDockWidget,
                             QStackedWidget, QMenuBar)

from src.gui.icons import Icons
from src.gui.media_controls import MediaControls
from src.gui.nowplaying import NowPlaying
from src.gui.style import ProxyStyle
from src.gui.settings import SettingsWindow
from src.metadata import MetadataUpdater

class MainWindow(QMainWindow):
    def __init__(self, session, player, database, settings_manager, *args,
                 **kwargs):

        super().__init__(*args, **kwargs)
        self.settings_manager = settings_manager
        self.session = session
        self.db = database
        self.player = player

        self.media_controls = MediaControls(self.player, self.session)
        self.tabs = QStackedWidget()

        self.now_playing = NowPlaying(settings_manager, database, player, session,
                                      self.media_controls)

        self.metadata = MetadataUpdater(self.session)
        self.metadata.start()
        self.metadata.add_to_update(self.session.queues[0], forced=True)

        self.tabs.insertWidget(-1, self.now_playing)
        self.setCentralWidget(self.tabs)

        self.bottom_dock = QDockWidget(self)
        self.bottom_dock.setTitleBarWidget(QWidget())
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
        action = menu.addAction('Settings')
        action.triggered.connect(lambda x: SettingsWindow(self.settings_manager, self.session).exec_())

        self.restore_position_settings()

    # http://stackoverflow.com/a/8736705/6046713
    def save_position_settings(self):
        settings = self.settings_manager.get_unique_settings_inst()
        settings.beginGroup('mainwindow')

        settings.setValue('geometry', self.saveGeometry())
        settings.setValue('savestate', self.saveState())
        settings.setValue('maximized', self.isMaximized())
        if not self.isMaximized():
            settings.setValue('pos', self.pos())
            settings.setValue('size', self.size())

        settings.endGroup()

    def restore_position_settings(self):
        settings = self.settings_manager.get_unique_settings_inst()
        settings.beginGroup('mainwindow')

        self.restoreGeometry(settings.value('geometry', self.saveGeometry()))
        self.restoreState(settings.value('savestate', self.saveState()))
        self.move(settings.value('pos', self.pos()))
        self.resize(settings.value('size', self.size()))
        maximized = settings.value('maximized', self.isMaximized())
        if maximized is True or maximized == 'true':
            self.showMaximized()

        settings.endGroup()

    def closeEvent(self, event):
        self.save_position_settings()


class GUI:
    def __init__(self, app, organization, settings_manager, session, database,
                 player, keybinds, style=None):

        self.app = QApplication(sys.argv)
        self.app.setApplicationName(app)
        self.app.setOrganizationName(organization)
        self.app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())

        if style is None:
            style = ProxyStyle()
        self.app.setStyle(style)

        Icons.create_icons()

        self.settings_manager = settings_manager
        self.settings.setValue('download', True)
        self.session = session
        self.db = database
        self.player = player
        self.keybinds = keybinds
        self.main_window = self.main_window = MainWindow(self.session, self.player, self.db,
                                                         self.settings_manager)

    def show(self):
        self.main_window.show()
        self.player.start()
        self.session.start()

        timer = QTimer()
        # Message pump has to be on the same thread as Qt or keyboard presses might
        # cause random crashes.
        timer.timeout.connect(self.keybinds.pump_messages)
        timer.setInterval(10)
        timer.start()

        self.app.exec_()

    @property
    def settings(self):
        return self.settings_manager.get_unique_settings_inst()
