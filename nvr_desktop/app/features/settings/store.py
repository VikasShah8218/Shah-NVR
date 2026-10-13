"""SettingsStore: test a central manager URL before saving it."""

from __future__ import annotations

from PySide6.QtCore import Property, Signal, Slot

from app.core.api.central import CentralApi
from app.core.context import AppContext
from app.core.store import BaseStore
from app.core.tasks import run_task


class SettingsStore(BaseStore):
    testChanged = Signal()

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(ctx, parent)
        self._test_state = "idle"  # idle | testing | ok | fail
        self._test_text = ""

    def _set_test(self, state: str, text: str) -> None:
        self._test_state, self._test_text = state, text
        self.testChanged.emit()

    @Slot(str)
    def testConnection(self, url: str) -> None:
        self._set_test("testing", "")

        def probe():
            api = CentralApi(url)
            try:
                return api.ping()
            finally:
                api.close()

        run_task(probe,
                 lambda body: self._set_test("ok", f"{(body or {}).get('service', 'Connected')}"),
                 lambda exc: self._set_test("fail", f"Cannot reach {url}: {exc}"))

    @Slot(str)
    def saveCentralUrl(self, url: str) -> None:
        self.ctx.prefs.centralUrl = url
        self.ctx.toasts.success("Central manager URL saved")

    testState = Property(str, lambda self: self._test_state, notify=testChanged)
    testText = Property(str, lambda self: self._test_text, notify=testChanged)
