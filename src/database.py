import os
import pathlib
import time
from collections import deque
import re
from functools import wraps

from apsw import SQLError
from playhouse.apsw_ext import (APSWDatabase, Model, TextField, CharField,
                                FloatField,
                                IntegerField, DateTimeField,
                                ForeignKeyField,
                                OperationalError, SQL, IntegrityError,
                                DeferredForeignKey,
                                DoesNotExist, Proxy)
from peewee import ManyToManyField

from src.exiftool import ExifTool
from src.globals import GV
from src.utils import (grouper, print_info, get_supported_formats, check_correct_extension,
                       get_file_cover_art, b64_to_cover_art)

_database = Proxy()
_database_stack = deque()


import logging
logger = logging.getLogger('debug')


class BaseModel(Model):
    class Meta:
        database = _database


class CoverArt(BaseModel):
    file = CharField()


class Artist(BaseModel):
    name = TextField()


class AlbumArtist(BaseModel):
    name = TextField()


class Album(BaseModel):
    name = TextField()
    album_artist = ForeignKeyField(AlbumArtist, default=None, null=True)

    class Meta:
        db_table = 'albums'


class Genre(BaseModel):
    name = TextField()

    class Meta:
        db_table = 'genres'


class Composer(BaseModel):
    name = TextField()

    class Meta:
        db_table = 'composers'


class EqualizerPreset(BaseModel):
    command = TextField()

    class Meta:
        db_table = 'eq_presets'


# Base for song items
class FullSong(BaseModel):
    title = TextField()
    link = TextField(unique=True)
    artist = ForeignKeyField(Artist, default=None, null=True, backref='songs')
    duration = FloatField(default=0)
    album = ForeignKeyField(Album, default=None, null=True, backref='songs')
    genre = ForeignKeyField(Genre, default=None, null=True, backref='songs')
    composer = ForeignKeyField(Composer, default=None, null=True, backref='songs')
    eq_preset = ForeignKeyField(EqualizerPreset, default=None, null=True, backref='songs')
    track = IntegerField(default=None, null=True)
    year = IntegerField(default=None, null=True)
    play_count = IntegerField(default=0)
    rating = IntegerField(default=0)
    file_type = CharField(default='link')
    folder = TextField(default=None, null=True)
    cover_art = ForeignKeyField(CoverArt, backref='songs', default=None,
                                null=True)

    added = DateTimeField(constraints=[SQL('DEFAULT CURRENT_TIMESTAMP')])

    class Meta:
        db_table = 'songs'


class PlaylistThroughSong(BaseModel):
    playlist = DeferredForeignKey('Playlist', unique=False)
    fullsong = ForeignKeyField(FullSong, unique=False)


class Playlist(BaseModel):
    name = TextField()
    songs = ManyToManyField(FullSong, backref='playlists')


class Tag(BaseModel):
    name = CharField()
    songs = ManyToManyField(FullSong, backref='tags')


class QueueSong(BaseModel):
    metadata = ForeignKeyField(FullSong, unique=False)
    sort_order = IntegerField(null=False)


class TempSong(BaseModel):
    cover_art = ForeignKeyField(CoverArt, backref='temp_songs',
                                default=None, null=True)
    artist = ForeignKeyField(Artist, default=None, null=True, backref='temp_songs')
    album = ForeignKeyField(Album, default=None, null=True, backref='temp_songs')
    album_artist = ForeignKeyField(AlbumArtist, default=None, null=True, backref='temp_songs')
    genre = ForeignKeyField(Genre, default=None, null=True,backref='temp_songs')
    composer = ForeignKeyField(Composer, default=None, null=True,backref='temp_songs')
    eq_preset = ForeignKeyField(EqualizerPreset, default=None, null=True, backref='temp_songs')

    class Meta:
        db_table = 'temporary_songs'


def connect_database():
    if _database.is_closed():
        _database.connect()
    _database_stack.append(None)
    print(len(_database_stack))


def close_database():
    _database_stack.pop()
    print(len(_database_stack))
    if len(_database_stack) == 0:
        _database.close()


def database_connection(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
        connect_database()
        try:
            retval = func(*args, **kwargs)
        except Exception as e:
            close_database()
            raise Exception from e
        else:
            close_database()
            return retval

    return wrapper


class Database:
    def __init__(self, session=None, db_name=GV.DatabaseName):
        self.database = APSWDatabase(db_name, c_extensions=False, autorollback=True, autocommit=True)

        _database.initialize(self.database)
        self.database.connect()
        #self.database._local.conn.setbusytimeout(3000)

        self.session_manager = session
        self._database_stack = deque()

        try:
            self.database.create_tables(
                [FullSong, Playlist, Tag, CoverArt, QueueSong, TempSong,
                 Artist, AlbumArtist, Genre, Composer, EqualizerPreset,
                 Playlist.songs.get_through_model(),
                 Tag.songs.get_through_model(), Album])
        except (OperationalError, SQLError) as e:
            print(e)

    @staticmethod
    @database_connection
    def select_by_tags(*tags):
        tags = list(map(lambda t: t.id, tags))
        model = Tag.songs.get_through_model()
        return FullSong.select().join(model).where(model.tag_id.in_(tags))

    @staticmethod
    @database_connection
    def select_by_playlists(*playlists):
        playlists = list(map(lambda p: p.id, playlists))
        model = Playlist.songs.get_through_model()
        return FullSong.select().join(model).where(
            model.playlist_id.in_(playlists))

    @database_connection
    def add_to_queue(self, songs, clear_before=False):
        if clear_before:
            self.clear_queue()

        for idx in range(0, len(songs), 100):
            with self.database.atomic() as txn:
                try:
                    QueueSong.insert_many(songs[idx:idx + 100]).execute()
                except Exception as e:
                    txn.rollback()
                    raise

    @database_connection
    def clear_queue(self):
        with self.database.atomic() as txn:
            try:
                QueueSong.delete().execute()
            except Exception as e:
                txn.rollback()
                raise

    def fullsongs_to_queue(self, songs, clear_before=False):
        i = QueueSong.select().count()
        s = []
        for song in songs:
            s.append({'metadata': song.id, 'sort_order': i})
            i += 1

        self.add_to_queue(s, clear_before=clear_before)

    @database_connection
    def get_queue(self):
        return list(FullSong.select()
                    .join(QueueSong)
                    .group_by(QueueSong.sort_order, QueueSong.id))

    @staticmethod
    def get_item_type(item_link):
        item_type = 'link'
        if os.path.exists(item_link):
            if os.path.isfile(item_link):
                item_type = 'file'
            elif os.path.isdir(item_link):
                item_type = 'dir'

        return item_type

    @staticmethod
    def set_cover_art(song, img):
        cover_art, created = CoverArt.get_or_create(file=img)
        song.cover_art = cover_art.id

    @database_connection
    def add_to_playlist_by_tags(self, playlist, *tags, ignore_duplicates=False):
        model = Tag.songs.get_through_model()
        playlist_model = Playlist.songs.get_through_model()
        tags = map(lambda t: t.id, tags)
        playlist_id = playlist.id

        songs = (FullSong
                 .select()
                 .join(model)
                 .where(model.tag_id.in_(tags)))

        if not ignore_duplicates:
            invalid_songs = (
                songs.switch(FullSong)
                    .select(FullSong.id)
                    .join(playlist_model).distinct()
                    .where(playlist_model.playlist_id == playlist_id))

            invalid_songs = list(map(lambda s: s.id, invalid_songs))
            songs = songs.switch(FullSong).where(
                FullSong.id.not_in(invalid_songs))

        with self.database.atomic() as txn:
            try:
                playlist.songs.add(songs)
            except Exception as e:
                txn.rollback()
                raise

    def construct_fullsong_metadata(self, **kwargs):
        kwargs.pop('id', None)
        # TODO
        return self

    @staticmethod
    def setup_filename(name):
        if not os.path.isabs(name):
            return os.path.realpath(name)
        return name

    @database_connection
    def shuffle_queue(self):
        """
        Updates sort_order value for each QueueSong by selecting a random integer
        between 0 and the current row count. Duplicate values will exist because of this 
        but the results randomness shouldn't be affected much because of this"""
        length = QueueSong.select().count()
        self.database.execute_sql('UPDATE queuesong SET sort_order=ABS(RANDOM() % {})'.format(length))

    @database_connection
    def get_temp_song(self, name, link, item_type='link', **kwargs):
        if not item_type:
            item_type = self.get_item_type(link)

        if item_type == 'file':
            link = self.setup_filename(link)

        if item_type == 'dir':
            return print('Skipped folder %s' % link)

        try:
            song = TempSong.get(TempSong.link == link & TempSong.title == name)
        except DoesNotExist:
            song = TempSong(name=name, link=link, **kwargs)
            song.save()

        return song

    def add_songs(self, cls, songs, step=100, on_error=None):
        for idx in range(0, len(songs), step):
            with self.database.atomic() as txn:
                _songs = songs[idx:idx + step]
                try:
                    cls.insert_many(_songs).execute()
                except Exception as e:
                    txn.rollback()
                    if callable(on_error):
                        on_error(e, _songs)

    def add_from_file(self, filename, delim=' -<>- ', link_first=True,
                      link_format='https://www.youtube.com/watch?v={}',
                      custom_parser=None, on_error=None):
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

            songs.append({'title': name, 'link': link})

        self.add_songs(FullSong, songs, on_error=on_error)

    def add_from_folder(self, dir, subfolders=False):
        formats = get_supported_formats()
        exiftool = ExifTool()
        song_files = {}
        for root, dirs, files in os.walk(dir):
            path = root
            # Only include files and folder that are not hidden -> they don't start with "."
            song_files[path] = Dir(path, [f for f in files if not f[0] == '.'])
            dirs[:] = [d for d in dirs if not d[0] == '.']

            if not subfolders:
                break

        exiftool.start()
        i = 0
        total = 0
        for folder in song_files.values():
            folder.filter_files(formats)
            total += len(folder.files)

        for folder in song_files.values():
            for files in grouper(folder.files, 20):
                if files[-1] is None:
                    # Remove all the None entries created by grouper
                    files = filter(None, files)

                # Get full filenames
                files = [os.path.join(folder.folder, f) for f in files]
                metadata = exiftool.get_metadata(*files)

                pictures = None
                if folder.cover_art is None:
                    pictures = exiftool.get_cover_art(*files)

                for idx, mt in enumerate(metadata):
                    i += 1
                    song = self.from_metadata(mt)

                    cover = None
                    if folder.cover_art:
                        cover, c = CoverArt.get_or_create(file=folder.cover_art)
                    elif pictures:
                        cover = pictures[idx].get('Picture')
                        if cover is not None:
                            cover = b64_to_cover_art(cover)
                            cover, c = CoverArt.get_or_create(file=cover)

                    song.cover_art = cover
                    if song:
                        try:
                            song.save()
                        except Exception as e:
                            _mt = mt.copy()
                            if 'Picture' in _mt:
                                del _mt['Picture']

                            logger.debug("Could not add {} because of an error.\n{}".format(_mt, e))
                    else:
                        logger.debug('[Exception] Skipped {}'.format(mt))

                    print_info(i, total, no_duration=True)

        exiftool.terminate()

    @staticmethod
    def from_metadata(mt):
        if mt is None:
            logger.debug('Metadata is None')
            return

        name = mt.get('Title', mt.get('FileName'))
        file = mt.get('SourceFile')

        if name is None or file is None:
            logger.debug('[ERROR] Name and filepath must be specified')
            return

        band = mt.get('Band')
        if band is not None:
            band, c = AlbumArtist.get_or_create(name=band)

        album = mt.get('Album')
        if album is not None:
            if len(album) > 0:
                album, c = Album.get_or_create(name=album, album_artist=band)
            else:
                album = None

        artist = mt.get('Artist')
        if artist is not None:
            artist, c = Artist.get_or_create(name=artist)

        track = mt.get('Track')
        if track is not None:
            try:
                track = int(track)
            except (ValueError, TypeError):
                match = re.match(r'(\d+)(?:[/\\])(?:\d+)', track)
                if match is None:
                    logger.debug("Could not extract track number %s from %s" % (name, track))
                    track = None
                else:
                    track = match.groups([None])[0]

        year = mt.get('Year')
        if year is not None:
            if isinstance(year, str):
                if len(year) > 0:
                    year = int(year)
                else:
                    year = None

        song = FullSong(title=name,
                        link=file,
                        file_type='file',
                        album=album,
                        track=track,
                        artist=artist,
                        year=year,
                        duration=mt.get('Duration', 0.0))

        return song


class Dir:
    def __init__(self, folder, files):
        self.folder = folder
        self.files = files
        self.cover_art = None

    def filter_files(self, formats):
        cover_art = list(filter(lambda f: f.lower() in ['cover.jpg', 'cover.png', 'folder.jpg', 'folder.png'], self.files))
        if cover_art:
            self.cover_art = os.path.join(self.folder, cover_art[0])

        self.files = list(filter(lambda f: check_correct_extension(f, formats), self.files))


class DirDatabase:
    def __init__(self, db_name='data\\test_files.db'):
        self.database = APSWDatabase(db_name, autorollback=True)
