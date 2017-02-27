import hashlib
import os
import shlex
import subprocess
import sys
from itertools import zip_longest
from signal import *

from PIL import Image, ImageChops


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
        time_string = ('{0:.' + str(decimals) + 'f}%').format(float(iteration)/total * 100)
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
        print('Exception while getting duration' % e)
        return None

    return dur


def get_supported_formats():
    path = os.path.join(os.getcwd(), 'cache', 'formats.txt')
    if os.path.exists(path):
        with open(path, 'r') as f:
            lines = f.read().split('\n')
        return lines

    p = subprocess.Popen('ffmpeg -formats'.split(' '), stdout=subprocess.PIPE)
    out, err = p.communicate()
    out = out.decode('utf-8')
    formats = []
    for l in out.split('\r\n ')[4:]:
        if 'D' in l[0:1]:
            formats.append(l[3:].split(' ')[0])

    with open(path, 'w') as f:
        f.write('\n'.join(formats) + '\n')

    return formats


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


def trim_image(im):
    bg = Image.new(im.mode, im.size, im.getpixel((0,0)))
    diff = ImageChops.difference(im, bg)
    diff = ImageChops.add(diff, diff, 2.0, -100)
    bbox = diff.getbbox()
    if bbox:
        return im.crop(bbox)