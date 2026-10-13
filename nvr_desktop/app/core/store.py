"""BaseStore: common state and helpers for every page store.

A store is the Python side of one page: it holds the data QML shows (properties / list models),
fetches it through the API on a worker thread (`fetch`), and exposes actions as @Slot methods
(`act`). QML never talks to the API directly.

* `loading` - true until the first successful fetch (spinners), not on every poll.
* `error`   - last fetch error message ("" when fine), shown by ErrorState in QML.
* `act()`   - run an action; success and failure are reported as toasts, then `after` refreshes.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Property, QObject, Signal

from app.core.api.central import CentralApi
from app.core.context import AppContext
from app.core.tasks import run_task

logger = logging.getLogger(__name__)


class BaseStore(QObject):
    loadingChanged = Signal()
    errorChanged = Signal()

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._loading = True
        self._error = ""
        self._in_flight: set[str] = set()

    @property
    def api(self) -> CentralApi:
        return self.ctx.central

    # ------------------------------------------------------------------ state
    def _set_loading(self, value: bool) -> None:
        if value != self._loading:
            self._loading = value
            self.loadingChanged.emit()

    def _set_error(self, message: str) -> None:
        if message != self._error:
            self._error = message
            self.errorChanged.emit()

    loading = Property(bool, lambda self: self._loading, notify=loadingChanged)
    error = Property(str, lambda self: self._error, notify=errorChanged)

    # ------------------------------------------------------------------ helpers
    def fetch(
        self,
        name: str,
        fn: Callable[[], Any],
        on_ok: Callable[[Any], None],
        track_error: bool = True,
        on_err: Callable[[Exception], None] | None = None,
    ) -> None:
        """Background read. A fetch with the same `name` is skipped while one is still running.

        track_error=True: the result drives the store's `loading` / `error` (the page's main data).
        on_err: extra handler for failures (e.g. a per-item error message)."""
        if name in self._in_flight:
            return
        self._in_flight.add(name)

        def ok(result):
            self._in_flight.discard(name)
            on_ok(result)
            if track_error:
                self._set_error("")
                self._set_loading(False)

        def err(exc: Exception):
            self._in_flight.discard(name)
            logger.debug("%s.%s failed: %s", type(self).__name__, name, exc)
            if on_err:
                on_err(exc)
            if track_error:
                self._set_error(str(exc))
                self._set_loading(False)

        run_task(fn, ok, err)

    def act(
        self,
        fn: Callable[[], Any],
        success: str | Callable[[Any], str] | None = None,
        after: Callable[[Any], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        """Background action (create / update / delete...). Results are reported as toasts."""

        def ok(result):
            if success:
                self.ctx.toasts.success(success(result) if callable(success) else success)
            if after:
                after(result)

        def err(exc: Exception):
            self.ctx.toasts.error(str(exc))
            if on_error:
                on_error(exc)

        run_task(fn, ok, err)
