import hashlib
import os
from io import BytesIO
import shlex
import subprocess
import sys
import warnings
from itertools import zip_longest
import base64
from signal import *
import ntpath
import binascii

from PIL import Image, ImageChops

from src.exiftool import ExifTool


import logging
logger = logging.getLogger('debug')


# Print iterations progress
def print_info(iteration, total, total_duration='', no_duration=False, prefix='', suffix='', decimals=0, bar_length=100, extra_info='', max_size=None):
    """
    Call in a loop to create terminal progress bar
    @params:
        iteration   - Required  : current iteration (Int)
        total       - Required  : total iterations (Int)
        prefix      - Optional  : prefix string (Str)
        suffix      - Optional  : suffix string (Str)
        decimals    - Optional  : positive number of decimals in percent complete (Int)
        barLength   - Optional  : character length of bar (Int)
    """
    iteration = int(iteration) if decimals <= 0 else round(iteration, decimals)
    if no_duration:
        time_string = ('{0:.' + str(decimals) + 'f}% {}/{}').format(float(iteration)/total * 100, iteration, total)
    else:
        if not total_duration:
            time_string = parse_duration(iteration, total, decimals)
        else:
            time_string = parse_duration(iteration, decimals=decimals) + ' / ' + total_duration

    # We don't want the screen to fill if the current iteration is bigger than the total
    if iteration > float(total):
        iteration = float(total)

    filled_length = int(round(bar_length * iteration / float(total)))
    bar = '█' * filled_length + '-' * (bar_length - filled_length)
    if isinstance(max_size, int):
        max_size = max(0, max_size - 2)

    text = '\r' + ('%s |%s| %s %s %s' % (prefix, bar, time_string, suffix, extra_info))[0:max_size]
    sys.stdout.write(text)
    sys.stdout.flush()


def concatenate_numbers(x, *y):
    n = str(x)
    for num in y:
        n += str(num)

    return int(n)


# http://stackoverflow.com/a/8384788/6046713
def path_leaf(path):
    head, tail = ntpath.split(path)
    return tail or ntpath.basename(head)


def parse_duration(current, total=None, decimals=0):
    def _parse(time):
        m, s = divmod(time, 60)

        dec = decimals
        m = int(m)
        if dec > 0:
            s = round(s, dec)
            dec += 1  # So zfill doesn't fuck up
        else:
            s = int(s)

        h, m = divmod(m, 60)

        s = str(s).zfill(2 + dec)
        m = str(m)
        if h > 0:
            h = str(h).zfill(2)
            m = m.zfill(2)
            string = '{}:{}:{}'.format(h, m, s)
        else:
            string = '{}:{}'.format(m, s)

        return string

    current = _parse(current)
    time_string = current
    if total:
        total = _parse(total)
        time_string += '/' + total

    return time_string


def get_duration(file):
    if not isinstance(file, str):
        return

    file = shlex.quote(file)
    cmd = 'ffprobe -i {} -show_entries format=duration -v quiet -of csv="p=0"'.format(file)
    args = shlex.split(cmd)
    try:
        p = subprocess.Popen(args, stdout=subprocess.PIPE)
        out, err = p.communicate()
        dur = round(float(out), 2)
    except Exception as e:
        print('Exception while getting duration. %s' % e)
        return None

    return dur


def read_formats(path):
    if os.path.exists(path):
        with open(path, 'r') as f:
            lines = f.read().split('\n')
        return lines


def get_supported_formats():
    path = os.path.join(os.getcwd(), 'cache', 'formats.txt')
    lines = read_formats(path)
    if lines is not None:
        return lines

    p = subprocess.Popen('ffmpeg -formats'.split(' '), stdout=subprocess.PIPE)
    out, err = p.communicate()
    out = out.decode('utf-8')
    formats = []
    for l in out.splitlines()[4:]:
        l = l.strip()
        try:
            demuxer = 'D' in l[0:3]
            if not demuxer:
                continue

            format_ = map(str.strip, l[3:].split(' ')[0].split(','))
            formats.append('\n'.join(format_))
        except Exception as e:
            print('failed to add format %s\n%s' % (l, e))

    with open(path, 'w') as f:
        f.write('\n'.join(formats) + '\n')

    return formats


def get_supported_audio_formats():
    audio_formats = os.path.join(os.getcwd(), 'src', 'audio_format_list.txt')
    formats = get_supported_formats()
    if not os.path.exists(audio_formats):
        warnings.warn('audio_format_list.txt not found in src folder')
        return formats

    supported_formats = os.path.join(os.getcwd(), 'cache', 'audio_formats.txt')
    if not os.path.exists(supported_formats):
        supported = set(formats)
        with open(audio_formats) as f:
            listed = set(f.read().split('\n'))

        formats = supported.intersection(listed)

        with open(supported_formats, 'w') as f:
            f.write('\n'.join(formats) + '\n')

        return list(formats)

    else:
        return read_formats(supported_formats)


def get_metadata(file):
    cmd = 'exiftool "{}"'.format(file)
    p = subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE)
    out, err = p.communicate()
    out = out.decode('utf-8')
    out = out.split('\r\n')
    metadata = {}
    for item in out:
        if item:
            k, v = item.split(':', 1)
            metadata[k.strip()] = v.strip()

    return metadata


# Taken from https://docs.python.org/3/library/itertools.html#recipes
def grouper(iterable, n, fillvalue=None):
    args = [iter(iterable)] * n
    return zip_longest(*args, fillvalue=fillvalue)


def at_exit(func, *args, **kwargs):
    from functools import partial
    func = partial(func, *args, **kwargs)

    for sig in (SIGABRT, SIGINT, SIGTERM):
        signal(sig, func)


def run_on_exit(func, *args, **kwargs):
    print('Cleaning up before shutting down. Please wait.')
    func(*args, **kwargs)
    print('Exiting app')
    if kwargs.pop('__os_exit', False):
        os._exit(0)
    else:
        sys.exit()


def run_funcs_on_exit(funcs, *args, **kwargs):
    print('Cleaning up before shutting down. Please wait.')
    for func, args, kwargs in funcs:
        func(*args, **kwargs)

    print('Exiting app')
    os._exit(0)


def md5_hash(file):
    md5 = hashlib.md5()
    for chunk in iter(lambda: file.read(4096), b""):
        md5.update(chunk)

    return md5.hexdigest()


def check_correct_extension(file, formats):
    ext = path_leaf(file).split('.')
    if len(ext) < 2:
        return True

    if formats is None:
        raise Exception('Format file is not generated. Files cannot be checked')

    ext = ext[-1]
    if ext in formats:
        return True
    else:
        logger.debug('Skipping file %s' % file)
        return False


def trim_image(im):
    bg = Image.new(im.mode, im.size, im.getpixel((0,0)))
    diff = ImageChops.difference(im, bg)
    diff = ImageChops.add(diff, diff, 2.0, -100)
    bbox = diff.getbbox()
    if bbox:
        return im.crop(bbox)


def get_file_cover_art(metadata, file):
    path = os.path.join(os.getcwd(), 'cache', 'cover_art', 'embedded')
    if not os.path.exists(path):
        os.makedirs(path)

    if 'Picture' not in metadata:
        exiftool = ExifTool()
        exiftool.start()

        pic = exiftool.get_cover_art(file)
        exiftool.terminate()

        if not pic:
            return None, None

    else:
        pic = metadata['Picture']

    buffer = BytesIO(pic)
    md5 = md5_hash(buffer)
    buffer.seek(0)

    fname = os.path.join(path, md5)
    if os.path.exists(fname):
        return fname

    with open(fname, 'wb') as f:
        for chunk in iter(lambda: buffer.read(4096), b""):
            f.write(chunk)

    return fname


def b64_to_cover_art(s):
    path = os.path.join(os.getcwd(), 'cache', 'cover_art', 'embedded')
    if not os.path.exists(path):
        os.makedirs(path)

    if s[:7] == 'base64:':
        s = s[7:]

    b = binascii.a2b_base64(s)
    buffer = BytesIO(b)

    md5 = md5_hash(buffer)
    buffer.seek(0)

    fname = os.path.join(path, md5)
    if os.path.exists(fname):
        return fname

    with open(fname, 'wb') as f:
        for chunk in iter(lambda: buffer.read(4096), b""):
            f.write(chunk)

    return fname
