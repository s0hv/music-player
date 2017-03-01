import threading
import os
from os.path import join
from src.utils import get_supported_audio_formats

from src.database import DBSong


class LibraryUpdater(threading.Thread):
    def __init__(self, session, db, settings, **kwargs):
        super().__init__(**kwargs)
        self.session = session
        self.db = db
        self.settings_manager = settings
        self.formats = get_supported_audio_formats()

    def check_correct_extension(self, file):
        ext = file.split('.')
        if len(ext) < 2:
            raise NotImplementedError('Cannot check for proper file type if the file has no file extension')

        if self.formats is None:
            raise Exception('Format file could not be generated. Files cannot be checked')

        ext = ext[-1]
        if ext in self.formats:
            return True
        else:
            return False

    def _updater_loop(self):
        # Do not call this outside of run
        pass

    def run(self):
        self._updater_loop()


class Dir:
    def __init__(self, directory, include_subdirs=False, old: set=None):
        self.directory = directory
        self.include_subdirs = include_subdirs
        self.old = set() if old is None else old

    def check_changes(self):
        if not os.path.exists(self.directory):
            return self.old

        new = set()
        for root, dir, files in os.walk(self.directory):
            path = os.path.relpath(root, self.directory)
            for file in files:
                new.add(join(path, file))

            if not self.include_subdirs:
                break

        return self.compare_sets(new, self.old)

    @staticmethod
    def compare_sets(new: set, old: set):
        deleted = old.difference(new)
        added = new.difference(old)

        return added, deleted


class DirUpdater(threading.Thread):
    def __init__(self, settings_manager, session_manager, db, after_update=None,
                 **kwargs):
        super().__init__(**kwargs)

        self.settings_manager = settings_manager
        self.session_manager = session_manager
        self.db = db
        self._after_update = after_update
        self.dirs = self.session_manager.scanned_dirs

    @property
    def settings(self):
        return self.settings_manager.get_settings_instance()

    def _single_dir(self, directory, session):
        for file in os.listdir(directory):

    def _update_loop(self):
        session = self.db.get_thread_local_session()
        query = self.db.items(DBSong, session=session).filter_by(
            file_type='file')
        for directory in self.dirs:
            if directory.include_subdirs:
                pass
            else:
                self._single_dir(directory, session)

    def run(self):
        self._update_loop()
