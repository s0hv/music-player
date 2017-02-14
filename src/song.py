import logging
import os
import threading
from io import BytesIO

import pyaudio
import requests

from PIL import Image

from src.exiftool import ExifTool
from src.ffmpeg import FFmpeg
from src.utils import md5_hash, parse_duration, get_duration, trim_image

PA = pyaudio.PyAudio()
FORMAT = pyaudio.paInt16
RATES = [44100, 48000, 96000]
CHANNELS = 2
STREAMS = {rate: PA.open(format=FORMAT, channels=CHANNELS, rate=rate, output=True) for rate in RATES}

logger = logging.getLogger('debug')


class SongBase:
    __slots__ = ['song', 'db_handler', '_duration', '_formatted_duration']

    def __init__(self, song_item, db):
        self.song = song_item
        self.db_handler = db
        self._duration = None
        self._formatted_duration = None

    def get_name_and_author(self):
        name = self.title
        if name is None:
            name = self.name

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
    def file_type(self):
        return self.song.file_type

    @file_type.setter
    def file_type(self, file_type):
        self.db_handler.update(self.song, 'file_type', file_type)

    @property
    def name(self):
        return self.song.name

    @name.setter
    def name(self, name):
        self.db_handler.update(self.song, 'name', name)

    @property
    def link(self):
        return self.song.link

    @link.setter
    def link(self, link):
        self.db_handler.update(self.song, 'link', link)

    @property
    def play_count(self):
        return self.song.play_count

    @play_count.setter
    def play_count(self, play_count):
        self.db_handler.update(self.song, 'play_count', play_count)

    @property
    def rating(self):
        return self.song.rating

    @rating.setter
    def rating(self, rating):
        self.db_handler.update(self.song, 'rating', rating)

    @property
    def duration(self):
        return self.song.duration if self._duration is None else self._duration

    @duration.setter
    def duration(self, duration):
        self.db_handler.update(self.song, 'duration', duration)
        self._duration = duration

    @property
    def title(self):
        return self.song.title

    @title.setter
    def title(self, title):
        self.db_handler.update(self.song, 'title', title)

    @property
    def album(self):
        return self.song.album

    @album.setter
    def album(self, album):
        self.db_handler.update(self.song, 'album', album)

    @property
    def track(self):
        return self.song.track

    @track.setter
    def track(self, track: int):
        self.db_handler.update(self.song, 'track', track)

    @property
    def artist(self):
        return self.song.artist

    @artist.setter
    def artist(self, artist):
        self.db_handler.update(self.song, 'artist', artist)

    @property
    def year(self):
        return self.song.year

    @year.setter
    def year(self, year: int):
        self.db_handler.update(self.song, 'year', year)

    @property
    def band(self):
        return self.song.band

    @band.setter
    def band(self, band):
        self.db_handler.update(self.song, 'band', band)

    @property
    def cover_art(self):
        return self.song.cover_art

    @cover_art.setter
    def cover_art(self, cover_art):
        self.db_handler.update(self.song, 'cover_art', cover_art)

    @property
    def added(self):
        return self.song.added

    @property
    def metadata_set(self):
        return self.song.metadata_set

    @metadata_set.setter
    def metadata_set(self, is_set: bool):
        self.db_handler.update(self.song, 'metadata_set', is_set)


class Song(SongBase):
    METADATA_CONVERSIONS = {'Title': 'title',
                            'Artist': 'artist',
                            'Track': 'track',
                            'Album': 'album',
                            'Year': 'year',
                            'Duration': 'duration',
                            'Band': 'band'}

    __slots__ = ['index', 'downloader', '_ffmpeg', '_stream', 'metadata',
                 '_formatted_duration', 'info', 'future', '_dl_error','_dl_ready',
                 '_downloading', 'on_cover_art_changed', 'after_download']

    def __init__(self, db_item, db, downloader, index=-1, on_cover_art_change=None,
                 after_download=None, **kwargs):
        super().__init__(db_item, db)

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
        if duration is None or isinstance(self.duration, int):
            duration = get_duration(self.file)
            if duration is None:
                return

        if not isinstance(duration, int) and not isinstance(duration, float):
            raise ValueError('Duration must be int or float')

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
        self.set_file(filename)
        self.set_duration()
        self.set_cover_art()
        self._dl_ready.set()
        if callable(self.after_download):
            self.after_download(self)

    def download_song(self):
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
            future = self.downloader.download(self.link)
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
        # This doesn't commit changes
        if file is None:
            if not forced and self.cover_art is not None:
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
        return self._ffmpeg.file

    @property
    def ffmpeg(self):
        return self._ffmpeg

    @property
    def cover_art(self):
        return self.song.cover_art

    @cover_art.setter
    def cover_art(self, cover_art):
        self.db_handler.update(self.song, 'cover_art', cover_art)
        if callable(self.on_cover_art_changed):
            self.on_cover_art_changed(self)

    @property
    def stream(self):
        return self._stream


class SearchSong:
    def __init__(self, info):
        self.info = info
