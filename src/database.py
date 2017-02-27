import logging
import os
import pathlib
import pickle
import threading
import time
from collections import deque
from functools import wraps
from queue import Queue
from random import choice, shuffle

import sqlalchemy
from sqlalchemy import Integer, Column, String, INTEGER, Float, Boolean
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base, declared_attr
from sqlalchemy.orm import class_mapper
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.orm.attributes import manager_of_class
from sqlalchemy.orm.properties import ColumnProperty

from src.exiftool import ExifTool
from src.utils import get_supported_formats, grouper, print_info, concatenate_numbers

logger = logging.getLogger('debug')


def attribute_names(cls):
    return [prop.key for prop in class_mapper(cls).iterate_properties
        if isinstance(prop, sqlalchemy.orm.ColumnProperty)]


def get_state_dict(instance):
    cls = type(instance)
    mgr = manager_of_class(cls)
    return dict((key, getattr(instance, key))
                for key, attr in mgr.local_attrs.items()
                if isinstance(attr.property, ColumnProperty))


def create_from_state_dict(cls, state_dict):
    mgr = manager_of_class(cls)
    instance = mgr.new_instance()
    for key, value in state_dict.items():
        setattr(instance, key, value)
    return instance


def thread_local_session(func):
    @wraps(func)
    def decorator_func(self, *args, **kwargs):
        session = kwargs.pop('session', None)
        remove = True
        if session is None:
            session = self.Session()
            remove = False

        retval = func(self, *args, **kwargs, session=session)

        if kwargs.pop('commit', True):
            session.commit()
        if remove:
            self.Session.remove()

        return retval

    return decorator_func


class SongQueue(deque):
    def __init__(self, iterable=(), maxlen=None, cls=None):
        deque.__init__(self, iterable, maxlen)
        self.cls = cls


class SongBase:
    @declared_attr
    def __tablename__(cls):
        return cls._tablename

    id = Column(Integer, primary_key=True)
    name = Column(String)
    link = Column(String)

    def __repr__(self):
        return self.link

Base = declarative_base(cls=SongBase)


# Class that has all the info for the song
class FullSong:
    title = Column(String, default=None)
    artist = Column(String, default=None)
    duration = Column(Float, default=None)
    album = Column(String, default=None)
    track = Column(INTEGER, default=None)
    year = Column(INTEGER, default=None)
    band = Column(String, default=None)
    play_count = Column(INTEGER, default=0)  # How many times the song has been played
    rating = Column(INTEGER, default=0)
    file_type = Column(String, default='link')
    cover_art = Column(String, default=None)
    added = Column(INTEGER)  # Follows format YYYYMMDD
    metadata_set = Column(Boolean, default=False)


class DBSong(Base, FullSong):
    _tablename = 'songs'


# DBSong that is in the queue
class QSong(Base):
    _tablename = 'queue'
    real_id = Column(INTEGER)
    played = Column(Boolean, default=False)


class TempSong(Base, FullSong):
    _tablename = 'searched'


Playlist = declarative_base(cls=SongBase)


class PlaylistSong(FullSong):
    _tablename = 'playlist'


class EmptyPlaylistError(Exception):
    pass


class DBHandler:
    def __init__(self, name: str, session_manager):
        self.name = name if name.endswith('.db') else name + '.db'
        success = self._connect_to_db()
        if not success:
            raise ConnectionError('Could not connect to database')

        self.session_manager = session_manager
        self._load_history()
        self._second_queue = deque()
        #self.queue_pos = self.session_manager.index
        self._real_queue = deque()
        self.load_queue('data/queue.dat', self._real_queue)
        self.load_queue('data/second_q.dat', self._second_queue)
        self.playlist = None

    def _connect_to_db(self):
        path = 'databases'
        if not os.path.exists(path):
            try:
                os.mkdir(path)
            except WindowsError:
                return False

        path = os.path.join(path, self.name)
        self.engine = create_engine('sqlite:///%s' % path)
        self.engine.execute('PRAGMA encoding = "UTF-8"')
        DBSong.metadata.create_all(self.engine)

        session_factory = sessionmaker(bind=self.engine)
        self.Session = scoped_session(session_factory)

        return True

    def _load_history(self):
        self.history = deque(maxlen=30)
        if os.path.exists('data/history.dat'):
            with open('data/history.dat', 'rb') as f:
                _history = pickle.load(f)

            for item in _history:
                self.history.append(create_from_state_dict(DBSong, item))

    @thread_local_session
    def get_state_updated(self, instance, session=None):
        instance = session.query(type(instance)).filter_by(id=instance.id).first()
        if instance is not None:
                return get_state_dict(instance)

    @staticmethod
    def delete_history():
        try:
            os.remove(os.path.join(os.getcwd(), 'data', 'history.dat'))
        except OSError:
            pass

    def save_history(self):
        self.save_list(self.history, 'data/history.dat')

    @thread_local_session
    def q2q(self, session=None):
        for item in self.items(QSong, session=session).all():
            song = self.items(DBSong, session=session).filter_by(id=item.real_id).first()
            if isinstance(song, DBSong):
                self._real_queue.append(song)

    def shuffle_queue(self):
        shuffle(self._real_queue)

    @thread_local_session
    def queue(self, session=None):
        if len(self._real_queue) == 0:
            q = self.items(DBSong, session=session).all()
            self._real_queue = deque(q)

        return self._real_queue

    def clear_main_queue(self):
        self._real_queue.clear()

    def set_queue(self, queue):
        self._real_queue = queue

    def secondary_queue(self):
        return self._second_queue

    def add_to_second_queue(self, item):
        self._second_queue.append(item)
        print(self._second_queue)

    def clear_second_queue(self):
        self._second_queue.clear()

    @thread_local_session
    def save_list(self, queue, filename, session=None):
        if len(queue) == 0:
            return

        _queue = SongQueue(cls=type(queue[0]))
        for inst in queue:
            state_dict = self.get_state_updated(inst, session=session)
            if state_dict is not None:
                _queue.append(state_dict)

        with open(filename, 'wb') as f:
            pickle.dump(_queue, f)

    def save_queue(self):
        self.save_list(self._real_queue, 'data/queue.dat')

    @staticmethod
    def load_queue(filename, queue):
        if not os.path.exists(filename):
            return

        with open(filename, 'rb') as f:
            _queue = pickle.load(f)

        for item in _queue:
            queue.append(create_from_state_dict(_queue.cls, item))

    @thread_local_session
    def shutdown(self, session=None):
        session.commit()
        self.Session.remove()

        self.save_history()
        self.save_queue()
        print(self._second_queue)
        if self._second_queue:
            self.save_list(self._second_queue, 'data/second_q.dat')
        else:
            try:
                os.remove('data/second_q.dat')
            except OSError:
                pass

    def get_current_playlist(self):
        if self.playlist is None:
            return ()

        return self.playlist.query(PlaylistSong).all()

    def get_from_history(self, idx=-1):
        try:
            return self.history[idx]
        except IndexError:
            return

    def get_from_queue(self, idx=0):
        try:
            return self._real_queue[idx]
        except IndexError:
            return

    @staticmethod
    def _get_random_by_play_count(query):
        # Sort list by play count
        query = sorted(query, key=lambda x: x.play_count)
        play_count = query[0].play_count
        # Get all _songs with the lowest play count
        query = [x for x in query if x.play_count == play_count]
        return choice(query)

    @thread_local_session
    def items(self, cls, session=None):
        return session.query(cls)

    @thread_local_session
    def get_random_song(self, session=None):
        songs = session.query(DBSong).all()
        if not len(songs) > 0:
            print('Empty playlist')
            return None

        song = self._get_random_by_play_count(songs)
        return song

    def add_to_history(self, item):
        self.history.append(item)

    @thread_local_session
    def increment_playcount(self, item, session=None):
        song = self.items(DBSong, session=session).filter_by(link=item.link, name=item.name).first()
        if song:
            song.play_count += 1
        else:
            print('Item "%s" not found with id %s' % (item, item.id))
            logger.info('Error while incrementing play counts. {}'.format(vars(item)))

    @thread_local_session
    def filter_from_database(self, session=None, **filters):
        items = session.query(DBSong)
        return items.filter_by(**filters).all()

    @thread_local_session
    def set_up_shuffled_queue(self, query=None, session=None, cls=QSong):
        if query is None:
            query = session.query(DBSong)

        songs = query.all()
        if not songs:
            print('Empty playlist')
            return

        shuffle(songs)
        for song in songs:
            self.add_song(song.name, song.link, cls=cls, commit=False, real_id=song.id, session=session)

        session.commit()
        return session.query(QSong)

    @thread_local_session
    def get_duration(self, item, session=None):
        if isinstance(item, FullSong):
            return item.duration
        else:
            item = self.items(DBSong, session=session).filter_by(link=item.link, name=item.name).first()
            return item.duration if item else 0

    @thread_local_session
    def get_from_shuffled(self, session=None):
        query = session.query(QSong).all()
        if not query:
            query = self.set_up_shuffled_queue().all()

        try:
            song = query[self.queue_pos]
        except IndexError:
            return print('End of queue')

        self.queue_pos += 1
        if song:
            real_song = self.items(DBSong, session=session).filter_by(id=song.real_id, link=song.link, name=song.name).first()
            return real_song

    @staticmethod
    def get_item_type(item_link):
        item_type = 'link'
        if os.path.exists(item_link):
            if os.path.isfile(item_link):
                item_type = 'file'
            elif os.path.isdir(item_link):
                item_type = 'dir'

        return item_type

    @thread_local_session
    def _add_song(self, song, session=None, commit=True):
        session.add(song)

    @staticmethod
    def setup_filename(name):
        if not os.path.isabs(name):
            return os.path.realpath(name)
        return name

    @thread_local_session
    def add_song(self, name, link, item_type=None, cls=DBSong, session=None, commit=True, **kwargs):
        if not item_type:
            item_type = self.get_item_type(link)

        if item_type == 'file':
            link = self.setup_filename(link)

        if item_type == 'dir':
            # TODO add all dir files
            print('skipped folder %s' % link)
            return

        kwargs.pop('added', None)  # Because the song is added now the old entry is removed

        if hasattr(cls, 'added'):
            kwargs['added'] = self.get_time()

        song = cls(name=name, link=link, **kwargs)
        if getattr(cls, 'file_type', False):
            song.file_type = item_type

        self._add_song(song, session=session, commit=commit)
        return song

    @thread_local_session
    def get_temp_song(self, name, link, item_type='link', commit=True, session=None, **kwargs):
        if not item_type:
            item_type = self.get_item_type(link)

        if item_type == 'file':
            link = self.setup_filename(link)

        if item_type == 'dir':
            # TODO add all dir files
            print('skipped folder %s' % link)
            return

        kwargs['added'] = self.get_time()

        song = self.items(TempSong, session=session).filter_by(link=link).first()
        if song is None:
            song = TempSong(name=name, link=link, **kwargs)
            self._add_song(song, session=session, commit=commit)

        return song

    @staticmethod
    def _dict_info(d, include_mt=False):
        mt = {}
        if include_mt:
            for var in vars(DBSong):
                if not var.startswith('_'):
                    mt[var] = d.get(var, None)

            return mt

        else:
            mt['name'] = d.get('name')
            mt['link'] = d.get('link')

        return mt

    @staticmethod
    def _item_info(item, include_mt=False):
        mt = {}
        if include_mt:
            for var in vars(DBSong):
                if not var.startswith('_'):
                    mt[var] = getattr(item, var, None)

            return mt

        else:
            mt['name'] = getattr(item, 'name')
            mt['link'] = getattr(item, 'link')

        return mt

    @staticmethod
    def _list_info(l):
        return {'name': l[0], 'link': l[1]}

    def _get_info_from_item(self, item, include_metadata=False):
        """
        Gets the name and link from the provided object
        """
        if isinstance(item, dict):
            return self._dict_info(item, include_metadata)
        elif isinstance(item, list) or isinstance(item, tuple):
            return self._list_info(item)
        else:
            return self._item_info(item, include_metadata)

    @thread_local_session
    def add_songs(self, songs, cls=DBSong, include_metadata=False, session=None):
        for song in songs:
            try:
                kwargs = self._get_info_from_item(song, include_metadata)
                if 'name' not in kwargs or 'link' not in kwargs:
                    print('Link or name is None. Link and name must be specified in the object\nSkipping song "{}"'.format(song))
                    continue

            except Exception as e:
                print('Skipping %s because of an error\n%s' % (song, e))
                continue

            name, link = kwargs.pop('name'), kwargs.pop('link')
            self.add_song(name, link, commit=False, cls=cls, session=session, **kwargs)

    def add_from_file(self, filename, delim=' -<>- ', link_first=True,
                      link_format='https://www.youtube.com/watch?v={}',
                      custom_parser=None):
        """
        Args:
            filename:
                Name of the file read
            delim:
                What separates the link and name
            link_first:
                If the file has links before the names
            link_format:
                A string that the method format can be called with the link as its
                parameter. It's useful when the link is only an id
            custom_parser:
                A function that takes a single line as its parameter and returns
                name and link in that order. If nothing is specified the link and
                name are taken using information provided

        Returns:
            None
        """
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                lines = f.read().splitlines()
        except OSError as e:
            print('Error while opening file. %s' % e)
            return

        songs = []
        for line in lines:
            try:
                if callable(custom_parser):
                    name, link = custom_parser(line)
                else:
                    link, name = line.split(delim, 1)
                    if not link_first:
                        link, name = name, link

                    if link_format:
                        link = link_format.format(link)
            except ValueError:
                print('Could not get link and name for the line "%s"' % line)
                continue

            songs.append((name, link))

        self.add_songs(songs)

    @thread_local_session
    def add_from_folder(self, dir, subfolders=False, session=None):
        formats = get_supported_formats()
        exiftool = ExifTool()
        song_files = []
        if subfolders:
            for root, dir, files in os.walk(dir):
                for name in files:

                    ext = pathlib.Path(name).suffix[1:]
                    if ext in formats:
                        song_files.append(os.path.join(root, name))

        else:
            files = [f for f in os.listdir(dir) if os.path.isfile(os.path.join(dir, f))]
            for file in files:
                ext = pathlib.Path(file).suffix
                if ext in formats:
                    song_files.append(os.path.join(dir, file))

        exiftool.start()
        i = 0
        total = len(song_files)
        for files in grouper(song_files, 20):
            if files[-1] is None:
                # Remove all the None entries
                files = filter(None, files)

            metadata = exiftool.get_metadata(*files)
            for mt in metadata:
                i += 1
                song = self._from_metadata(mt)
                if song:
                    self._add_song(song, session=session, commit=False)
                else:
                    print('[Exception] Skipped {}'.format(mt))

                print_info(i, total, no_duration=True)

            session.commit()

        exiftool.terminate()

    @staticmethod
    def get_time():
        ltime = time.localtime()
        return concatenate_numbers(ltime.tm_year, ltime.tm_mon, ltime.tm_mday)

    def _from_metadata(self, mt):
        if mt is None:
            print('Metadata is None')
            return

        name = mt.get('Title', mt.get('FileName'))
        file = mt.get('SourceFile')

        if name is None or file is None:
            print('[ERROR] Name and filepath must be specified')
            return

        song = DBSong(name=name, link=file, file_type='file',
                      title=mt.get('Title'), album=mt.get('Album'),
                      track=mt.get('Track'), band=mt.get('Band'),
                      artist=mt.get('Artist'), year=mt.get('Year'),
                      added=self.get_time())

        return song

    @thread_local_session
    def update(self, db_item, name, value, session=None):
        DBItem = type(db_item)
        item = session.query(DBItem).filter(DBItem.id == db_item.id)
        item.update({name: value})
        return item


class ActionQueue(threading.Thread):
    """
    A thread that runs functions and returns the result or a queue that will have the result
    after the call is finished. With this every thread can access DBHandler functions
    as they need to be called from the same thread. You can also queue
    """
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.r = threading.Event()
        self.q = deque()
        self.running = threading.Event()

    def queue_action(self, action, *args, **kwargs):
        """Executes A function in this thread and returns the result
        Blocking
        See :func:`queue_nowait` for info about the parameters

        Returns:
            Whatever action(*args, **kwargs) returns
        """
        q = self.queue_nowait(action, *args, **kwargs)
        return q.get()

    def queue_nowait(self, action, *args, **kwargs):
        """
        Non-blocking
        Queue a function that wil be executed in this thread.

        MainWindow:
            This gets the ident of of the thread that executes this function

            res = queue_nowait(threading.get_ident)
            thread_id = res.get()

        Args:
            action: the function that will be called
            *args: args that will be passed to action
            **kwargs: kwargs that will be passed to action

        Returns:
            A Queue that will have the result of the function once it finishes
        """
        q = Queue()
        self.q.append((action, args, kwargs, q))
        self.r.set()
        return q

    def run(self):
        self.running.set()
        while True:
            self.r.wait()
            self.r.clear()
            while len(self.q) > 0:
                action, args, kwargs, q = self.q.popleft()
                try:
                    res = action(*args, **kwargs)
                except Exception as e:
                    print('database error: %s' % e)
                    res = None
                q.put(res)


class DBAccessThread(ActionQueue):
    def __init__(self, db, session, **kwargs):
        super().__init__(**kwargs)
        self.db = db
        self.session = session

    def _db_action(self, name, *args, **kwargs):
        action = getattr(self.db, name, None)
        if not callable(action):
            return action

        return action(*args, **kwargs)

    def db_action(self, name, *args, **kwargs):
        """Get an attribute from :obj:`DBHandler` and call it if it's callable
        Blocking

        For info on usage see :func:`ActionQueue.queue_action`
        """
        action = getattr(self.db, name, None)
        if not callable(action):
            return action

        return self.queue_action(action, *args, **kwargs)

    def db_action_nowait(self, name, *args, **kwargs):
        action = getattr(self.db, name, None)
        if not callable(action):
            return action

        self.queue_nowait(action, *args, **kwargs)

    def run(self):
        logger.debug('DBAccessThread ident %s' % threading.get_ident())
        self.db = DBHandler(self.db, self.session)
        super().run()
