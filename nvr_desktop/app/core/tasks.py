"""The only threading helper in the app.

`run_task(fn, on_ok, on_err)` runs the blocking `fn` (an HTTP call, a download...) on Qt's global
thread pool and calls `on_ok(result)` or `on_err(exception)` back on the GUI thread. Stores never
block the UI and never touch Qt objects from worker threads.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

logger = logging.getLogger(__name__)

_running: set[_Task] = set()  # keep tasks alive until they report back


class _Signals(QObject):
    succeeded = Signal(object)
    failed = Signal(object)


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], Any]):
        super().__init__()
        self.setAutoDelete(False)
        self.fn = fn
        self.signals = _Signals()  # created on the GUI thread -> callbacks are queued to it

    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as exc:  # reported to the caller, never swallowed
            self._emit(self.signals.failed, exc)
        else:
            self._emit(self.signals.succeeded, result)

    @staticmethod
    def _emit(signal, value) -> None:
        try:
            signal.emit(value)
        except RuntimeError:
            pass  # the app is shutting down and the receiver is gone


def run_task(
    fn: Callable[[], Any],
    on_ok: Callable[[Any], None] | None = None,
    on_err: Callable[[Exception], None] | None = None,
) -> None:
    task = _Task(fn)

    def finish(callback, value):
        _running.discard(task)
        if callback is not None:
            callback(value)
        elif isinstance(value, Exception):
            logger.warning("Background task failed: %s", value)

    task.signals.succeeded.connect(lambda result: finish(on_ok, result))
    task.signals.failed.connect(lambda exc: finish(on_err, exc))
    _running.add(task)
    QThreadPool.globalInstance().start(task)
