"""DictListModel: a list of dicts exposed to QML ListView/Repeater, updated in place.

Each dict key listed in `roles` becomes a QML role (`model.name`, `model.status`...). `set_items()`
compares the new rows with the current ones by `key`: when the same rows are present in the same
order (the usual case for polling), only changed rows emit dataChanged, so delegates are NOT
recreated (no flicker, scroll position and hover state survive). Otherwise the model resets.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QByteArray, QModelIndex, Qt, Property, Signal, Slot


class DictListModel(QAbstractListModel):
    countChanged = Signal()

    def __init__(self, roles: list[str], key: str = "id", parent=None):
        super().__init__(parent)
        self._roles = list(roles)
        self._key = key
        self._items: list[dict] = []
        self._role_ids = {Qt.ItemDataRole.UserRole + 1 + i: name for i, name in enumerate(self._roles)}

    # ------------------------------------------------------------------ Qt model API
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._items)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._items):
            return None
        name = self._role_ids.get(role)
        return self._items[index.row()].get(name) if name else None

    def roleNames(self) -> dict[int, QByteArray]:
        return {rid: QByteArray(name.encode()) for rid, name in self._role_ids.items()}

    # ------------------------------------------------------------------ Python API
    def set_items(self, items: list[dict]) -> None:
        old_keys = [row.get(self._key) for row in self._items]
        new_keys = [row.get(self._key) for row in items]
        if old_keys == new_keys:
            for row, item in enumerate(items):
                if item != self._items[row]:
                    self._items[row] = item
                    idx = self.index(row)
                    self.dataChanged.emit(idx, idx)
            return
        self.beginResetModel()
        self._items = list(items)
        self.endResetModel()
        self.countChanged.emit()

    def items(self) -> list[dict]:
        return list(self._items)

    @Slot(int, result="QVariant")
    def get(self, row: int):
        return self._items[row] if 0 <= row < len(self._items) else None

    count = Property(int, lambda self: len(self._items), notify=countChanged)
