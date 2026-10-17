"""H2 regression tests: no server, camera, real settings or database access."""
from copy import deepcopy
from unittest.mock import Mock

import httpx
import pytest
import respx
from PySide6.QtCore import QCoreApplication, QObject, Signal

from app.core.api.central import CentralApi
from app.core.api.encoder_models import EncoderChange, EncoderHistory, EncoderState
from app.core.api.errors import ApiError
from app.features.encoder.helpers import alternatives, fields, preset_values, storage_text, validation
from app.features.encoder.store import EncoderStore

OPTION = {"encoding": "H265", "resolutions": [[1920, 1080], [1280, 720]], "frame_rates": [10, 15, 18, 25],
          "bitrate_range": [1024, 8000], "gop_range": [2, 255], "quality_range": [0, 5],
          "codec_profiles": [], "rate_controls": ["VBR", "CBR"]}
STATE = {"api": "tr2", "profile_token": "main-token", "encoder_token": "encoder-1", "revision": "a" * 64,
         "current": {"encoding": "H265", "width": 1920, "height": 1080, "fps": 18, "bitrate_kbps": 1024,
                     "gop": 20, "quality": 5, "rate_control": "VBR", "codec_profile": None},
         "options": [OPTION, {**OPTION, "resolutions": [[640, 360]], "bitrate_range": [128, 1024]}],
         "profiles": [{"token": "main-token", "name": "Main", "encoder_token": "encoder-1"}],
         "shared_profiles": ["main-token"], "use_count": 1, "warnings": []}
CHANGE = {"id": "operation-12345678", "status": "verified", "created_at": "2026-10-17T00:00:00Z",
          "before": STATE, "result": {"after": STATE, "message": "Readback verified"}}
RECOVERY = {"status": "RECORDING", "fresh_status": True, "new_recording": True, "recording_expected": True}


def immediate(fn, ok, err):
    try:
        result = fn()
    except Exception as exc:
        err(exc)
    else:
        ok(result)


def mock_api():
    api = Mock()
    api.encoder.return_value = EncoderState.model_validate(STATE)
    api.encoder_check.return_value = EncoderState.model_validate(STATE)
    api.encoder_mapping.return_value = EncoderState.model_validate(STATE)
    api.encoder_history.return_value = EncoderHistory()
    api.encoder_recovery.return_value = deepcopy(RECOVERY)
    api.encoder_apply.return_value = EncoderChange.model_validate(CHANGE)
    api.encoder_resolve.return_value = {"message": "No pending operation."}
    return api


class Context(QObject):
    centralChanged = Signal()


@pytest.fixture
def setup(monkeypatch):
    app = QCoreApplication.instance() or QCoreApplication([])
    ctx = Context()
    ctx.central = mock_api()
    cameras = Mock()
    cameras.cameras.return_value = [{"id": cid, "name": f"Camera {cid}", "enabled": True,
                                     "onvif_host": f"192.0.2.{cid}", "streams": [{"profile": "main"}]} for cid in range(1, 25)]
    monkeypatch.setattr("app.features.encoder.store.run_task", immediate)
    store = EncoderStore(ctx, cameras)
    store.setTarget(1, "main")
    yield app, ctx, cameras, store


def test_multiple_options_accept_the_reported_h265_proposal():
    draft = {**STATE["current"], "bitrate_kbps": 4096}
    assert validation(STATE, draft) == []
    assert len(alternatives([OPTION, deepcopy(OPTION)], "H265")) == 1


def test_never_union_incompatible_alternatives():
    draft = {**STATE["current"], "width": 640, "height": 360, "bitrate_kbps": 4096}
    assert validation(STATE, draft)
    assert validation(STATE, {**draft, "bitrate_kbps": 1024}) == []


@pytest.mark.parametrize("key,value", [("fps", 19), ("bitrate_kbps", 8001), ("gop", 1), ("quality", 6),
                                     ("rate_control", "INVALID"), ("codec_profile", "Main"),
                                     ("fps", float("nan")), ("bitrate_kbps", "bad"), ("gop", 10.5)])
def test_reject_invalid_values(key, value):
    assert validation(STATE, {**STATE["current"], key: value})


def test_missing_limits_preserve_current_only_and_media1_fps_is_integer():
    state = deepcopy(STATE)
    state["options"] = [{**OPTION, "gop_range": None}]
    assert not validation(state, {**state["current"], "bitrate_kbps": 2048})
    assert validation(state, {**state["current"], "gop": 21})
    state["api"] = "trt"
    state["options"][0].update(frame_rates=[], fps_range=[1, 30])
    assert validation(state, {**state["current"], "fps": 12.5})


def test_presets_and_storage_estimate():
    current = {**STATE["current"], "bitrate_kbps": 4096}
    assert preset_values(current, OPTION, "Storage saver")["bitrate_kbps"] == 2458
    low = preset_values(current, OPTION, "Low-bandwidth substream")
    assert (low["fps"], low["width"], low["bitrate_kbps"], low["encoding"]) == (10, 1280, 1024, "H265")
    assert storage_text(4096) == "44.2 GB/day"
    assert storage_text(1_000_000) == storage_text(float("nan")) == "unknown"
    assert next(f for f in fields(STATE, current, OPTION) if f["key"] == "codec_profile")["enabled"] is False


def test_preflight_then_confirmation_is_exactly_one_write(setup):
    _, ctx, _, store = setup
    store.edit("bitrate_kbps", "4096")
    assert store.view["canApply"]
    store.prepare("")
    ctx.central.encoder_apply.assert_not_called()
    checked = deepcopy(ctx.central.encoder_check.call_args.args[2])
    assert checked["values"] == {"bitrate_kbps": 4096}
    assert len(checked["operation_id"]) == 36
    store.confirm()
    store.confirm()
    assert ctx.central.encoder_apply.call_args.args == (1, "main", checked)
    ctx.central.encoder_apply.assert_called_once()
    assert store.view["bulk"][0]["status"] == "verified"


def test_edit_invalidates_confirmation_and_invalid_text_blocks_it(setup):
    _, ctx, _, store = setup
    store.edit("bitrate_kbps", "4096")
    store.prepare("")
    store.edit("bitrate_kbps", "invalid")
    store.confirm()
    ctx.central.encoder_apply.assert_not_called()
    assert not store.view["canApply"]
    assert store.view["errors"]


def test_shared_ack_restore_and_mapping(setup):
    _, ctx, _, store = setup
    store._accept_state({**STATE, "use_count": 2})
    store.prepare(CHANGE["id"])
    ctx.central.encoder_check.assert_not_called()
    store.acknowledge(True)
    store.prepare(CHANGE["id"])
    body = ctx.central.encoder_check.call_args.args[2]
    assert body["restore_from"] == CHANGE["id"] and body["values"] == {} and body["acknowledge_shared"]
    store.saveMapping("new-token")
    ctx.central.encoder_mapping.assert_called_once_with(1, "main", "new-token")
    store.confirm()
    ctx.central.encoder_apply.assert_not_called()


def test_status_poll_never_reads_camera_or_discards_draft(setup):
    _, ctx, _, store = setup
    store.edit("bitrate_kbps", "4096")
    ctx.central.encoder.reset_mock()
    store.refreshStatus()
    ctx.central.encoder.assert_not_called()
    assert store.view["draft"]["bitrate_kbps"] == 4096


def test_stale_callbacks_and_queued_write_cancelled_on_navigation(setup, monkeypatch):
    _, ctx, _, store = setup
    queue = []
    monkeypatch.setattr("app.features.encoder.store.run_task", lambda fn, ok, err: queue.append((fn, ok, err)))
    store.reload()
    old_read = queue[0]
    store.setTarget(2, "sub")
    old_read[1](deepcopy(STATE))
    assert store.view["state"] == {}
    monkeypatch.setattr("app.features.encoder.store.run_task", immediate)
    store.setTarget(1, "main")
    store.edit("bitrate_kbps", "4096")
    store.prepare("")
    queue.clear()
    monkeypatch.setattr("app.features.encoder.store.run_task", lambda fn, ok, err: queue.append((fn, ok, err)))
    store.confirm()
    queued_write = queue[0]
    ctx.central = mock_api()
    ctx.centralChanged.emit()
    queued_write[1](queued_write[0]())
    ctx.central.encoder_apply.assert_not_called()
    assert store.view["state"] == {}


def test_bulk_preflight_skips_shared_and_applies_only_after_confirmation(setup):
    _, ctx, _, store = setup
    store.edit("bitrate_kbps", "4096")
    store.selectCamera(2, True)
    store.selectCamera(3, True)
    ctx.central.encoder.side_effect = [EncoderState.model_validate({**STATE, "use_count": 2}), EncoderState.model_validate(STATE)]
    store.prepareBulk()
    ctx.central.encoder_apply.assert_not_called()
    assert [r["status"] for r in store.view["bulk"]] == ["skipped", "ready"]
    assert store.view["reviewCount"] == 1
    store.confirm()
    assert ctx.central.encoder_apply.call_args.args[0] == 3


def test_bulk_stops_after_uncertain_write_and_never_retries(setup):
    _, ctx, _, store = setup
    store.edit("bitrate_kbps", "4096")
    for cid in (2, 3):
        store.selectCamera(cid, True)
    store.prepareBulk()
    ctx.central.encoder_apply.side_effect = ApiError(0, "Connection lost")
    store.confirm()
    store.confirm()
    ctx.central.encoder_apply.assert_called_once()
    assert [r["status"] for r in store.view["bulk"]] == ["unknown", "skipped"]


def test_bulk_max_20(setup):
    _, _, _, store = setup
    for cid in range(2, 24):
        store.selectCamera(cid, True)
    assert len(store.view["selected"]) == 20


def test_selected_alternative_is_not_silently_combined(setup):
    _, _, _, store = setup
    store.edit("bitrate_kbps", "4096")
    store.selectOption(1)
    assert not store.view["canApply"] and store.view["errors"]
    store.selectOption(0)
    assert store.view["canApply"]


def test_history_failure_blocks_writes_until_status_recovers(setup):
    _, ctx, _, store = setup
    store.edit("bitrate_kbps", "4096")
    ctx.central.encoder_history.side_effect = ApiError(0, "Cannot read history")
    store.refreshStatus()
    store.prepare("")
    assert not store.view["canApply"]
    ctx.central.encoder_check.assert_not_called()
    ctx.central.encoder_history.side_effect = None
    store.refreshStatus()
    assert store.view["canApply"]


def test_unknown_write_requires_explicit_readback_even_if_history_is_delayed(setup):
    _, ctx, _, store = setup
    store.edit("bitrate_kbps", "4096")
    store.prepare("")
    ctx.central.encoder_apply.side_effect = ApiError(0, "Lost connection")
    store.confirm()
    assert store.view["uncertain"] and not store.view["canApply"]
    store.prepare("")
    store.confirm()
    ctx.central.encoder_apply.assert_called_once()
    store.resolve()
    ctx.central.encoder_resolve.assert_called_once_with(1, "main")
    assert not store.view["uncertain"]


def test_profile_switch_and_server_switch_clear_confirmation(setup):
    _, ctx, _, store = setup
    store.edit("bitrate_kbps", "4096")
    store.prepare("")
    store.setTarget(1, "sub")
    store.confirm()
    ctx.central.encoder_apply.assert_not_called()
    assert ctx.central.encoder.call_args.args == (1, "sub")
    store.edit("bitrate_kbps", "4096")
    store.prepare("")
    old_api = ctx.central
    ctx.central = mock_api()
    ctx.centralChanged.emit()
    store.confirm()
    old_api.encoder_apply.assert_not_called()
    ctx.central.encoder_apply.assert_not_called()


def test_navigation_stops_remaining_bulk_writes(setup):
    _, ctx, _, store = setup
    store.edit("bitrate_kbps", "4096")
    store.selectCamera(2, True)
    store.selectCamera(3, True)
    store.prepareBulk()
    def apply(*args):
        # Simulate cancellation arriving while the first network request is in flight.
        store._cancel.set()
        return EncoderChange.model_validate(CHANGE)
    ctx.central.encoder_apply.side_effect = apply
    store.confirm()
    ctx.central.encoder_apply.assert_called_once()


@respx.mock
def test_api_contract_timeouts_and_no_write_retry():
    api = CentralApi("http://central.test")
    url = "http://central.test/api/v1/cameras/1/streams/main/encoder"
    respx.get(url).respond(200, json=STATE)
    respx.put(url + "/mapping").respond(200, json=STATE)
    respx.post(url + "/check").respond(200, json=STATE)
    apply = respx.put(url).respond(200, json=CHANGE)
    respx.get(url + "/history").respond(200, json={"changes": [CHANGE], "pending": None})
    respx.get(url + "/recovery").respond(200, json=RECOVERY)
    respx.post(url + "/resolve").respond(200, json={"message": "No pending operation."})
    body = {"operation_id": "operation-12345678", "revision": "a"*64, "values": {"bitrate_kbps": 4096}}
    assert api.encoder(1, "main").encoder_token == "encoder-1"
    api.encoder_mapping(1, "main", "main-token")
    api.encoder_check(1, "main", body)
    assert api.encoder_apply(1, "main", body).status == "verified"
    assert apply.calls.last.request.extensions["timeout"]["read"] == 190
    assert api.encoder_history(1, "main").changes[0].before.api == "tr2"
    assert api.encoder_recovery(1, "main")["new_recording"]
    api.encoder_resolve(1, "main")
    apply.side_effect = httpx.ReadTimeout("timed out")
    with pytest.raises(ApiError):
        api.encoder_apply(1, "main", body)
    assert apply.call_count == 2
    api.close()
