"""CamerasStore: the Cameras page list, one page at a time (search + filter on the server), a small cache of the
cameras other pages show (live tiles, the playback camera, bulk-encoder targets) and every camera action:
create, update (+ stream changes), enable/disable, delete.

Never loads the whole camera list (docs/PAGINATION_PLAN.md):
* `listModel` / `rows` hold only the current page of the Cameras page.
* `track(key, ids)` tells the store which cameras a page needs in full; they are fetched by id (and refreshed on
  every poll) into the cache read by `byId()`. `revision` changes whenever the cache does (QML bindings use it).
"""

from __future__ import annotations

from PySide6.QtCore import Property, Signal, Slot

from app.core.context import AppContext
from app.core.paged_store import PagedStore
from app.features.cameras import forms

CAMERA_ROLES = [
    "id", "name", "description", "username", "has_password", "enabled", "retention_days",
    "created_at", "updated_at", "streams", "assignment", "lastSegment", "recordStatus",
    "onvif_host", "onvif_port", "manufacturer", "deviceModel", "firmware", "serial", "mac",
    "onvif_services", "onvif_reachable", "clock_offset_seconds", "onvif_checked_at",
    "expose_via_onvif", "has_ptz",
]

# Server-side filters of the Cameras page (same as the web).
FILTERS = {
    "all": {},
    "enabled": {"enabled": True},
    "disabled": {"enabled": False},
    "not_recording": {"enabled": True, "status": "NOT_RECORDING"},
    "connecting": {"enabled": True, "status": "CONNECTING"},
}
FILTER_OPTIONS = [
    {"value": "all", "label": "All cameras"},
    {"value": "enabled", "label": "Enabled"},
    {"value": "disabled", "label": "Disabled"},
    {"value": "not_recording", "label": "Not recording"},
    {"value": "connecting", "label": "Connecting"},
]


def _decorate(camera: dict) -> dict:
    """Add the computed fields the camera table and live list show."""
    # `model` is QML's delegate row object. Keep the API field in dictionaries,
    # but expose hardware identity under a non-conflicting list role.
    camera["deviceModel"] = camera.get("model")
    segments = sorted(s["last_segment_at"] for s in camera["streams"] if s.get("last_segment_at"))
    record_stream = next((s for s in camera["streams"] if s["record"]), camera["streams"][0] if camera["streams"] else None)
    camera["lastSegment"] = segments[-1] if segments else None
    camera["recordStatus"] = (record_stream or {}).get("status", "UNKNOWN") if camera["enabled"] else "DISABLED"
    return camera


class CamerasStore(PagedStore):
    camerasChanged = Signal()  # the cache behind byId() changed
    filterChanged = Signal()
    saved = Signal(int)  # camera id, after a successful create/update (closes the form sheet)

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(ctx, CAMERA_ROLES, poll_seconds=ctx.prefs.pollSeconds, parent=parent)
        self._filter = "all"
        self._known: dict[int, dict] = {}  # id -> camera (current page + tracked cameras)
        self._tracked: dict[str, set[int]] = {}  # consumer -> camera ids it shows
        self._revision = 0
        ctx.prefs.pollSecondsChanged.connect(lambda: self._poller.set_interval(ctx.prefs.pollSeconds))
        ctx.centralChanged.connect(self._central_changed)
        self.start_polling()

    # ------------------------------------------------------------------ the Cameras page (paged)
    def _load(self, limit: int, offset: int):
        rows, total = self.api.cameras(q=self._query, limit=limit, offset=offset, **FILTERS[self._filter])
        return [_decorate(c.to_qml()) for c in rows], total

    def _apply(self, rows: list[dict], total: int) -> None:
        super()._apply(rows, total)
        self._remember(rows)

    def _poll(self) -> None:
        super()._poll()
        self._refresh_tracked()

    def _central_changed(self) -> None:
        self._known.clear()
        self.refresh()
        self._refresh_tracked()

    @Slot(str)
    def setFilter(self, value: str) -> None:
        if value in FILTERS and value != self._filter:
            self._filter = value
            self.filterChanged.emit()
            self.reset()

    filter = Property(str, lambda self: self._filter, notify=filterChanged)
    filterOptions = Property("QVariantList", lambda self: FILTER_OPTIONS, constant=True)

    # ------------------------------------------------------------------ cache of cameras shown elsewhere
    def _remember(self, cameras: list[dict]) -> None:
        changed = False
        for c in cameras:
            if self._known.get(c["id"]) != c:
                self._known[c["id"]] = c
                changed = True
        if changed:
            self._revision += 1
            self.camerasChanged.emit()

    def _tracked_ids(self) -> set[int]:
        return set().union(*self._tracked.values()) if self._tracked else set()

    def _fetch_ids(self, ids: set[int], name: str) -> None:
        ids = {i for i in ids if i}
        if ids:
            self.fetch(name, lambda: [_decorate(c.to_qml()) for c in self.api.cameras_by_ids(sorted(ids))],
                       self._remember, track_error=False)

    def _refresh_tracked(self) -> None:
        self._fetch_ids(self._tracked_ids(), "tracked")

    @Slot(str, "QVariantList")
    def track(self, key: str, ids) -> None:
        """`key` (a page) shows these cameras in full: fetch the ones not cached yet, keep them fresh on poll."""
        wanted = {int(i) for i in (ids or []) if i}
        self._tracked[key] = wanted
        missing = wanted - self._known.keys()
        if missing:
            self._fetch_ids(missing, f"track-{key}-{sorted(missing)}")

    @Slot(int, result="QVariant")
    def byId(self, camera_id: int):
        return self._known.get(camera_id)

    revision = Property(int, lambda self: self._revision, notify=camerasChanged)

    def _after_change(self, camera_id: int | None = None) -> None:
        if camera_id:
            self._fetch_ids({camera_id}, f"one-{camera_id}")
        self.refresh()
        self._refresh_tracked()

    # ------------------------------------------------------------------ form helpers
    @Slot("QVariant", result="QVariantList")
    def validate(self, form) -> list[str]:
        return forms.validate(form)

    @Slot(result="QVariantList")
    def brandExamples(self) -> list[dict]:
        return forms.BRAND_EXAMPLES

    # ------------------------------------------------------------------ actions
    @Slot("QVariant")
    def create(self, form) -> None:
        body = forms.create_body(form)
        self.act(
            lambda: self.api.create_camera(body).to_qml(),
            success=lambda c: f'Camera "{c["name"]}" added',
            after=lambda c: (self.saved.emit(c["id"]), self._after_change(c["id"])),
        )

    @Slot(int, "QVariant")
    def update(self, camera_id: int, form) -> None:
        original = self.byId(camera_id) or {"streams": []}
        body = forms.update_body(form)
        diff = forms.stream_diff(original["streams"], form)

        def run():
            self.api.update_camera(camera_id, body)
            for stream in diff["add"]:
                self.api.add_stream(camera_id, stream)
            for change in diff["update"]:
                self.api.update_stream(camera_id, change["profile"], change["body"])
            for profile in diff["remove"]:
                self.api.delete_stream(camera_id, profile)

        self.act(run, success="Camera updated",
                 after=lambda _r: (self.saved.emit(camera_id), self._after_change(camera_id)))

    @Slot(int, bool)
    def setEnabled(self, camera_id: int, enabled: bool) -> None:
        self.act(lambda: self.api.update_camera(camera_id, {"enabled": enabled}),
                 success="Camera updated", after=lambda _r: self._after_change(camera_id))

    @Slot(int)
    def remove(self, camera_id: int) -> None:
        def after(_r):
            self._known.pop(camera_id, None)
            self._revision += 1
            self.camerasChanged.emit()
            self.refresh()

        self.act(lambda: self.api.delete_camera(camera_id), success="Camera deleted", after=after)
