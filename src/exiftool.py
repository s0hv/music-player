import json
import os
import subprocess
import logging

logger = logging.getLogger('debug')


class ExifTool:
    """
    ExifTool class that is used to get song metadata
    """
    sentinel = b"{ready}"

    def __init__(self, executable="exiftool"):
        self.executable = executable
        self.running = False

    def start(self):
        with open('errors.txt', 'a') as err:
            self._process = subprocess.Popen([self.executable, "-stay_open", "True",
                                              "-@", "-", "-common_args", "-n",
                                              "-charset", "filename=UTF-8", "-b"],
                                              stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                              stderr=err)

        self.running = True

    def terminate(self):
        if not self.running:
            return

        self._process.stdin.write(b"-stay_open\nFalse\n")
        self._process.stdin.flush()
        self._process.communicate()

        del self._process
        self.running = False

    @staticmethod
    def get_filenames(*files):
        filenames = []
        for file in files:
            if isinstance(file, bytes):
                filenames.append(file)

            elif isinstance(file, str):
                filenames.append(file.encode('utf-8'))

            else:
                raise TypeError('Filename must be bytes or str')

        return b"\n".join(filenames)

    def execute(self, *args):
        if not self.running:
            print('[ERROR] ExifTool is not running')
            return

        args = b"\n".join(args + (b"-execute\n",))
        self._process.stdin.write(args)
        self._process.stdin.flush()
        output = b""
        fd = self._process.stdout.fileno()
        while not output.strip().endswith(self.sentinel):
            output += os.read(fd, 4096)

        return output.strip()[:-len(self.sentinel)]

    def get_cover_art(self, *files):
        args = (b"-Picture", b"-j")
        pics = self.execute(*args, self.get_filenames(*files)).decode('utf-8')
        try:
            return json.loads(pics)
        except Exception as e:
            logger.info('Could not get metadata. {}\n{}\n{}'.format(', '.join(files), pics, e))
            return {}

    def get_metadata(self, *filenames):
        args = (b"-j",)

        js = self.execute(*args, self.get_filenames(*filenames)).decode('utf-8')
        if js is not None:
            try:
                return json.loads(js)
            except Exception as e:
                logger.info('Could not get metadata. {}\n{}\n{}'.format(', '.join(filenames), js, e))
                return {}