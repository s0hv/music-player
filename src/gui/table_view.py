from PyQt5.QtCore import QAbstractTableModel, QVariant, Qt, QTimer, pyqtSlot, pyqtSignal
from PyQt5.QtWidgets import QMessageBox, QTableView, QLineEdit


class Column:
    def __init__(self, header, sql_column, name, **kwargs):
        self.header = header
        self.sql_column = sql_column
        self.name = name
        self.editable = kwargs.pop('editable', False)
        self.fallback = kwargs.pop('fallback', None)


class Filter:
    def __init__(self, keyword=None, column=None):
        self.keyword = keyword
        self.column = column

    def remove_filter(self):
        self.keyword = None

    def set_filter(self, keyword):
        self.keyword = keyword

    def keyword_and_column(self):
        return self.keyword, self.column


class SQLAlchemyTableModel(QAbstractTableModel):
    set_filter = pyqtSignal(str, int, bool)

    def __init__(self, db_handler, columns, query):
        super().__init__()

        self.db = db_handler
        self.fields = columns
        self.query = query
        self.results = None

        self.count = None
        self._sort = None
        self._filters = [Filter(column=i) for i in range(0, self.columnCount())]
        self.set_filter.connect(self._set_filter)

        self.refresh()

    def headerData(self, col, orientation, role=None):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return QVariant(self.fields[col].header)
        else:
            return QVariant()

    def flags(self, index):
        if index.row() == 0:
            return Qt.ItemIsEnabled

        _flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable

        if self.fields[index.column()].editable:
            _flags |= Qt.ItemIsEditable

        return _flags

    @pyqtSlot(str, int, bool)
    def _set_filter(self, keyword, column, refresh=True):
        if keyword is None or keyword == '':
            self._filters[column].remove_filter()
        else:
            self._filters[column].set_filter(keyword)

        if refresh:
            self.refresh()

    def rowCount(self, parent=None, **kwargs):
        return self.count + 1 if self.count else 1

    def columnCount(self, parent=None, **kwargs):
        return len(self.fields)

    @pyqtSlot()
    def refresh(self):
        self.layoutAboutToBeChanged.emit()

        q = self.query
        if self._sort is not None:
            col, order = self._sort
            if order == Qt.DescendingOrder:
                col = col.desc()

        else:
            col = None

        for filter_ in self._filters:
            keyword, column = filter_.keyword_and_column()
            if keyword is None:
                continue

            column = self.fields[column].sql_column
            q = q.filter(column.contains(keyword))

        q = q.order_by(col)
        self.results = q.all()
        self.count = q.count()
        self.layoutChanged.emit()

    def data(self, index, role=None):
        if not index.isValid():
            return QVariant()

        elif role not in (Qt.DisplayRole, Qt.EditRole):
            return QVariant()

        if index.row() == 0:
            return ''

        row = self.results[index.row() - 1]
        name = self.fields[index.column()].header

        var = getattr(row, name)
        if var is None and self.fields[index.column()].fallback is not None:
            var = getattr(row, self.fields[index.column()].fallback)

        return var

    def setData(self, index, value, role=None):
        if index.row() == 0:
            return False

        row = self.results[index.row() - 1]
        name = self.fields[index.column()].header

        try:
            self.db.update(row, name, value)
        except Exception as e:
            QMessageBox.critical(None, 'SQL error', e)
            return False

        else:
            self.dataChanged.emit(index, index)
            self.refresh()
            return True

    def sort(self, col, order=None):
        self._sort = self.fields[col].sql_column, order
        self.refresh()


class SongTable(QTableView):
    def __init__(self, model, parent=None):
        super().__init__(parent=parent)
        self.setModel(model)

        self.setSortingEnabled(True)
        self.setTabKeyNavigation(False)

        for i in range(self.model().columnCount()):
            index = self.model().index(0, i)
            line = FilterLine(i, self.model())
            self.setIndexWidget(index, line)


class FilterLine(QLineEdit):
    def __init__(self, column, model, *args, placeholder_text='Filter'):
        super().__init__(*args)
        self.column = column
        self.model = model
        self._func = None
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._do_filter)

        self.setPlaceholderText(placeholder_text)
        self.textEdited.connect(self.filter_table)

    @pyqtSlot()
    def _do_filter(self):
        if callable(self._func):
            self._func()

    @pyqtSlot(str)
    def filter_table(self, s):
        self._func = lambda: self.model.set_filter.emit(s, self.column, True)
        # The timer saves some resources whe typing quickly without impacting responsiveness much
        self.timer.start(100)
