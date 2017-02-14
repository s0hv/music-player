import logging
import threading

import pyHook
from pyHook.HookManager import GetKeyState
from pyHook.HookManager import HookConstants

import pythoncom

logger = logging.getLogger('debug')


class HeldKeyError(Exception):
    pass


class KeyCodes:
    key_to_id = {
        'backspace': 8,
        'tab': 9,
        'enter': 13,
        'shift': 16,
        'ctrl': 17,
        'alt': 18,
        'pause/break': 19,
        'caps lock': 20,
        'escape': 27,
        'page up': 33,
        'page down': 34,
        'end': 35,
        'home': 36,
        'left arrow': 37,
        'up arrow': 38,
        'right arrow': 39,
        'down arrow': 40,
        'insert': 45,
        'delete': 46,
        'left window key': 91,
        'right window key': 92,
        'select key': 93,
        'numpad 0': 96,
        'numpad 1': 97,
        'numpad 2': 98,
        'numpad 3': 99,
        'numpad 4': 100,
        'numpad 5': 101,
        'numpad 6': 102,
        'numpad 7': 103,
        'numpad 8': 104,
        'numpad 9': 105,
        'multiply': 106,
        'add': 107,
        'subtract': 109,
        'decimal point': 110,
        'divide': 111,
        'f1': 112, 'f2': 113,
        'f3': 114,
        'f4': 115,
        'f5': 116,
        'f6': 117,
        'f7': 118,
        'f8': 119,
        'f9': 120,
        'f10': 121,
        'f11': 122,
        'f12': 123,
        'num lock': 144,
        'scroll lock': 145,
        'semi-colon': 186,
        'equal sign': 187,
        'comma': 188,
        'dash': 189,
        'period': 190,
        'forward slash': 191,
        'grave accent': 192,
        'open bracket': 219,
        'back slash': 220,
        'close bracket': 221,
        'single quote': 222}

    id_to_key = {v: k for k, v in key_to_id.items()}

    @classmethod
    def key_from_id(cls, key_id):
        key = KeyCodes.id_to_key.get(key_id, None)
        if key is None:
            try:
                key = chr(key_id)
            except ValueError:
                return None

        return key

    @classmethod
    def id_from_key(cls, key_name: str):
        key_name = key_name.lower()
        key = KeyCodes.key_to_id.get(key_name, None)
        return key


class KeyBind:
    def __init__(self, key, func, name, modifiers=(), alt=False, threaded=False):
        self.key = key
        self._func = func
        self.alt = alt
        self.modifiers = modifiers
        self.name = name
        self.threaded = threaded
        self._func_lock = threading.Lock()

    def run_func(self):
        self._func()

    def lock_func(self, blocking=True):
        return self._func_lock.acquire(blocking)

    def unlock_func(self):
        if self._func_lock.locked():
            self._func_lock.release()

    @property
    def locked(self):
        return self._func_lock.locked()

    @property
    def lock(self):
        return self._func_lock

    def __str__(self):
        s = KeyCodes.key_from_id(self.key)

        if self.alt:
            s += ' + Alt'

        for modifier in self.modifiers:
            s += ' + {}'.format(KeyCodes.key_from_id(modifier))

        return s


class KeyBinds(threading.Thread):
    def __init__(self, hwnd=0, global_binds=False, **kwargs):
        super().__init__(**kwargs)
        self.global_binds = global_binds
        self._hwnd = hwnd
        self.keybinds = {}

    def _init(self):
        self.hm = pyHook.HookManager()

        if self.global_binds:
            self.hm.KeyDown = self._on_keyboard_event
        else:
            print('Press any key to set the currently active window to receive non global keybinds.')
            self.hm.KeyDown = self._set_player_window

        self.hm.HookKeyboard()
        self._lock = threading.Lock()
        logger.debug(vars(self))

    def add_keybind(self, keybind):
        if keybind.key in self.keybinds:
            keys = self.keybinds[keybind.key]
            key_s = str(keybind)
            for idx, key in enumerate(keys.copy()):
                k = str(key)
                if k == key_s:
                    keys.pop(idx)
                    keys.append(keybind)
                    logger.debug('removing old key {}, {}'.format(self.keybinds[key].name, key))
                    print('removing old key {}, {}'.format(self.keybinds[key].name, key))
                    break
        else:
            self.keybinds[keybind.key] = [keybind]

    @property
    def hwnd(self):
        return self._hwnd

    @hwnd.setter
    def hwnd(self, hwnd):
        self._hwnd = hwnd

    def _set_player_window(self, event):
        logger.info('Set the window id to {} from {}'.format(event.Window, self.hwnd))
        self.hwnd = event.Window
        self.hm.KeyDown = self._on_keyboard_event
        print('\nWindow set to %s' % event.WindowName)
        return False

    @staticmethod
    def get_hook_constant(key):
        if isinstance(key, str):
            return HookConstants.VKeyToID(key)
        elif isinstance(key, int):
            return key
        else:
            raise HeldKeyError('Held key must be an int representing the ID of the key or str representing the vk code of the key')

    def _check_window_active(self, hwnd):
        if self.global_binds:
            return True

        return hwnd == self._hwnd

    def _on_keyboard_event(self, event):
        if not self._check_window_active(event.Window):
            return True

        keybinds = self.keybinds.get(event.KeyID, None)
        if keybinds is None:
            return True

        for keybind in keybinds:
            if keybind.alt and not event.Alt:
                continue

            for modifier in keybind.modifiers:
                if modifier is None:
                    print('modifier is None')
                    continue

                modifier = int(hex(modifier), 16)
                is_pressed = GetKeyState(modifier)
                if not is_pressed:
                    break
            else:
                if keybind.lock_func(False):
                    t = None
                    try:
                        if keybind.threaded:
                            t = threading.Thread(target=keybind.run_func, args=(keybind.lock, ))
                            t.start()
                        else:
                            keybind.run_func()
                    except Exception as e:
                        logger.info('Error in keybind func: %s' % e)
                    finally:
                        if t is None:
                            keybind.unlock_func()

        return True

    def run(self):
        self._init()
        pythoncom.PumpMessages()

    def stop(self):
        self.hm.UnhookKeyboard()
