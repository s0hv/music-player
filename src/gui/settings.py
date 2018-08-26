from PyQt5.QtWidgets import (QWidget, QListWidget, QListView, QStackedLayout,
                             QTabWidget, QStackedWidget, QPushButton, QVBoxLayout,
                             QDialog, QHBoxLayout, QCheckBox, QListWidgetItem,
                             QShortcut, QMessageBox)

from PyQt5.QtCore import Qt, QItemSelectionModel
from PyQt5.QtGui import QKeySequence


class SettingsWindow(QDialog):
    def __init__(self, settings, session, *args):
        super().__init__(*args)
        self.settings_manager = settings
        self.session = session

        self.categories = QListWidget(self)
        #self.categories.setViewMode(QListView.IconMode)
        self.categories.setSpacing(10)
        self.setting_pages = QStackedWidget(self)
        self.setting_pages.setMinimumWidth(100)
        self.categories.setFixedWidth(50)
        self.setting_pages.addWidget(TestPage())
        self.setting_pages.addWidget(LibrarySettingsPage(settings, session))

        self.main_layout = QHBoxLayout()
        self.main_layout.addWidget(self.categories)
        self.main_layout.addSpacing(5)
        self.main_layout.addWidget(self.setting_pages, stretch=5)

        self.setLayout(self.main_layout)

        self.test = QListWidgetItem(self.categories)
        self.test.setText('Test')
        self.test.setTextAlignment(Qt.AlignHCenter)
        self.test.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)

        self.library = QListWidgetItem(self.categories)
        self.library.setText('Library')
        self.library.setTextAlignment(Qt.AlignHCenter)
        self.library.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)

        self.categories.currentItemChanged.connect(self.change_page)

    def change_page(self, current, previous):
        if not current:
            current = previous

        self.setting_pages.setCurrentIndex(self.categories.row(current))

    @property
    def settings(self):
        return self.settings_manager.get_settings_instance()


class TestPage(QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.download = QCheckBox()
        self.download.setText('Download songs')

        main_layout = QHBoxLayout()
        main_layout.addWidget(self.download, alignment=Qt.AlignTop)
        self.setLayout(main_layout)


class LibrarySettingsPage(QWidget):
    def __init__(self, settings_manager, session, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.settings_manager = settings_manager
        self.session = session

        self.folder_list = QListWidget()
        self.session.scanned_dirs = ['11', '22', '33']
        for f in self.session.scanned_dirs:
            item = QListWidgetItem()
            item.setText(f)
            self.folder_list.addItem(item)
        self.folder_list.addItem('test/test')

        self.add_folder = QPushButton()
        self.add_folder.setText('Add folder to library')

        self.web_list = QListWidget()
        self.session.updated_playlists = ['1', '2', '3']
        for p in self.session.updated_playlists:
            self.web_list.addItem(p)
        self.web_list.addItem('test.com')

        self.add_web_playlist = QPushButton()
        self.add_web_playlist.setText('Add web playlist')

        shortcut = QShortcut(self)
        shortcut.setKey(Qt.Key_Delete)
        shortcut.activated.connect(self.delete_item)

        main_layout = QVBoxLayout()
        main_layout.addWidget(self.folder_list, stretch=2)
        main_layout.addWidget(self.add_folder)
        main_layout.addWidget(self.web_list, stretch=2)
        main_layout.addWidget(self.add_web_playlist)

        self.setLayout(main_layout)

    def delete_item(self):
        item = None
        if self.web_list.hasFocus():
            item = self.web_list.currentItem()
            print('web_list', item)
        elif self.folder_list.hasFocus():
            item = self.folder_list.currentItem()
            print('folder_list', item)

        if item is None:
            return

        d = QMessageBox.warning(self, 'Update library', 'Do you want to remove %s '
                                'and all its contents from the library' % item.text(),
                                QMessageBox.Yes | QMessageBox.No)

        if d == QMessageBox.Yes:
            if self.web_list.hasFocus():
                self.web_list.takeItem(self.web_list.row(item))
                self.web_list.selectionModel().clear()

            elif self.folder_list.hasFocus():
                self.folder_list.takeItem(self.folder_list.row(item))
                self.folder_list.selectionModel().clear()

    @property
    def settings(self):
        return self.settings_manager.get_settings_instance()