import functools
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import youtube_dl

from src.cache import Cache


out_folder = os.path.join(os.getcwd(), 'cache', 'audio', '%(extractor)s-%(id)s-%(title)s.%(ext)s')
opts = {
    'format': 'bestaudio/best',
    'extractaudio': True,
    'audioformat': 'mp3',
    'outtmpl': out_folder,
    'restrictfilenames': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'external_downloader': 'ffmpeg',
    'external_downloader_args': ['-loglevel', 'error'],
    'prefer_ffmpeg': True,
    'nooverwrites': True}


class DownloaderPool:
    def __init__(self, max_workers=3):
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self._success = threading.Event()
        self._not_downloading = threading.Event()
        self._not_downloading.set()
        self.ytdl = youtube_dl.YoutubeDL(opts)
        self.extract_flat = youtube_dl.YoutubeDL(opts)
        self.extract_flat.params['extract_flat'] = True

        cache = os.path.join(os.getcwd(), 'cache', 'audio')
        if not os.path.isdir(cache):
            os.mkdir(cache)
        self.cache = Cache(cache)

    def download(self, link):
        return self.executor.submit(self._get_song, link)

    def get_info(self, link, flat=False):
        return self.executor.submit(self._get_info, link, flat=flat)

    def _get_info(self, link, flat=False):
        try:
            if flat:
                yt = self.extract_flat
            else:
                yt = self.ytdl

            info = functools.partial(yt.extract_info, link, download=False)()
        except Exception as e:
            print('Exception while downloading file. %s' % e)
        else:
            return info

    def _get_song(self, link, flat=False):
        try:
            info = functools.partial(self.ytdl.extract_info, link)()
        except Exception as e:
            print('Exception while downloading file. %s' % e)
        else:
            fname = self.ytdl.prepare_filename(info)
            self.cache.add_file(fname)
            return info, fname
