import logging
import os
import pickle
import threading
import warnings
from collections import deque

from src.downloader import DownloaderPool

logger = logging.getLogger('debug')


class SessionManager(threading.Thread):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._path = os.path.join(os.getcwd(), 'data', 'session.dat')
        self._running = threading.Event()
        self._stop_event = threading.Event()
        self.downloader = DownloaderPool(max_workers=4)
        self.queues = {}
        self._excludes = [var for var in vars(self)]
        # Everything before this are excluded from the saving

        self._excludes.append('_excludes')
        self._excludes.append('temp_futures')
        self._excludes.append('queues')
        self.temp_futures = deque()
        self._finished = threading.Event()

        self.index = 0
        self.main_index = 0
        self.secondary_index = 0

        p = os.path.join(os.getcwd(), 'data')
        if not os.path.exists(p):
            os.mkdir(p)

        self._load_session()

    def _session_saver_loop(self):
        while self._running.is_set():
            self.save_session()
            for future in self.temp_futures.copy():
                try:
                    if future.done():
                        self.temp_futures.remove(future)
                except Exception as e:
                    print('Could not delete future %s' % e)

            self._stop_event.wait(timeout=120.0)

        self.save_session()
        self._finished.set()

    def run(self):
        self._running.set()
        self._session_saver_loop()

    def wait_for_stop(self, timeout=None):
        self._finished.wait(timeout)

    def stop(self):
        self._running.clear()
        self._stop_event.set()

    def _load_session(self):
        variables = {}
        if os.path.exists(self._path):
            try:
                with open(self._path, 'rb') as f:
                    _list = pickle.load(f)

                successful_stop = _list[0]
                try:
                    variables = _list[1]
                except IndexError:
                    pass

                if successful_stop is not True:
                    warnings.warn('Player was closed unsuccessfully')
                    logger.debug('Player was closed unsuccessfully')

            except Exception as e:
                logger.exception('Exception while getting session data. %s' % e)

        with open(self._path, 'wb') as f:
            pickle.dump([False], f)

        for variable, value in variables.items():
            setattr(self, variable, value)

    def save_session(self, exclude_list=None):
        if exclude_list is None:
            exclude_list = []

        with open(self._path, 'wb') as f:
            variables = {k: v for k, v in vars(self).items() if k not in self._excludes and k not in exclude_list and not k.startswith('_')}
            pickle.dump([True, variables], f)
