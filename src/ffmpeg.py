import shlex
import subprocess
import re


class FFmpeg:
    __slots__ = ['ffmpeg', 'file', 'channels', 'samplerate', '_process',
                 'running', 'filters', 'before_options', '_cmd']

    def __init__(self, file=None, path='ffmpeg', before_options='', channels=2,
                 samplerate=44100):
        self.ffmpeg = path
        self.file = file
        self.channels = channels
        self.samplerate = samplerate
        self._process = None
        self.running = False
        self.filters = ''
        self.before_options = before_options
        self._cmd = ''

    def add_filter(self, filter, arguments=None):
        if not self.filters:
            self.filters = ' -filter:a "'
        else:
            self.filters += ', {}'.format(filter)

        if arguments:
            self.filters += ':{}'.format(arguments)

    def create_subprocess(self, stdin=None, stderr=None):
        if not self._cmd:
            self.create_command()

        args = shlex.split(self._cmd)
        self._process = subprocess.Popen(args, stdout=subprocess.PIPE, stdin=stdin,
                                         stderr=stderr)

        self.running = True

        return self._process

    def create_command(self):
        before_opts = ''
        if isinstance(self.before_options, str):
            before_opts = ' ' + self.before_options
            before_opts = before_opts.replace('  ', ' ')

        cmd = '{}{} -i "{}" -vn -f s16le -ar {} -ac {} -loglevel warning{} pipe:1'.format(self.ffmpeg, before_opts, self.file,
                                                                                        self.samplerate, self.channels, self.filters)

        self._cmd = cmd
        return self._cmd

    def reset_seek(self):
        if '-ss' in self.before_options:
            self.before_options = re.sub('(-ss \d+\.\d*)|(-ss \d+:\d+:\d+\.\d*)',
                                         '', self.before_options)
            self.before_options = self.before_options.strip()

    def seek(self, seconds):
        seek_str = '-ss {}'.format(round(seconds, 3))
        if '-ss ' in self.before_options:
            self.before_options = re.sub('(-ss \d+\.\d*)|(-ss \d+:\d+:\d+\.\d*)', seek_str, self.before_options)
        else:
            self.before_options += ' ' + seek_str

        self.kill()

        self.create_command()
        return self.create_subprocess()

    def kill(self):
        if self.running:
            self._process.kill()
            self.running = False

    @property
    def process(self):
        return self._process

    @property
    def cmd(self):
        return self._cmd


class NoOptions(Exception):
    pass
