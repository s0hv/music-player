import threading
import os
from os.path import join
import csv
import pickle
from src.utils import get_supported_audio_formats, get_supported_formats

from src.database import FullSong
from src.metadata import update_song, get_file_metadata
from src.utils import path_leaf
from src.exiftool import ExifTool
from src.song import SongBase

import logging
logger = logging.getLogger('debug')


class DirDump:
    def __init__(self):
        self.dirs = []

    def load_dirs(self):
        file = join(os.getcwd(), 'data', 'library_dirs.dat')
        if not os.path.exists(file):
            return []

        try:
            with open(file, 'rb') as f:
                dirs = pickle.load(f)
        except:
            logger.exception('Exception while loading library dirs')
        else:
            self.dirs = dirs

        return self.dirs

    def save_dirs(self):
        try:
            file = join(os.getcwd(), 'data', 'library_dirs.dat')
            with open(file, 'wb') as f:
                pickle.dump(self.dirs, f)

        except:
            raise

        return True


class LibraryUpdater(threading.Thread):
    def __init__(self, session, db, **kwargs):
        super().__init__(**kwargs)
        self.session = session
        self.db = db
        self.dirdump = DirDump()
        self.dirdump.load_dirs()
        self.formats = get_supported_formats()
        self._exif = None
        self.stop_ = threading.Event()
        self.deleted = []
        self.new = []

    def check_correct_extension(self, file):
        ext = path_leaf(file).split('.')
        if len(ext) < 2:
            return True

        if self.formats is None:
            raise Exception('Format file is not generated. Files cannot be checked')

        ext = ext[-1]
        if ext in self.formats:
            return True
        else:
            print('Skipping file %s' % file)
            return False

    def _updater_loop(self):
        # Do not call this outside of run
        for directory in self.dirdump.dirs:
            if self.stop_.is_set():
                break

            new_deleted, files = directory.check_changes()
            new, deleted = new_deleted
            self.new.append(new)
            self.deleted.append(deleted)

            directory.old = files

        self._exif = ExifTool()
        self._exif.start()
        for files in self.new:
            files = list(filter(self.check_correct_extension, files))

            mt = self._exif.get_metadata(*files)
            mt = list(filter(lambda x: 'audio' in x.get('MIMEType', '') or 'video' in x.get('MIMEType', ''), mt))
            print(mt)

        self._exif.terminate()

    def k(self):
        query = FullSong.select().where(FullSong.file_type == 'file')
        """
        for file in new:
            if self._stop.is_set():
                break

            path = join(directory.directory, file)
            item = query.filter_by(link=path).first()
            if item is None:
                mt = get_file_metadata(path, exiftool=self._exif)
                if settings.value('check_for_dupes', False):
                    dupe = query.filter_by(title=mt.get('title'),
                                           artist=mt.get('artist')).first()
                    if dupe is not None:
                        # TODO Do something
                        pass

                        # item = self.db.add_song(path_leaf(path), path, item_type='file', session=session, commit=False, **mt)

            else:
                update_song(item, exiftool=self._exif)
        """

    def run(self):
        self._updater_loop()

    def stop(self):
        self.stop_.set()


class Dir:
    def __init__(self, directory, include_subdirs=False, old: set=None):
        self.directory = directory
        self.include_subdirs = include_subdirs
        self.old = set() if old is None else old
        self.new = None

    def check_changes(self):
        current = set()
        if not os.path.exists(self.directory):
            return current, self.old, set()

        for root, dirs, files in os.walk(self.directory):
            path = root
            [current.add(join(path, f)) for f in files if not f[0] == '.']
            dirs[:] = [d for d in dirs if not d[0] == '.']

            if not self.include_subdirs:
                break

        return self.compare_sets(current, self.old), current

    @staticmethod
    def compare_sets(current: set, old: set):
        deleted = old.difference(current)
        added = current.difference(old)

        return added, deleted

    def __getstate__(self):
        return self.__dict__

    def __setstate__(self, d):
        self.__dict__ = d
