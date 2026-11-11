"""PagedStore: one page of a server list at a time (docs/PAGINATION_PLAN.md). Same behaviour as the web `usePaged`
hook + `Pager`: page/size/search state, debounced search, the newest request wins, the page steps back when the list
shrinks under it, and polling reloads only the page on screen.

A subclass implements `_load(limit, offset)` (runs on a worker thread, returns `(rows, total)`) and calls
`self.refresh()` whenever one of its own filters changes (`self.reset()` also goes back to page 1).
"""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from app.core.context import AppContext
from app.core.list_model import DictListModel
from app.core.paging import DEFAULT_PAGE_SIZE, clamp_page, offset_for, page_count, range_label
from app.core.poller import Poller
from app.core.store import BaseStore

SEARCH_DEBOUNCE_MS = 300


class PagedStore(BaseStore):
    pageChanged = Signal()  # page, size, total, rows
    searchChanged = Signal()
    # permissions that may load this list (any one; empty = everyone). Lists poll in the background, so a user
    # without them never asks (each refused request would also be written to the audit log).
    PERMS: tuple[int, ...] = ()

    def __init__(self, ctx: AppContext, roles: list[str], *, page_size: int = DEFAULT_PAGE_SIZE,
                 poll_seconds: float | None = None, key: str = "id", parent=None):
        super().__init__(ctx, parent)
        self.model = DictListModel(roles, key=key, parent=self)
        self._rows: list[dict] = []
        self._page = 1
        self._size = page_size
        self._total = 0
        self._search = ""
        self._query = ""  # debounced search sent to the server
        self._seq = 0  # request counter: only the newest answer is applied
        self._busy = False
        self._debounce = QTimer(self, singleShot=True, interval=SEARCH_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._apply_search)
        self._poller = Poller(self._poll, poll_seconds, self) if poll_seconds else None

    # ------------------------------------------------------------------ loading
    def _load(self, limit: int, offset: int) -> tuple[list[dict], int]:  # pragma: no cover - abstract
        raise NotImplementedError

    def _can_load(self) -> bool:
        """False while a required filter is missing (e.g. no camera picked yet)."""
        return True

    def start_polling(self) -> None:
        if self._poller:
            self._poller.start()

    def _poll(self) -> None:
        if not self._busy:  # a slow server must not pile up requests
            self.refresh()

    @Slot()
    def refresh(self) -> None:
        if not self.allowed(*self.PERMS):
            return
        if not self._can_load():
            self._apply([], 0)
            return
        self._seq += 1
        seq, limit, offset = self._seq, self._size, offset_for(self._page, self._size)
        self._busy = True

        def ok(result):
            if seq != self._seq:
                return  # an older request: the page / filters changed since
            self._busy = False
            rows, total = result
            self._apply(rows, total)
            clamped = clamp_page(self._page, total, self._size)
            if clamped != self._page:  # the list shrank under us: show its last page
                self._page = clamped
                self.refresh()

        def err(_exc):
            if seq == self._seq:
                self._busy = False

        self.fetch(f"page-{seq}", lambda: self._load(limit, offset), ok, on_err=err)

    def reset(self) -> None:
        """A filter changed: back to page 1 and reload."""
        self._page = 1
        self.pageChanged.emit()
        self.refresh()

    def _apply(self, rows: list[dict], total: int) -> None:
        self._rows = rows
        self._total = total
        self.model.set_items(rows)
        self.pageChanged.emit()

    # ------------------------------------------------------------------ slots
    @Slot(int)
    def setPage(self, page: int) -> None:
        page = clamp_page(page, self._total, self._size)
        if page != self._page:
            self._page = page
            self.pageChanged.emit()
            self.refresh()

    @Slot()
    def next(self) -> None:
        self.setPage(self._page + 1)

    @Slot()
    def prev(self) -> None:
        self.setPage(self._page - 1)

    @Slot(int)
    def setPageSize(self, size: int) -> None:
        if size > 0 and size != self._size:
            self._size = size
            self.reset()

    @Slot(str)
    def setSearch(self, text: str) -> None:
        if text != self._search:
            self._search = text
            self.searchChanged.emit()
            self._debounce.start()

    def _apply_search(self) -> None:
        query = self._search.strip()
        if query != self._query:
            self._query = query
            self.reset()

    # ------------------------------------------------------------------ properties
    page = Property(int, lambda self: self._page, notify=pageChanged)
    pageSize = Property(int, lambda self: self._size, notify=pageChanged)
    total = Property(int, lambda self: self._total, notify=pageChanged)
    pageCount = Property(int, lambda self: page_count(self._total, self._size), notify=pageChanged)
    rangeLabel = Property(str, lambda self: range_label(self._page, self._size, self._total), notify=pageChanged)
    rows = Property("QVariantList", lambda self: self._rows, notify=pageChanged)
    search = Property(str, lambda self: self._search, notify=searchChanged)
    query = Property(str, lambda self: self._query, notify=searchChanged)
    listModel = Property(QObject, lambda self: self.model, constant=True)
