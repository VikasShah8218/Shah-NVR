import asyncio
import struct
from types import SimpleNamespace

from app.mediamtx import services
from app.recordings.utils import _parse_moov, decoder_signature


def test_targeted_restart_leaves_other_camera_paths_untouched(monkeypatch):
    calls = []
    async def refresh():
        pass
    async def delete(name):
        calls.append(("delete", name))
    async def add(name, conf):
        calls.append(("add", name))
    monkeypatch.setattr(services, "refresh_assignments", refresh)
    monkeypatch.setattr(services, "mtx", SimpleNamespace(delete_path=delete, add_path=add))
    monkeypatch.setattr(services, "desired_paths", lambda: {
        "cam-1/main": {"record": True}, "cam-1/sub": {"record": False}, "cam-2/main": {"record": True}})
    result = asyncio.run(services.restart_camera_paths([1]))
    assert result == {"cam-1/main": "pending", "cam-1/sub": "on_demand"}
    assert calls == [("delete", "cam-1/main"), ("add", "cam-1/main"), ("delete", "cam-1/sub"), ("add", "cam-1/sub")]


def test_restart_error_is_explicit_and_next_path_still_restarts(monkeypatch):
    async def refresh():
        pass
    async def delete(name):
        if name.endswith("main"):
            raise RuntimeError("secret-URL-must-not-leak")
    async def add(name, conf):
        pass
    monkeypatch.setattr(services, "refresh_assignments", refresh)
    monkeypatch.setattr(services, "mtx", SimpleNamespace(delete_path=delete, add_path=add))
    monkeypatch.setattr(services, "desired_paths", lambda: {"cam-1/main": {"record": True}, "cam-1/sub": {"record": False}})
    result = asyncio.run(services.restart_camera_paths([1]))
    assert result == {"cam-1/main": "restart_failed", "cam-1/sub": "on_demand"}


def test_decoder_signature_ignores_timestamps_but_tracks_config_changes():
    original = {"1": {"ts": 90000, "t0": 0, "config": "A"}}
    later = {"1": {"ts": 90000, "t0": 99999, "config": "A"}}
    changed = {"1": {"ts": 90000, "t0": 99999, "config": "B"}}
    assert decoder_signature(original) == decoder_signature(later)
    assert decoder_signature(original) != decoder_signature(changed)
    assert decoder_signature({"1": {"ts": 90000, "t0": 0}}) is None


def test_sample_description_changes_are_fingerprinted():
    def box(kind, payload):
        return struct.pack(">I4s", len(payload) + 8, kind) + payload
    def moov(width):
        tkhd = box(b"tkhd", bytes(12) + struct.pack(">I", 1) + bytes(8))
        mdhd = box(b"mdhd", bytes(12) + struct.pack(">I", 90000) + bytes(8))
        stsd = box(b"stsd", bytes(4) + struct.pack(">I", 1) + box(b"avc1", bytes(24) + struct.pack(">HH", width, 1080)))
        return box(b"trak", tkhd + box(b"mdia", mdhd + box(b"minf", box(b"stbl", stsd))))
    a, b = _parse_moov(moov(1920))[1], _parse_moov(moov(1280))[1]
    assert a.codec == b.codec == "h264"
    assert a.config_signature != b.config_signature
