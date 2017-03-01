import threading

from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import QSettings


class Settings(QSettings):
    def __init__(self, *args):
        super().__init__(*args)


class SettingsManager:
    def __init__(self, organization='s0hvaperuna', application='Music player',
                 scope=QSettings.UserScope, format=QSettings.NativeFormat):
        self.organization = organization
        self.application = application
        self.scope = scope
        self.format = format
        self._settings_instances = {}

    def get_settings_instance(self):
        settings = self._settings_instances.get(threading.get_ident(), None)
        if settings is None:
            settings = self.get_unique_settings_inst()
            self._settings_instances[threading.get_ident()] = settings

        return settings

    def get_unique_settings_inst(self):
        return Settings(self.format, self.scope, self.organization, self.application)


class SettingsWindow(QWidget):
    def __init__(self, settings, session, *args):
        super().__init__(*args)
        self.settings = settings
        self.session = session
