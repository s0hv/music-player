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


class SongList(list):
    def __init__(self, iterable=(), cls=None):
        list.__init__(self, iterable)
        self.cls = cls


class ScrollingIconPage:
    def __init__(self, collection, part_length=10):
        self.collection = collection or []
        self._pages = []
        self._loaded_pages = []
        self.page_length = part_length*3
        self.part_length = part_length
        self._current_page = 0

        self.set_up_pages()

    def set_collection(self, collection):
        self.collection = collection or []
        self.clear_pages()
        self.set_up_pages()

    def set_up_pages(self):
        self._pages = []
        for idx in range(0, len(self.collection), self.part_length):
            self._pages.append(self.collection[idx:idx+self.part_length])

    @property
    def current_pages(self):
        return self.pages_from_index(self._current_page)

    @property
    def current_page(self):
        return self._current_page

    def next_page(self):
        if self.page_count >= self._current_page+1:
            print('End of pages reached')
            return

        self._current_page += 1

    def append_item(self, item):
        if self.page_count == 0:
            last_page = []
            self._pages.append(last_page)
        else:
            last_page = self._pages[-1]

        if len(last_page) < self.part_length:
            last_page.append(item)
        else:
            last_page = [item]
            self._pages.append(last_page)

        count = self.page_count
        if self._current_page in [count-1, count-2]:
            item.load_icon()

    def clear_pages(self):
        self._unload_pages(self._loaded_pages)
        self._pages.clear()
        self._current_page = 0

    def pages_from_index(self, index: int):
        return self._pages[max(0, index - 1):index + 2]

    def load_pages(self, page_index):
        if page_index < 0:
            return

        load = self.pages_from_index(page_index)
        unload = self._difference(self._loaded_pages, load)
        self._load_pages(load)
        self._unload_pages(unload)
        self._current_page = page_index

    @staticmethod
    def _intersection(l1, l2):
        intersecting = []
        for item in l1:
            if item in l2:
                intersecting.append(item)

        return intersecting

    # Not symmetric difference
    @staticmethod
    def _difference(l1, l2):
        different = []
        for item in l1:
            if item not in l2:
                different.append(item)

        return different

    def _unload_pages(self, pages):
        for page in pages:
            for item in page:
                item.unload_icon()

            try:
                self._loaded_pages.remove(page)
            except:
                pass

    def _load_pages(self, pages):
        for page in pages:
            for item in page:
                item.load_icon()

            self._loaded_pages.append(page)

    @property
    def page_count(self):
        return len(self._pages)

    def __len__(self):
        return len(self.collection)


class Item:
    def __init__(self):
        self.loaded = False

    def unload_icon(self):
        self.loaded = False
        print('unloaded')

    def load_icon(self):
        if not self.loaded:
            print('loaded')
            self.loaded = True

        else:
            print('already loaded')
