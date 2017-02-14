from PyQt5.QtCore import QAbstractTableModel, QVariant, Qt
from PyQt5.QtWidgets import QMessageBox, QTableView


class Column:
    def __init__(self, header, sql_column, name, **kwargs):
        self.header = header
        self.sql_column = sql_column
        self.name = name
        self.editable = kwargs.pop('editable', False)


class SQLAlchemyTableModel(QAbstractTableModel):
    def __init__(self, db_handler, columns, query):
        super().__init__()

        self.db = db_handler
        self.fields = columns
        self.query = query
        self.results = None

        self.count = None
        self._sort = None
        self._filter = None
        self.refresh()

    def headerData(self, col, orientation, role=None):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return QVariant(self.fields[col].header)
        else:
            return QVariant()

    def flags(self, index):
        _flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable

        if self.fields[index.column()].editable:
            _flags |= Qt.ItemIsEditable

        return _flags

    def filter(self, keyword, column):
        self._filter = keyword, column
        self.refresh()

    def index(self, row, column, parent=None, **kwargs):
        return self.createIndex(row, column, parent)

    def rowCount(self, parent=None):
        return self.count or 0

    def columnCount(self, parent=None):
        return len(self.fields)

    def refresh(self):
        self.layoutAboutToBeChanged.emit()

        q = self.query
        if self._sort is not None:
            col, order = self._sort
            if order == Qt.DescendingOrder:
                col = col.desc()

        else:
            col = None

        if self._filter is not None:
            keyword, column = self._filter
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

        row = self.results[index.row()]
        name = self.fields[index.column()].header

        return getattr(row, name)

    def setData(self, index, value, role=None):
        row = self.results[index.row()]
        name = self.fields[index.column()].header

        try:
            self.db.update(row, name, value)
        except Exception as e:
            QMessageBox.critical(None, 'SQL error', e)
            return False

        else:
            self.dataChanged.emit(index, index)
            return True

    def sort(self, col, order=None):
        self._sort = self.fields[col].sql_column, order
        self.refresh()
