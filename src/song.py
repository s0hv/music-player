import logging
import os
import threading
from io import BytesIO
from functools import wraps

import pyaudio
import requests

from PIL import Image

from src.exiftool import ExifTool
from src.ffmpeg import FFmpeg
from src.utils import md5_hash, parse_duration, get_duration, trim_image
from src.database import CoverArt, Artist, AlbumArtist, Album, Genre, Composer
from apsw import BusyError, SQLError
from src.database import _database


PA = pyaudio.PyAudio()
FORMAT = pyaudio.paInt16
RATES = [44100, 48000, 96000]
CHANNELS = 2
STREAMS = {rate: PA.open(format=FORMAT, channels=CHANNELS, rate=rate, output=True) for rate in RATES}

logger = logging.getLogger('debug')


def item_updated(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            func(self, *args, **kwargs)
            self.song.save()
        except (BusyError, SQLError, ValueError) as e:
            print('Could not update song. %s' % e)

    return wrapper


class SongBase:
    METADATA_CONVERSIONS = {'Title': 'title',
                            'Artist': 'artist',
                            'Track': 'track',
                            'Album': 'album',
                            'Year': 'year',
                            'Duration': 'duration',
                            'Band': 'album_artist'}

    __slots__ = ['song', 'db_handler', '_duration', '_formatted_duration']

    def __init__(self, song_item):
        self.song = song_item
        self._duration = None
        self._formatted_duration = None

    def get_name_and_author(self):
        name = self.title
        author = self.artist
        if author is None:
            author = 'Unknown'

        return name, author

    @property
    def duration_formatted(self):
        if self.duration is None:
            return '00:00'

        if self._formatted_duration is None:
            dur = self.duration

            if dur is None:
                return '00:00'

            self._formatted_duration = parse_duration(dur)

        return self._formatted_duration

    @duration_formatted.setter
    def duration_formatted(self, formatted):
        self._formatted_duration = formatted

    @property
    def is_file(self):
        return self.file_type == 'file'

    @property
    def title(self):
        return self.song.title

    @title.setter
    @item_updated
    def title(self, title):
        self.song.title = title

    @property
    def link(self):
        return self.song.link

    @link.setter
    @item_updated
    def link(self, link):
        self.song.link = link

    @property
    def artist(self):
        if self.song.artist:
            return self.song.artist.name

    @artist.setter
    @item_updated
    def artist(self, artist):
        artist, c = Artist.get_or_create(name=artist)
        self.song.artist = artist

    @property
    def duration(self):
        return self.song.duration

    @duration.setter
    @item_updated
    def duration(self, duration):
        self.song.duration = duration

    @property
    def album(self):
        if self.song.album:
            return self.song.album.name

    @album.setter
    @item_updated
    def album(self, album):
        album, c = Album.get_or_create(name=album)
        self.song.album = album

    @property
    def track(self):
        return self.song.track

    @track.setter
    @item_updated
    def track(self, track: int):
        self.song.track = track

    @property
    def year(self):
        return self.song.year

    @year.setter
    @item_updated
    def year(self, year: int):
        self.song.year = year

    @property
    def album_artist(self):
        if self.song.album_artist:
            return self.song.album_artist.name

    @album_artist.setter
    @item_updated
    def album_artist(self, album_artist):
        album_artist, c = AlbumArtist.get_or_create(name=album_artist)
        self.song.album_artist = album_artist

    @property
    def play_count(self):
        return self.song.play_count

    @play_count.setter
    @item_updated
    def play_count(self, play_count):
        self.song.play_count = play_count

    @property
    def rating(self):
        return self.song.rating

    @rating.setter
    @item_updated
    def rating(self, rating):
        self.song.rating = rating

    @property
    def file_type(self):
        return self.song.file_type

    @file_type.setter
    @item_updated
    def file_type(self, file_type):
        self.song.file_type = file_type

    @property
    def cover_art(self):
        if self.song.cover_art:
            return self.song.cover_art.file

    @cover_art.setter
    @item_updated
    def cover_art(self, cover_art):
        cover_art, c = CoverArt.get_or_create(file=cover_art)
        self.song.cover_art = cover_art

    @property
    def added(self):
        return self.song.added

    @property
    def metadata_set(self):
        return self.song.metadata_set

    @metadata_set.setter
    @item_updated
    def metadata_set(self, is_set: bool):
        self.song.metadata_set = is_set

    def __getattr__(self, item):
        if item in self.__slots__:
            return self.__getattribute__(item)
        elif item == 'length':
            return self.duration

        else:
            return None


class Song(SongBase):
    __slots__ = ['index', 'downloader', '_ffmpeg', '_stream', 'metadata',
                 '_formatted_duration', 'info', 'future', '_dl_error','_dl_ready',
                 '_downloading', 'on_cover_art_changed', 'after_download',
                 'is_link']

    def __init__(self, db_item, downloader, index=-1, on_cover_art_change=None,
                 after_download=None, **kwargs):
        super().__init__(db_item)

        self.index = index
        self.on_cover_art_changed = on_cover_art_change
        self.after_download = after_download
        self.downloader = downloader
        self._ffmpeg = FFmpeg(**kwargs)
        self._stream = None
        self.metadata = {}
        self._formatted_duration = None
        self.info = {}
        self.future = None
        self._dl_error = None
        self._dl_ready = None
        self._downloading = None
        self.is_link = not self.is_file

    def set_file(self, file):
        self._ffmpeg.file = file

    def set_info(self, info):
        self.info = {**info}

        if self.artist is None:
            self.artist = self.info.get('uploader', None)

        if self.title is None:
            self.title = self.info.get('title', None)

    def trim_cover_art(self):
        if self.cover_art is None:
            return

        image = Image.open(self.cover_art)
        image_trimmed = trim_image(image)
        buffer = BytesIO()
        image_trimmed.save(buffer, format='PNG')

        buffer.seek(0)
        md5 = md5_hash(buffer)
        buffer.seek(0)

        path = os.path.join(os.getcwd(), 'cache', 'cover_art', 'downloaded')
        if not os.path.exists(path):
            os.makedirs(path)

        fname = os.path.join(path, md5)
        if os.path.exists(fname):
            self.delete_cover_art()
            self.cover_art = fname
            return None, fname

        with open(fname, 'wb') as f:
            for chunk in iter(lambda: buffer.read(4096), b""):
                f.write(chunk)

        self.delete_cover_art()
        self.cover_art = fname

    def delete_cover_art(self):
        if self.cover_art is not None:
            try:
                res = self.db_handler.filter_from_database(cover_art=self.cover_art)
                if len(res) == 1:
                    os.remove(self.cover_art)
                    self.cover_art = None
            except OSError as e:
                logger.debug('Could not delete cover art %s. %s' % (self.cover_art, e))

    def _get_file_cover_art(self):
        path = os.path.join(os.getcwd(), 'cache', 'cover_art', 'embedded')
        if not os.path.exists(path):
            os.makedirs(path)

        if 'Picture' not in self.metadata:
            exiftool = ExifTool()
            exiftool.start()
            if self._ffmpeg.file is None:
                self.set_file(self.link)

            pic = exiftool.get_cover_art(self._ffmpeg.file)
            exiftool.terminate()

            if not pic:
                return None, None

        else:
            pic = self.metadata.pop('Picture')

        buffer = BytesIO(pic)
        md5 = md5_hash(buffer)
        buffer.seek(0)

        fname = os.path.join(path, md5)
        if os.path.exists(fname):
            logger.debug('Cover art for {} {} already exists with filename {}'.format(self.name, self.link, fname))
            return None, fname

        return buffer, fname

    def set_duration(self, duration=None):
        if duration is None:
            if self.is_link:
                duration = self.info.get('duration')
            else:
                duration = get_duration(self.file)

            if duration is None:
                return

        if not isinstance(duration, int) and not isinstance(duration, float):
            print('Duration must be int or float')
            logger.debug('Duration must be int or float')
            return

        self.duration = duration

    def after_dl(self, future):
        result = future.result()
        self._downloading.clear()
        if result is None:
            self._dl_error.set()
            self._dl_ready.set()
            return

        info, filename = result
        self.set_info(info)
        if filename is False:
            filename = info.get('url')
            if filename is None:
                self._dl_error.set()
                self._dl_ready.set()
                return

        self.set_file(filename)
        self.set_duration()
        self.set_cover_art()
        self._dl_ready.set()
        if callable(self.after_download):
            self.after_download(self)

    def download_song(self, download=True):
        if self._dl_ready is None:
            self._dl_error = threading.Event()
            self._dl_ready = threading.Event()
            self._downloading = threading.Event()

        if self._dl_ready.is_set():
            return

        if self.is_file:
            self.set_file(self.link)
            self.set_duration()
            self.set_cover_art()
            self._dl_ready.set()
        else:
            if self._downloading.is_set():
                return

            self._downloading.set()
            self.is_link = not download

            if self.is_link:
                self.ffmpeg.before_options = '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 2 -timeout 10'

            future = self.downloader.download(self.link, download=download)
            future.add_done_callback(self.after_dl)

    def _get_cover_art_after_info(self, future):
        result = future.result()
        if result is None:
            return

        if not result:
            return

        self.info = result
        self.set_cover_art(forced=True)

    def _get_link_cover_art(self):
        if not self.info:
            future = self.downloader.get_info(self.link)
            future.add_done_callback(self._get_cover_art_after_info)
            return future

        pic = self.info.get('thumbnail', None)
        if pic is None:
            return None, None

        r = requests.get(pic, stream=True)
        buffer = BytesIO(r.content)
        md5 = md5_hash(buffer)
        buffer.seek(0)

        path = os.path.join(os.getcwd(), 'cache', 'cover_art', 'downloaded')
        if not os.path.exists(path):
            os.makedirs(path)

        fname = os.path.join(path, md5)
        if os.path.exists(fname):
            return None, fname

        return buffer, fname

    def set_cover_art(self, file: str=None, forced=False):
        if file is None:
            if not forced and self.cover_art is not None and os.path.exists(self.cover_art):
                return

            try:
                if self.is_file:
                    buffer, fname = self._get_file_cover_art()
                else:
                    resp = self._get_link_cover_art()
                    if isinstance(resp, tuple):
                        buffer, fname = resp
                    else:
                        return resp

            except Exception as e:
                logger.exception('Could not get cover art. %s' % e)
                return

            if buffer is None:
                if fname is not None:
                    self.cover_art = fname
                return

            with open(fname, 'wb') as f:
                for chunk in iter(lambda: buffer.read(4096), b""):
                    f.write(chunk)

            self.cover_art = fname

        else:
            self.cover_art = file

    def set_metadata(self):
        if self.is_link or not isinstance(self.file, str):
            return

        file = self._ffmpeg.file
        exiftool = ExifTool()
        exiftool.start()
        try:
            self.metadata = exiftool.get_metadata(file)[0]
        except Exception as e:
            self.metadata = {}
            logger.info('Could not get metadata from file %s\nError: %s' % (file, e))

        exiftool.terminate()
        return self.metadata

    def create_stream(self):
        self.set_metadata()
        samplerate = int(self.metadata.get('Sample Rate', '44100'))
        if samplerate not in RATES:
            samplerate = 44100

        self.ffmpeg.samplerate = samplerate

        self._stream = STREAMS[samplerate]
        logger.debug('Using stream {} with samplerate at {}'.format(self._stream, samplerate))
        return samplerate

    def get_name_and_author(self):
        name = self.title
        if name is None:
            name = self.name

        author = self.artist
        if author is None:
            author = self.info.get('uploader', 'Unknown')

        return name, author

    def add_filter(self, filter, arguments=None):
        self._ffmpeg.add_filter(filter, arguments)

    @property
    def dl_error(self):
        return True if self._dl_error is None else self._dl_error.is_set()

    @property
    def dl_finished(self):
        return False if self._dl_ready is None else self._dl_ready.is_set()

    @property
    def ready_for_use(self):
        return False if self._dl_ready is None else self._dl_ready.is_set() and not self._dl_error.is_set()

    def wait_until_ready(self, timeout=None):
        if self._dl_ready is None:
            return

        self._dl_ready.wait(timeout=timeout)

    @property
    def duration_formatted(self):
        if self.duration is None and 'duration' not in self.info:
            return '00:00'

        if self._formatted_duration is None:
            dur = self.duration
            if dur is None:
                dur = self.info.get('duration')

            if dur is None:
                return '00:00'

            self._formatted_duration = parse_duration(dur)

        return self._formatted_duration

    @duration_formatted.setter
    def duration_formatted(self, formatted):
        self._formatted_duration = formatted

    @property
    def file(self):
        if self.is_file:
            return self.link
        else:
            return self._ffmpeg.file

    @property
    def ffmpeg(self):
        return self._ffmpeg

    @property
    def cover_art(self):
        if self.song.cover_art:
            return self.song.cover_art.file

    @cover_art.setter
    @item_updated
    def cover_art(self, cover_art):
        cover_art, created = CoverArt.get_or_create(file=cover_art)
        self.song.cover_art = cover_art

        if callable(self.on_cover_art_changed):
            self.on_cover_art_changed(self)

    @property
    def stream(self):
        return self._stream


class SearchSong:
    def __init__(self, info):
        self.info = info
