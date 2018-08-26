import logging
import os
import pickle
import threading
import warnings
from collections import deque

from src.downloader import DownloaderPool
from src.globals import GV

logger = logging.getLogger('debug')


class SessionManager(threading.Thread):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._path = os.path.join(os.getcwd(), 'data', 'session.dat')
        self._running = threading.Event()
        self._resume_event = threading.Event()
        self.downloader = DownloaderPool(max_workers=4)
        self.queues = {k: [] for k in GV.Queues.keys()}
        self.scanned_dirs = []
        self.updated_playlists = []
        # Everything before this are excluded from the saving
        self._excludes = [var for var in vars(self)]

        self._excludes.append('_excludes')
        self._excludes.append('temp_futures')
        self.temp_futures = deque()  # This is needed so Qt won't delete some objects
        self._finished = threading.Event()
        self.successful_stop = False

        self.index = 0
        self.main_index = 0
        self.secondary_index = 0

        p = os.path.join(os.getcwd(), 'data')
        if not os.path.exists(p):
            os.mkdir(p)

        self._load_session()

    def run_loop(self):
        self._resume_event.set()
        self._resume_event.clear()

    def _session_saver_loop(self):
        while self._running.is_set():
            self.save_session()
            for future in self.temp_futures.copy():
                try:
                    if future.done():
                        self.temp_futures.remove(future)
                except Exception as e:
                    print('Could not delete future %s' % e)

            self._resume_event.wait(timeout=120.0)

        self.save_session()
        self._finished.set()

    def run(self):
        self._running.set()
        self._session_saver_loop()

    def wait_for_stop(self, timeout=None):
        self._finished.wait(timeout)

    def stop(self):
        self._running.clear()
        self.successful_stop = True
        self._resume_event.set()

    def clear_main_queue(self):
        self.queues.get(GV.MainQueue, []).clear()

    def clear_secondary_queue(self):
        self.queues.get(GV.SecondaryQueue, []).clear()

    def add_to_queue(self, item, queue=GV.MainQueue):
        self.queues[queue].append(item)

    def _load_session(self):
        variables = {}
        if os.path.exists(self._path):
            try:
                with open(self._path, 'rb') as f:
                    variables = pickle.load(f)

                if not isinstance(variables, dict) or variables.get('successful_stop', False) is not True:
                    warnings.warn('Player was closed unsuccessfully')
                    logger.debug('Player was closed unsuccessfully')

            except Exception as e:
                logger.exception('Exception while getting session data. %s' % e)

        for variable, value in variables.items():
            setattr(self, variable, value)

        self.successful_stop = False
        self.save_session()

    def save_session(self, exclude_list=None):
        if exclude_list is None:
            exclude_list = []

        with open(self._path, 'wb') as f:
            variables = {k: v for k, v in vars(self).items() if k not in self._excludes and k not in exclude_list and not k.startswith('_')}
            pickle.dump(variables, f)
