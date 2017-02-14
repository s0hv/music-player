import logging
import threading
from collections import deque
from concurrent.futures import TimeoutError

from src.exiftool import ExifTool
from src.song import Song
from src.database import FullSong

logger = logging.getLogger('debug')


def check_if_metadata_set(song):
    is_set = True
    check = ['duration', 'title', 'artist', 'cover_art', 'year']
    for variable in vars(FullSong):
        if variable not in check:
            continue

        res = getattr(song, variable)
        if res is None:
            is_set = False
            break

    return is_set


def update_song(song, forced=False, exiftool=None):
    if song.metadata_set and not forced:
        return

    future = song.set_cover_art(forced=forced)
    if song.is_file:
        ex = exiftool
        if exiftool is None:
            ex = ExifTool()
            ex.start()

        mt = ex.get_metadata(song.link)
        if mt is None:
            return

        mt = mt[0]

        for key in mt:
            variable = song.METADATA_CONVERSIONS.get(key, None)
            if variable is None:
                continue

            setattr(song, variable, mt[key])

        if exiftool is None:
            ex.terminate()

    else:
        if future is None:
            pass
        else:
            try:
                future.result(timeout=10)
            except TimeoutError:
                return

            if 'duration' in song.info and song.duration is None:
                song.duration = song.info['duration']

            if 'title' in song.info:
                song.title = song.info['title']

            if 'uploader' in song.info:
                song.artist = song.info['uploader']

            if 'upload_date' in song.info:
                song.year = int(song.info['upload_date'][:4])

    song.handler.db_action('commit_all')
    song.metadata_set = check_if_metadata_set(song)
    return True


class BaseMetadataUpdater(threading.Thread):
    def __init__(self, session, **kwargs):
        super().__init__(**kwargs)
        self.session = session
        self._stopper = threading.Event()
        self._songs = deque()
        self._update_metadata = threading.Event()
        self._exiftool = ExifTool()

    def running(self):
        return not self._stopper.is_set()

    def add_to_update(self, songs, forced=False):
        if isinstance(songs, Song):
            songs = [songs]

        if len(songs) == 0:
            return

        self._songs.append([songs, forced])
        self.start_update()

    def stop(self):
        self._stopper.set()

    def start_update(self):
        self._update_metadata.set()

    def _do_loop(self):
        items, forced = self._songs.popleft()

        for item in items:
            if not self.running():
                break

            after_update = None
            if not isinstance(item, Song):
                after_update = getattr(item, 'update_info')
                item = getattr(item, 'song')
                if item is None:
                    continue

            res = update_song(item, forced, self._exiftool)
            if callable(after_update) and res is not None:
                after_update()

    def _update_song(self, song, forced=False):
        if song.metadata_set and not forced:
            return

        future = song.set_cover_art(forced=forced)
        if song.is_file:
            mt = self._exiftool.get_metadata(song.link)
            if mt is None:
                return

            mt = mt[0]

            for key in mt:
                variable = song.METADATA_CONVERSIONS.get(key, None)
                if variable is None:
                    continue

                setattr(song, variable, mt[key])

        else:
            if future is None:
                pass
            else:
                try:
                    future.result(timeout=10)
                except TimeoutError:
                    return

                if 'duration' in song.info and song.duration is None:
                    song.duration = song.info['duration']

                if 'title' in song.info:
                    song.title = song.info['title']

                if 'uploader' in song.info:
                    song.artist = song.info['uploader']

                if 'upload_date' in song.info:
                    song.year = int(song.info['upload_date'][:4])

        song.handler.db_action('commit_all')
        song.metadata_set = check_if_metadata_set(song)
        return True

    @classmethod
    def _updater_loop(cls):
        pass

    def run(self):
        try:
            self._updater_loop()
        except Exception as e:
            logger.exception('Exception while updating metadata. %s' % e)


class MetadataUpdater(BaseMetadataUpdater):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _updater_loop(self):
        while self.running():
            self._update_metadata.wait()
            self._exiftool.start()

            while len(self._songs) > 0:
                self._do_loop()

            self._update_metadata.clear()
            self._exiftool.terminate()


class SingleMetadataUpdate(BaseMetadataUpdater):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _updater_loop(self):
        self._update_metadata.wait()
        self._exiftool.start()
        self._do_loop()
        self._stopper.set()
