"""Isolated H2 editor. Only explicit confirmation can issue encoder writes.

Worker closures capture their server, target and immutable request. Navigation
invalidates callbacks and stops unsent batch work; sent writes are never retried.
Only central history/recovery is polled, never camera SOAP settings.
"""
from copy import deepcopy
import math
from threading import Event
from uuid import uuid4

from PySide6.QtCore import QObject, Property, Signal, Slot

from app.core.tasks import run_task
from app.features.encoder.helpers import (
    alternatives, changed_values, fields, option_errors, preferred_option, preset_values, storage_text, validation,
)


def shared(state):
    return len(state.get("shared_profiles", [])) > 1 or state.get("use_count", 0) > 1


class EncoderStore(QObject):
    changed = Signal()
    reviewReady = Signal()
    targetChanged = Signal()

    def __init__(self, ctx, cameras, parent=None):
        super().__init__(parent)
        self._ctx, self._cameras = ctx, cameras
        self._cid, self._profile = 0, ""
        self._cancel = Event()
        self._reset()
        ctx.centralChanged.connect(self._server_changed)

    def _reset(self):
        self._cancel.set()
        self._cancel = Event()
        self._state, self._draft, self._history, self._recovery = {}, {}, {}, {}
        self._option, self._ack = 0, False
        self._busy = self._status_busy = False
        self._uncertain = False
        self._status_loaded = False
        self._error = self._status_error = self._message = ""
        self._review, self._bulk, self._selected = [], [], set()

    def _server_changed(self):
        self._reset()
        self.targetChanged.emit()
        self.changed.emit()
        self.reload()

    @Slot(int, str)
    def setTarget(self, camera_id, profile):
        if (camera_id, profile) == (self._cid, self._profile):
            return
        self._cid, self._profile = camera_id, profile
        self._reset()
        self.targetChanged.emit()
        self.changed.emit()
        self.reload()

    def _invalidate_review(self):
        self._review = []
        self._bulk = []

    def _accept_state(self, state):
        self._state = deepcopy(state)
        self._draft = deepcopy(state.get("current") or {})
        self._ack = False
        options = alternatives(state.get("options", []), self._draft.get("encoding"))
        self._option = preferred_option(options, self._draft, self._draft)
        self._invalidate_review()

    def _run(self, work, done):
        if self._busy or not self._cid or not self._profile:
            return
        api, cid, profile, cancel = self._ctx.central, self._cid, self._profile, self._cancel
        self._busy, self._error = True, ""
        self.changed.emit()

        def ok(result):
            if cancel.is_set():
                return
            self._busy = False
            done(result)
            self.changed.emit()

        def fail(exc):
            if cancel.is_set():
                return
            self._busy, self._error = False, str(exc)
            self.changed.emit()

        run_task(lambda: None if cancel.is_set() else work(api, cid, profile, cancel), ok, fail)

    @Slot()
    def reload(self):
        if self._busy:
            return
        self._invalidate_review()
        self._run(lambda api, cid, p, _: api.encoder(cid, p).to_qml(), self._accept_state)
        self.refreshStatus()

    @Slot()
    def refreshStatus(self):
        if self._status_busy or not self._cid or not self._profile:
            return
        api, cid, profile, cancel = self._ctx.central, self._cid, self._profile, self._cancel
        self._status_busy = True

        def work():
            return api.encoder_history(cid, profile).to_qml(), api.encoder_recovery(cid, profile)

        def ok(result):
            if cancel.is_set():
                return
            self._status_busy = False
            self._history, self._recovery = result
            self._status_loaded = True
            self._status_error = ""
            self.changed.emit()

        def fail(exc):
            if not cancel.is_set():
                self._status_busy, self._status_error = False, str(exc)
                self.changed.emit()

        run_task(work, ok, fail)

    @Slot(str)
    def saveMapping(self, token):
        if not token or self._busy or self._locked():
            return
        self._invalidate_review()
        def done(state):
            self._accept_state(state)
            self._message = "Profile mapping saved. RTSP URL was not changed."
            self.refreshStatus()
        self._run(lambda api, cid, p, _: api.encoder_mapping(cid, p, token).to_qml(), done)

    @Slot(str, str)
    def edit(self, key, value):
        if self._busy:
            return
        self._invalidate_review()
        self._error = ""
        if key == "resolution":
            try:
                w, h = (int(v) for v in value.split("x"))
            except ValueError:
                return
            self._draft.update(width=w, height=h)
        elif key in ("fps", "bitrate_kbps", "gop", "quality"):
            try:
                self._draft[key] = float(value)
            except ValueError:
                # Keep an invalid draft visible and block review (never silently use an old value).
                self._draft[key] = value
        elif key in ("encoding", "rate_control", "codec_profile"):
            self._draft[key] = value
        else:
            return
        if key == "encoding":
            options = alternatives(self._state.get("options", []), value)
            self._option = preferred_option(options, self._state.get("current") or {}, self._draft)
        self.changed.emit()

    @Slot(int)
    def selectOption(self, index):
        if not self._busy:
            self._option = max(0, index)
            self._invalidate_review()
            self.changed.emit()

    @Slot(bool)
    def acknowledge(self, value):
        if not self._busy:
            self._ack = value
            self._invalidate_review()
            self.changed.emit()

    @Slot(str)
    def preset(self, name):
        if self._busy or name not in ("Storage saver", "Best quality", "Low-bandwidth substream"):
            return
        options = alternatives(self._state.get("options", []), self._draft.get("encoding"))
        if options:
            # Preserve the chosen codec and other draft fields, just like the web editor.
            # An incomplete numeric input must be corrected before applying a preset.
            if any(not isinstance(self._draft[k], (int, float)) or not math.isfinite(self._draft[k]) for k in ("fps", "bitrate_kbps", "quality") if self._draft.get(k) is not None):
                self._error = "Correct the numeric draft fields before choosing a preset."
                self.changed.emit()
                return
            self._draft = preset_values(self._draft, options[min(self._option, len(options)-1)], name)
            self._invalidate_review()
            self.changed.emit()

    def _body(self, state, values, restore=None, ack=False):
        return {"operation_id": str(uuid4()), "revision": state["revision"], "values": values,
                "acknowledge_shared": ack, "restore_from": restore}

    def _locked(self):
        return bool(self._uncertain or self._history.get("pending") or not self._status_loaded or self._status_error)

    def _draft_errors(self):
        errors = validation(self._state, self._draft)
        options = alternatives(self._state.get("options", []), self._draft.get("encoding"))
        if not errors and options:
            errors = option_errors(options[min(self._option, len(options)-1)], self._state.get("current") or {}, self._draft)
        return errors

    @Slot(str)
    def prepare(self, restore_id=""):
        if self._busy or self._locked() or not self._state.get("revision"):
            return
        if shared(self._state) and not self._ack:
            self._error = "Acknowledge the shared encoder before continuing."
            self.changed.emit()
            return
        values = changed_values(self._state.get("current") or {}, self._draft)
        if not restore_id and (self._draft_errors() or not values):
            return
        self._invalidate_review()
        body = self._body(self._state, {} if restore_id else values, restore_id or None, self._ack)
        def done(_):
            self._review = [{"id": self._cid, "name": f"Camera #{self._cid}", "profile": self._profile, "body": body}]
            self._message = "Restore previous settings" if restore_id else "Apply proposed video settings"
            self.changed.emit()
            self.reviewReady.emit()
        self._run(lambda api, cid, p, _: api.encoder_check(cid, p, body), done)

    @Slot(int, bool)
    def selectCamera(self, cid, selected):
        if self._busy:
            return
        if selected:
            if len(self._selected) < 20:
                self._selected.add(cid)
        else:
            self._selected.discard(cid)
        self._invalidate_review()
        self.changed.emit()

    @Slot()
    def prepareBulk(self):
        if self._busy or self._locked() or not self._selected or self._draft_errors():
            return
        values = changed_values(self._state.get("current") or {}, self._draft)
        if not values:
            return
        targets = deepcopy([c for c in self._cameras.cameras() if c["id"] in self._selected])[:20]
        self._invalidate_review()
        profile = self._profile
        def work(api, cid, p, cancel):
            ready, results = [], []
            for camera in targets:
                if cancel.is_set():
                    break
                item = {"id": camera["id"], "name": camera["name"], "profile": profile}
                try:
                    if not camera.get("enabled") or not camera.get("onvif_host") or not any(s["profile"] == profile for s in camera.get("streams", [])):
                        raise ValueError("Requires an enabled ONVIF camera with the same stream name")
                    state = api.encoder(camera["id"], profile).to_qml()
                    if not state.get("revision") or not state.get("profile_token"):
                        raise ValueError("Explicit profile mapping required")
                    if shared(state):
                        raise ValueError("Shared encoder: review and apply individually")
                    target = {**(state.get("current") or {}), **values}
                    errors = validation(state, target)
                    if errors:
                        raise ValueError("; ".join(errors))
                    body = self._body(state, values)
                    api.encoder_check(camera["id"], profile, body)
                    ready.append({**item, "body": body})
                    results.append({**item, "status": "ready", "message": "Preflight passed; not yet applied"})
                except Exception as exc:
                    results.append({**item, "status": "skipped", "message": str(exc)})
            return ready, results
        def done(result):
            self._review, self._bulk = result
            self._message = f"Bulk preflight: {len(self._review)} ready. Skipped targets will not be changed."
            self.changed.emit()
            if self._review:
                self.reviewReady.emit()
        self._run(work, done)

    @Slot()
    def confirm(self):
        if self._busy or not self._review:
            return
        requests = deepcopy(self._review)
        self._review = []  # consume once; double-clicks cannot send again
        def work(api, cid, p, cancel):
            results = []
            stopped = False
            for item in requests:
                if cancel.is_set():
                    break
                if stopped:
                    results.append({**item, "status": "skipped", "message": "Batch stopped after an unverified result"})
                    continue
                try:
                    change = api.encoder_apply(item["id"], item["profile"], item["body"]).to_qml()
                    result = change.get("result") or {}
                    results.append({**item, "status": change["status"], "message": result.get("message", ""), "after": result.get("after")})
                    stopped = change["status"] != "verified"
                except Exception as exc:
                    results.append({**item, "status": "unknown", "message": f"{exc}. Check history/readback; do not retry."})
                    stopped = True
            return results
        def done(results):
            skipped = [r for r in self._bulk if r["status"] == "skipped"]
            self._uncertain = any(r["status"] in ("unknown", "pending") for r in results)
            for result in results:
                if result["id"] == self._cid and result.get("after"):
                    self._accept_state(result["after"])
                    break
            # Preserve outcomes even when accepting readback resets the review.
            self._bulk = [{k: v for k, v in r.items() if k not in ("body", "after")} for r in results] + skipped
            self._message = "Finished. Review each outcome and stream recovery below. No writes are retried automatically."
            self.refreshStatus()
        self._run(work, done)

    @Slot()
    def resolve(self):
        self._invalidate_review()
        def done(result):
            self._uncertain = False
            self._message = (result.get("result") or result).get("message", "Readback completed")
            self.reload()
        self._run(lambda api, cid, p, _: api.encoder_resolve(cid, p), done)

    def _view(self):
        current = self._state.get("current") or {}
        camera = self._cameras.byId(self._cid) or {}
        streams = camera.get("streams", []) if isinstance(camera, dict) else []
        streams = streams if isinstance(streams, list) else []
        stream = next((s for s in streams if s.get("profile") == self._profile), {})
        audio_kbps = stream.get("audio_bitrate_kbps") or 0
        current_total = current.get("bitrate_kbps")
        current_total = current_total + audio_kbps if isinstance(current_total, (int, float)) else None
        proposed_total = self._draft.get("bitrate_kbps")
        proposed_total = proposed_total + audio_kbps if isinstance(proposed_total, (int, float)) else None
        options = alternatives(self._state.get("options", []), self._draft.get("encoding"))
        option = options[min(self._option, len(options)-1)] if options else {}
        errors = self._draft_errors() if current else []
        changes = changed_values(current, self._draft)
        review_values = self._review[0]["body"]["values"] if self._review else {}
        restore_id = self._review[0]["body"].get("restore_from") if self._review else None
        if restore_id:
            prior = next((r for r in self._history.get("changes", []) if r["id"] == restore_id), {})
            review_values = (prior.get("before") or {}).get("current") or {}
        return {"state": self._state, "draft": self._draft, "busy": self._busy, "error": self._error,
                "statusError": self._status_error, "message": self._message, "fields": fields(self._state, self._draft, option),
                "options": [{"value": str(i), "label": f"Option {i+1}: " + ", ".join(f"{w}x{h}" for w, h in o.get("resolutions", []))} for i, o in enumerate(options)],
                "option": str(self._option), "errors": errors, "shared": shared(self._state), "ack": self._ack,
                "canApply": bool(current and self._state.get("revision") and changes and not errors and not self._busy and not self._locked() and (not shared(self._state) or self._ack)),
                "locked": self._locked(),
                "uncertain": self._uncertain,
                "history": self._history.get("changes", []), "pending": self._history.get("pending"),
                "recovery": self._recovery, "bulk": self._bulk, "selected": sorted(self._selected),
                "reviewCount": len(self._review), "proposal": ", ".join(f"{k}: {current.get(k)} → {v}" for k, v in changes.items()),
                "reviewTargets": ", ".join(f'{r["name"]} / {r["profile"]}' for r in self._review),
                "reviewValues": ", ".join(f"{k}: {v}" for k, v in review_values.items() if v is not None),
                "storage": f"Continuous recording: current {storage_text(current_total)} → proposed {storage_text(proposed_total)}",
                "audioKbps": audio_kbps}

    view = Property("QVariantMap", _view, notify=changed)
