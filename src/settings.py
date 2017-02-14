from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import QSettings


class Settings(QSettings):
    def __init__(self, *args):
        super().__init__(*args)


settings = Settings('s0hvaperuna', 'Music player')


def set_settings(qsettings):
    global settings
    settings = qsettings


def get_setting(name, default=None):
    settings.value(name, default)


class SettingsWindow(QWidget):
    def __init__(self, settings, session, *args):
        super().__init__(*args)
        self.settings = settings
        self.session = session
