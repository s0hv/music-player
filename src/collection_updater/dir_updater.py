import os
import threading


class DirUpdater(threading.Thread):
    def __init__(self, settings_manager, **kwargs):
        super().__init__(**kwargs)

        self.settings_manager = settings_manager
        self.dirs = self.settings.value('music_directories', '').split('\n')

    @property
    def settings(self):
        return self.settings_manager.get_settings_instance()
