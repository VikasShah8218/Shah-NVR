"""L3 camera edge-storage configuration and job monitor."""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import Property, Signal, Slot

from app.core.context import AppContext
from app.core.poller import Poller
from app.core.store import BaseStore


def local_to_utc(value: str) -> str:
    parsed = datetime.fromisoformat(value.strip().replace(" ", "T"))
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone(timezone.utc).isoformat()


class BackfillStore(BaseStore):
    changed = Signal()

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(ctx, parent)
        self._camera_id = 0
        self._config: dict = {}
        self._recordings: list[dict] = []
        self._jobs: list[dict] = []
        self._generation = 0
        self._poller = Poller(self.refreshJobs, 3, self)
        ctx.centralChanged.connect(self._reset)

    def _reset(self):
        cid = self._camera_id
        self.setCamera(0)
        self.setCamera(cid)

    @Slot(int)
    def setCamera(self, camera_id: int) -> None:
        if camera_id == self._camera_id:
            return
        self._camera_id, self._config, self._recordings, self._jobs = camera_id, {}, [], []
        self._generation += 1
        self.changed.emit()
        if camera_id:
            self.refresh()
            self._poller.start(immediately=False)
        else:
            self._poller.stop()

    @Slot()
    def refresh(self) -> None:
        cid, generation = self._camera_id, self._generation
        if not cid:
            return
        self.fetch("backfill", lambda: self.api.backfill(cid).to_qml(),
                   lambda value: self._apply(generation, value), track_error=False)
        self.refreshJobs()

    def _apply(self, generation: int, value: dict) -> None:
        if generation == self._generation:
            self._config = value
            self.changed.emit()

    @Slot()
    def probe(self) -> None:
        cid, generation = self._camera_id, self._generation

        def done(value):
            if generation == self._generation:
                self._recordings = value.pop("recordings", [])
                self._config = value
                self.changed.emit()

        self.act(lambda: self.api.backfill_probe(cid).to_qml(), success="Camera edge storage tested", after=done)

    @Slot(str, str, str)
    def save(self, mode: str, profile: str, recording_token: str) -> None:
        cid, generation = self._camera_id, self._generation
        body = {"mode": mode, "profile": profile, "recording_token": recording_token or None}
        self.act(lambda: self.api.update_backfill(cid, body).to_qml(), success="Edge-storage settings saved",
                 after=lambda value: self._apply(generation, value))

    @Slot()
    def refreshJobs(self) -> None:
        cid, generation = self._camera_id, self._generation
        if not cid:
            return

        def apply(rows):
            if generation == self._generation:
                self._jobs = rows
                self.changed.emit()

        self.fetch("backfill-jobs", lambda: [j.to_qml() for j in self.api.backfill_jobs(cid)],
                   apply, track_error=False)

    @Slot(str, str, str, result=bool)
    def queue(self, start: str, end: str, profile: str) -> bool:
        try:
            body = {"start_time": local_to_utc(start), "end_time": local_to_utc(end), "profile": profile}
        except ValueError:
            self.ctx.toasts.error("Use local time as YYYY-MM-DD HH:MM")
            return False
        cid = self._camera_id
        self.act(lambda: self.api.create_backfill_job(cid, body).to_qml(), success="Backfill job queued",
                 after=lambda _value: self.refreshJobs())
        return True

    cameraId = Property(int, lambda self: self._camera_id, notify=changed)
    config = Property("QVariant", lambda self: self._config, notify=changed)
    recordings = Property("QVariantList", lambda self: self._recordings, notify=changed)
    jobs = Property("QVariantList", lambda self: self._jobs, notify=changed)
