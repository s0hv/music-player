import audioop
import logging
import os
import shlex
import subprocess
import sys
import threading
import time
import traceback
from collections import deque

import pyaudio

from src import database
from src.downloader import DownloaderPool
from src.globals import GV
from src.queue import LockedQueue
from src.song import Song
from src.utils import print_info, get_duration

logger = logging.getLogger('debug')

# Don't change these if you don't know what you are doing
FORMAT = pyaudio.paInt16
CHANNELS = 2
WIDTH = 4


def get_columns():
    try:
        cols = os.get_terminal_size().columns
    except:
        return None

    return cols


class Deque(deque):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def full(self):
        return len(self) == self.maxlen


class StreamPlayer(threading.Thread):
    def __init__(self, buff, stream, rate, volume=1.0, after=None, on_write_frame=None,
                 remove_start_silence=False, remove_end_silence=False, on_pause=None,
                 on_resume=None, **kwargs):

        super().__init__(**kwargs)
        self.buff = buff
        self.rate = rate
        self._audio_buffer = Deque(maxlen=10)
        self._volume = volume
        self._resume = threading.Event()
        self._resume.set()
        self._stream_finished = threading.Event()
        self._end = threading.Event()
        self.seeking = threading.Event()
        self.stream = stream
        self.after = after
        self._loops = 0
        self._bytes_per_second = self.rate * (16 / 8) * CHANNELS
        self.remove_start_silence = remove_start_silence
        self.remove_end_silence = remove_end_silence
        self.on_pause = on_pause
        self.on_resume = on_resume

        if callable(on_write_frame):
            self._on_write = on_write_frame
        else:
            self._on_write = None

    def _buffer_next(self):
        if not self._stream_finished.is_set() and not self._audio_buffer.full() and not self.seeking.is_set():
            d = self.buff.read(self.rate)

            if len(d) > 0:
                self._audio_buffer.append(d)
            else:
                if self.remove_end_silence:
                    removed = 0
                    buffer = list(self._audio_buffer)
                    buffer.reverse()
                    for data in buffer:
                        rms = audioop.rms(data, 2)
                        if rms <= 50:
                            removed += 1
                            self._audio_buffer.pop()
                            self._loops += 1
                        else:
                            break

                    logger.debug('Removed %s loops' % removed)

                self._stream_finished.set()

    def _start_playing(self):
        if self.remove_start_silence:
            # Drop all data that is silent
            while not self._end.is_set():
                d = self.buff.read(self.rate)
                if len(d) > 0:
                    rms = audioop.rms(d, 2)
                    # 50 is the silence detection sensitivity.
                    if rms > 50:
                        self._audio_buffer.append(d)
                        break
                    self._loops += 1
                else:
                    self._stream_finished.set()
                    break

            logger.debug('Removed %s loops from start' % self._loops)

        while not self._end.is_set():
            if not self._resume.is_set():
                while self.can_buffer:
                    self._buffer_next()
                    if self._resume.is_set():
                        break

                self._resume.wait()
                continue

            if self.seeking.is_set():
                self.seeking.wait()

            if self._audio_buffer:
                data = self._audio_buffer.popleft()
                while self.can_buffer:
                    self._buffer_next()
            else:
                if self.seeking.is_set():
                    continue

                if self._stream_finished.is_set():
                    self.stop()
                    break

                data = self.buff.read(self.rate)
                while not self._audio_buffer.full() and not self._stream_finished.is_set():
                    self._buffer_next()

            if not len(data) > 0:
                if self.seeking.is_set():
                    continue

                self.stop()
                break

            if self._volume != 1.0:
                data = audioop.mul(data, 2, self._volume)

            self.stream.write(data)
            self._loops += 1
            if self._on_write:
                    self._on_write(self)

    @property
    def can_buffer(self):
        return not self._audio_buffer.full() and not self._stream_finished.is_set() and not self._end.is_set() and not self.seeking.is_set()

    def run(self):
        try:
            self._start_playing()
        except:
            logger.exception('Exception in stream player')
            self.stop()

    def seek(self, seconds, ffmpeg):
        self.seeking.set()
        self._audio_buffer.clear()
        self._stream_finished.clear()
        self._end.clear()
        self._loops = seconds * self.bytes_per_second / self.rate
        self.buff = ffmpeg.seek(seconds).stdout
        self.seeking.clear()

    @property
    def bytes_per_second(self):
        return self._bytes_per_second

    def pause(self):
        self._resume.clear()
        if self.on_pause:
            self.on_pause(self)

    @property
    def loop_time(self):
        return self.rate / self.bytes_per_second

    @property
    def paused(self):
        return not self._resume.is_set()

    def resume(self):
        self._resume.set()
        if self.on_resume:
            self.on_resume(self)

    @property
    def volume(self):
        return self._volume

    @volume.setter
    def volume(self, value):
        self._volume = value

    @property
    def loops(self):
        return self._loops

    @property
    def duration(self):
        return self._loops * self.rate / self.bytes_per_second

    def stop(self):
        self._end.set()
        if self.after:
            self.after()


class MusicPlayer(threading.Thread):
    def __init__(self, db: database.DBHandler, default_vol=0.5, **kwargs):
        super().__init__(**kwargs)
        self.volume = default_vol
        self.stream_player = None
        self._not_playing = threading.Event()
        self._not_playing.set()
        self._stop = threading.Event()
        self._end_finalized = threading.Event()
        self.db = db

    def change_volume(self, add=False):
        try:
            amount = 0.01 if add else -0.01

            if self.stream_player is None:
                return

            vol = self.stream_player.volume + amount
            if vol < 0 or vol > 2:
                return

            vol = round(vol, 2)
            self.volume = vol
            self.stream_player.volume = vol
        except Exception as e:
            print('Exception while changing volume: %s' % e)

    def pause(self):
        if self.stream_player is None:
            return

        if not self.stream_player.paused:
            self.stream_player.pause()
            return False
        else:
            self.stream_player.resume()
            return True

    def wait_until_stop(self):
        self.not_playing.wait()

    def play_next_song(self, lock=None):
        if self.stream_player is None:
            return
        self.stream_player.stop()
        if lock:
            lock.release()

    def on_stop(self):
        # Gets rid of the duration meter from cmd
        sys.stdout.write('\r')
        sys.stdout.flush()

        self.not_playing.set()

    @property
    def not_playing(self):
        return self._not_playing

    def play_current(self, after, stderr=None, stdin=None, **kwargs):
        samplerate = self.current.create_stream()
        self.current.ffmpeg.create_command()
        p = self.current.ffmpeg.create_subprocess(stderr=stderr, stdin=stdin)
        self.stream_player = StreamPlayer(p.stdout, self.current.stream, samplerate, self.volume, after=after, **kwargs)
        self._not_playing.clear()
        self.stream_player.start()

    def create_player(self, filename, stderr=None, stdin=None, after=None,
                      on_write_frame=None, options=None, before_options=None,
                      remove_start_silence=False, remove_end_silence=False):

        if not isinstance(before_options, str):
            before_options = ''
        else:
            before_options = ' ' + before_options

        if not isinstance(options, str):
            options = ''
        else:
            options = ' ' + options

        file = shlex.quote(filename)
        samplerate = self.current.ffmpeg.samplerate
        cmd = '_ffmpeg{} -i {} -vn -f s16le -ar {} -ac {} -loglevel warning{} pipe:1'
        cmd = cmd.format(before_options, file, samplerate, CHANNELS, options)
        args = shlex.split(cmd)
        p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=stderr, stdin=stdin)

        return StreamPlayer(p.stdout, self.current.stream, samplerate, self.volume, after=after, on_write_frame=on_write_frame,
                            remove_start_silence=remove_start_silence, remove_end_silence=remove_end_silence)

    def play(self, filename, stderr=None, stdin=None, after=None, on_write_frame=None,
             options=None, before_options=None, remove_start_silence=False,
             remove_end_silence=False):

        after = self.on_stop if not after else after
        self.stream_player = self.create_player(filename, stdin=stdin, after=after,
                                                stderr=stderr, on_write_frame=on_write_frame,
                                                options=options, before_options=before_options,
                                                remove_start_silence=remove_start_silence,
                                                remove_end_silence=remove_end_silence)

        self._not_playing.clear()
        self.stream_player.start()

    @staticmethod
    def is_file(item):
        return item.file_type == 'file'

    @property
    def running(self):
        return not self._stop.is_set()

    @staticmethod
    def _set_dur(item, file):
        duration = get_duration(file)
        if duration is None:
            return

        item.duration = duration

        return duration

    def _init(self):
        self.current = None
        self.next = None
        self.duration = 0
        self.curr_name = ''
        self.next_name = ''

    def exit_player(self, lock=None):
        try:
            self._stop.set()
            if self.stream_player:
                self.stream_player.stop()
            self._end_finalized.wait(timeout=10)
        except Exception as e:
            print('Exception while closing player\n%s' % e)
        finally:
            if lock:
                lock.release()


class CMDPlayer(MusicPlayer):
    def __init__(self, db, default_vol=0.5, max_workers=3, **kwargs):
        raise NotImplementedError('CMDPlayer is currently not implimented correctly')
        super().__init__(db, default_vol, **kwargs)
        self._print_lock = threading.Lock()
        self.downloader = DownloaderPool(max_workers)
        logger.debug('CMDPlayer thread: {}'.format(threading.get_ident()))

    def _init(self):
        super()._init()
        self.printer = PrintDuration()

    def _update_duration(self, *args):
        if self._print_lock.acquire(False):
            try:
                self.printer.print_next()
            except Exception as e:
                print(e)
            self._print_lock.release()

    @staticmethod
    def cmd_text(s):
        """"
        Re-encodes a string so it can be displayed in cmd.
        """
        s = s.encode(sys.stdout.encoding, 'ignore').decode(sys.stdout.encoding)
        try:
            s = s[0:get_columns()]
        except:
            logger.exception('Error while creating cmd text')
        finally:
            return s

    def _get_next_info(self):
        future = super()._get_next_info()
        self.next_name = self.cmd_text(self.next_name)
        self.printer.next_name = self.next_name
        return future

    def _set_up_current(self, future):
        file = super()._set_up_current(future)
        self.printer.dur_parsed = self.current.duration_formatted
        self.printer.duration = self.duration
        return file

    def on_stop(self):
        sys.stdout.write('\r')
        sys.stdout.flush()

        try:
            p = self.current.ffmpeg.process
            p.kill()
            if p.poll() is None:
                p.communicate()
        except Exception as e:
            print('Exception while stopping ffmpeg\n%s' % e)

        self.not_playing.set()

    def test(self, file):
        cmd = '{0} -i {1} -t 00:10:00 -filter:a "volumedetect" -vn -sn -f null /dev/null'.format(
            '_ffmpeg', file)

        args = shlex.split(cmd)
        process = subprocess.Popen(args, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)

        print(process.communicate())

    def _audio_loop(self):
        self._init()
        self.printer.start()
        future = self._get_next_info()
        while future is False:
            future = self._get_next_info()
            time.sleep(1)

        if future is None:
            self._next_ready.set()
        else:
            future.add_done_callback(self._after_dl)

        f = open('errors.txt', 'a')
        while self.running:
            self._next_ready.wait()
            self._set_up_current(future)
            name = self.cmd_text(self.current.name)
            print('\rNow playing: {}'.format(name))
            self.next_name = ''
            self.printer.next_name = ''

            self.play_current(after=self.on_stop, stderr=f, remove_start_silence=True,
                              remove_end_silence=True, on_write_frame=self._update_duration)
            self.printer.stream_player = self.stream_player

            future = self._get_valid_next()
            self._next_ready.wait()
            while self.dl_error.is_set():
                future = self._get_valid_next()
                self._next_ready.wait()

            self.wait_until_stop()
            if self.stream_player.duration > 0.5 * self.duration:
                self.current.play_count += 1

        try:
            f.close()
        except Exception as e:
            print('Exception while closing audio loop\n%s' % e)
        finally:
            self._end_finalized.set()

    def run(self):
        try:
            self._audio_loop()
        except Exception as e:
            traceback.print_exc()
            print('Exception while running music player: %s ' % e)


class GUIPlayer(MusicPlayer):
    IN_ORDER = 0
    SHUFFLED = 1
    AUTO_DJ = 2

    def __init__(self, duration_fn, on_next, on_start, session, mode=AUTO_DJ, *args, **kwargs):
        """

        Args:
            duration_fn:
                A callable that StreamPlayer calls after every audio write
            on_next:
                A callable that is called when the song changes
            on_start:
                A callable that is called after stream_player.start() has been called
            session:
                The sessionmanager that this will use. See class SessionManager in src/session
            mode:
                The mode in which new _songs are gotten. All of the options for this
                are global variables in this class
            *args:
                args that are passed to class MusicPlayer
            **kwargs:
                kwargs that are passed to threading.Thread
        """
        super().__init__(*args, **kwargs)
        self.duration_fn = duration_fn
        self.on_next = on_next
        self.on_start = on_start
        self.session = session
        self.queue_mode = mode

        self.future = None
        self.index = 0
        self.queue = None

        self.queue_modes = {self.IN_ORDER: 'd',
                            self.SHUFFLED: 'get_from_shuffled',
                            self.AUTO_DJ: 'get_random_song'}
        self.queues = {self.SHUFFLED: 'queue'}
        self._next_queue = LockedQueue()
        self.current = None
        self.unpaused = threading.Event()

    def skip_to(self, idx, song_item=None):
        if idx < 0:
            return

        self._next_queue.lock()
        if song_item is None:
            try:
                song = self.queue[idx]
            except IndexError:
                self._next_queue.unlock()
                return
        else:
            song = song_item.song

        logger.debug('skip_to %s' % idx)
        print(song_item)
        self._next_queue.force_append(song)
        self.db.queue_pos = idx + 1
        self.index = idx
        self.play_next_song()
        self.unpaused.set()

    def update_queue(self, queue=GV.MainQueue, index=0):
        self.queue = self.session.queues.get(queue)
        self.index = index
        self._next_queue.clear()

    def play_from_search(self, info):
        song = self.db.get_temp_song(info.get('title', 'Untitled'),
                                     info.get('webpage_url'), item_type='link')

        item = Song(song, self.db, self.session.downloader)
        item.info = info
        self._next_queue.lock()
        self._next_queue.force_append(item)
        self.play_next_song()
        self.unpaused.set()

    def get_next(self):
        self.index += 1
        try:
            song = self.queue[self.index]
        except IndexError:
            self.unpaused.clear()
            return

        song.download_song()
        self._next_queue.append(song)

    def _init(self):
        if self.queue is None:
            self.queue = self.session.queues.get(GV.MainQueue, deque())
        self.index = self.session.index

    def _audio_loop(self):
        self._init()

        song = None
        if self.queue_mode == self.SHUFFLED:
            try:
                song = self.queue[self.index]
            except IndexError:
                pass
        else:
            history = self.db.history
            try:
                song = history.pop()
            except IndexError:
                pass

        if song is not None:
            self._next_queue.append(song)
            self.on_next.emit(song, self.queue_mode == self.SHUFFLED,
                              self.index, False, self.queue_mode == self.AUTO_DJ)

        f = open('errors.txt', 'a')

        while self.running:
            self.unpaused.wait()
            if not self.running:
                break

            if len(self._next_queue) > 0:
                self.current = self._next_queue.pop()
                self._next_queue.clear()
                self._next_queue.unlock()
            else:
                self.get_next()
                continue

            logger.debug('Downloading song {} {}'.format(self.current.name, self.current.link))
            self.current.download_song()
            logger.debug('DL complete. Calling on next')
            try:
                self.on_next.emit(self.current, self.queue_mode == self.SHUFFLED and self.current.index >= 0,
                                  self.current.index, True, self.queue_mode == self.AUTO_DJ)
            except Exception as e:
                logger.exception('on_next exception %s' % e)

            if not self.current.dl_finished:
                self.current.wait_until_ready()

            if self.current.dl_error:
                logger.debug('DL error')
                self.get_next()
                continue

            if self.current.index >= 0:
                self.index = self.current.index

            logger.debug('Starting player')
            self.play_current(after=self.on_stop, stderr=f,
                              remove_start_silence=True,
                              remove_end_silence=True,
                              on_write_frame=self.duration_fn, daemon=True)
            logger.debug('Started player')
            self.get_next()

            self.wait_until_stop()
            if self.stream_player.duration > 0.5 * self.current.duration:
                self.current.play_count += 1

        try:
            f.close()
        except Exception as e:
            print('Exception while closing audio loop\n%s' % e)
        finally:
            self._end_finalized.set()

    def exit_player(self, lock=None):
        try:
            self._stop.set()
            if self.stream_player:
                self.stream_player.stop()

            self.unpaused.set()
            self._end_finalized.wait(timeout=10)
        except Exception as e:
            print('Exception while closing player\n%s' % e)
        finally:
            if lock:
                lock.release()

    def play_current(self, after, stderr=None, stdin=None, **kwargs):
        if self.current is None:
            return

        samplerate = self.current.create_stream()
        self.current.ffmpeg.reset_seek()
        self.current.ffmpeg.create_command()
        p = self.current.ffmpeg.create_subprocess(stderr=stderr, stdin=stdin)
        self.stream_player = StreamPlayer(p.stdout, self.current.stream, samplerate, self.volume, after=after, **kwargs)
        self._not_playing.clear()
        self.stream_player.start()
        self.on_start(self)

    def run(self):
        try:
            self._audio_loop()
        except Exception as e:
            traceback.print_exc()
            print('Exception while running music player: %s ' % e)

    def on_stop(self):
        try:
            self.current.ffmpeg.kill()
        except Exception as e:
            print('Exception while stopping ffmpeg\n%s' % e)

        self.not_playing.set()


class PrintDuration(threading.Thread):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._print_next = threading.Event()
        self._printing = threading.Event()
        self.stream_player = None
        self.curr_dur = 0
        self.next_name = ''
        self.dur_parsed = ''
        self.duration = 0

    def _print_job(self):
        while self._printing.is_set():
            self._print_next.clear()
            try:
                curr_dur = self.stream_player.duration if not self.curr_dur else self.curr_dur
                size = get_columns()

                xtra_info = 'Volume: {}  Next: {}'.format(self.stream_player.volume, self.next_name)
                print_info(curr_dur, self.duration, self.dur_parsed, prefix='Duration',
                           bar_length=50, decimals=1, extra_info=xtra_info, max_size=size)
            except:
                pass
            self._print_next.wait()

    def print_next(self):
        self._print_next.set()

    def run(self):
        try:
            self._printing.set()
            self._print_job()
        except:
            logger.exception('Exception in printing loop')
