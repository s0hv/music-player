from collections import deque


class LockedQueue(deque):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lock = False

    def append(self, *args, **kwargs):
        if not self.locked:
            super().append(*args, **kwargs)

    def appendleft(self, *args, **kwargs):
        if not self.locked:
            super().appendleft(*args, **kwargs)

    def force_append(self, *args, **kwargs):
        super().append(*args, **kwargs)

    def force_appendleft(self, *args, **kwargs):
        super().appendleft(*args, **kwargs)

    def lock(self):
        self._lock = True

    def unlock(self):
        self._lock = False

    @property
    def locked(self):
        return self._lock
