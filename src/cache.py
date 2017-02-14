import os
import ntpath
from collections import deque
import logging


logger = logging.getLogger('debug')


def name_from_path(path):
    head, tail = ntpath.split(path)
    return tail or ntpath.basename(head)


class DirEntry:
    def __init__(self, path):
        self._path = path
        self._name = name_from_path(path)
        self._stat = None

    @property
    def path(self):
        return self._path

    def stat(self):
        if self._stat is None:
            self._stat = os.stat(self.path)
        return self._stat

    def __repr__(self):
        return self._name

    @property
    def name(self):
        return self._name


class Cache:
    def __init__(self, cache_folder, max_size=104857600):
        self.max_size = max_size
        if os.path.isabs(cache_folder):
            self.folder = cache_folder
        else:
            self.folder = os.path.join(os.getcwd(), cache_folder)
            if not os.path.exists(self.folder):
                self.folder = os.path.normpath(self.folder)

            if not os.path.exists(self.folder):
                raise InvalidCacheFolder("Cache folder %s doesn't exist" % self.folder)

        self.curr_size = 0
        self.files = self._sorted_by_modification_date()
        self.delete_oldest()

    def _get_size(self):
        return sum(os.path.getsize(os.path.join(self.folder, f)) for f in os.listdir(self.folder))

    def _sorted_by_modification_date(self):
        files = deque(os.scandir(self.folder))
        return sorted(files, key=lambda x: x.stat().st_ctime, reverse=True)

    @property
    def is_full(self):
        return self.curr_size > self.max_size

    def in_cache(self, path):
        for e in self.files:
            if e.path == path:
                return True

    def add_file(self, path):
        if self.in_cache(path):
            return
        entry = DirEntry(path)
        ctime = entry.stat().st_ctime
        for idx, e in enumerate(self.files):
            a = e.stat().st_ctime
            if a < ctime:
                self.files.insert(idx, entry)
                break

        self.delete_oldest()

    def delete_oldest(self):
        self.curr_size = self._get_size()
        if self.is_full:
            logger.debug('Audiocache full deleting files')
            for file in reversed(self.files):
                path = file.path
                size = os.path.getsize(path)
                try:
                    os.remove(path)
                    logger.debug('Deleted %s' % path)
                except OSError:
                    continue

                self.curr_size -= size
                self.files.pop()
                if not self.is_full:
                    break


class ArtCache:
    def __init__(self, root_folder, embed_folder, dl_folder):
        self.root = root_folder
        self.embedded = embed_folder
        self.downloaded = dl_folder


class InvalidCacheFolder(Exception):
    pass