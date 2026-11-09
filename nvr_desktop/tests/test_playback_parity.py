"""Playback & investigation parity with the web client (2026-11-09): reverse-play maths, hover thumbnails,
timeline markers, the bookmarks API client and PlaybackStore.thumbAt. Ports of nvr_client/tests/
transport.test.ts, thumbs.test.ts and markers.test.ts, so both clients behave the same."""

from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from app.core.api.central import CentralApi
from app.core.api.errors import ApiError
from app.features.playback.markers import MIN_RANGE_WIDTH, bookmark_marker, place_markers
from app.features.playback.thumbs import thumb_target, thumbnail_url
from app.features.playback.transport import RATES, ReverseAnchor, reverse_done, reverse_target, seek_precision

BASE = "http://central.test"
T0 = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
MS0 = T0.timestamp() * 1000
S = 1000


def iso(ms: float) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


# ---------------------------------------------------------------- reverse play
def test_reverse_moves_back_at_the_rate_by_wall_time():
    a = ReverseAnchor(pos=100.0, clock=5.0, rate=1)
    assert reverse_target(a, 5.0) == 100
    assert reverse_target(a, 6.0) == 99
    assert reverse_target(ReverseAnchor(100.0, 5.0, 4), 6.5) == 94
    assert reverse_target(ReverseAnchor(100.0, 5.0, 0.5), 7.0) == 99


def test_reverse_stops_at_the_playlist_start():
    floor = 50.0
    t = reverse_target(ReverseAnchor(51.0, 0.0, 8), 1.0, floor)
    assert t == floor and reverse_done(t, floor)
    assert not reverse_done(50.5, floor)


def test_rates_and_seek_precision():
    assert RATES == [0.5, 1, 2, 4, 8, 16]
    assert seek_precision(1) == "exact" and seek_precision(2) == "exact"
    assert seek_precision(4) == "keyframes"


# ---------------------------------------------------------------- thumbnails
SEGS = [
    {"id": "a", "node_id": 1, "start_time": iso(MS0), "end_time": iso(MS0 + 60 * S)},
    {"id": "b", "node_id": 2, "start_time": iso(MS0 + 60 * S), "end_time": iso(MS0 + 120 * S)},
    {"id": "c", "node_id": 1, "start_time": iso(MS0 + 180 * S), "end_time": iso(MS0 + 240 * S)},  # gap before
]


def test_hover_in_a_slot_maps_to_the_slot_start():
    assert thumb_target(SEGS, MS0 + 10 * S) == {"segment_id": "a", "node_id": 1, "at_ms": 0, "slot_start": MS0}
    assert thumb_target(SEGS, MS0 + 45 * S)["at_ms"] == 30_000
    assert thumb_target(SEGS, MS0 + 45 * S)["slot_start"] == MS0 + 30 * S


def test_two_thumbnails_per_minute_chunk_and_boundaries():
    slots = []
    for t in range(int(MS0), int(MS0 + 120 * S), 5 * S):
        x = thumb_target(SEGS, t)
        key = f"{x['segment_id']}:{x['at_ms']}"
        if key not in slots:
            slots.append(key)
    assert slots == ["a:0", "a:30000", "b:0", "b:30000"]
    assert thumb_target(SEGS, MS0 + 60 * S)["segment_id"] == "b"


def test_gaps_give_no_thumbnail_and_url_shape():
    assert thumb_target(SEGS, MS0 + 150 * S) is None
    assert thumb_target(SEGS, MS0 - 1) is None
    assert thumb_target(SEGS, MS0 + 240 * S) is None
    assert thumb_target(SEGS, MS0 + 25 * S, 10_000)["at_ms"] == 20_000
    assert thumbnail_url("http://10.0.0.5:7100/", "abc", 30000) == \
        "http://10.0.0.5:7100/api/v1/media/abc/thumb.jpg?at_ms=30000&w=240"


# ---------------------------------------------------------------- markers
MIN = 60_000
VIEW = (MS0, MS0 + 100 * MIN)


def at(minutes: float) -> float:
    return MS0 + minutes * MIN


def test_point_marker_position():
    [m] = place_markers([{"id": 1, "t": at(25), "kind": "bookmark"}], *VIEW)
    assert m["x"] == pytest.approx(0.25) and m["width"] is None


def test_points_outside_dropped_edges_kept():
    ms = [{"id": i, "t": at(v), "kind": "bookmark"} for i, v in (("before", -1), ("s", 0), ("e", 100), ("after", 101))]
    assert [m["id"] for m in place_markers(ms, *VIEW)] == ["s", "e"]


def test_ranges_are_clipped_and_have_a_minimum_width():
    [clipped] = place_markers([{"id": 1, "t": at(-10), "end_t": at(20), "kind": "bookmark"}], *VIEW)
    assert clipped["x"] == 0 and clipped["width"] == pytest.approx(0.2)
    [tiny] = place_markers([{"id": 2, "t": at(50), "end_t": at(50) + 1000, "kind": "bookmark"}], *VIEW)
    assert tiny["width"] == MIN_RANGE_WIDTH
    assert place_markers([{"id": 3, "t": at(-20), "end_t": at(0), "kind": "bookmark"}], *VIEW) == []
    assert place_markers([{"id": 4, "t": at(10), "kind": "bookmark"}], MS0, MS0) == []


def test_bookmark_becomes_a_marker():
    b = {"id": 7, "start_time": iso(at(5)), "end_time": iso(at(6)), "note": "Truck at gate", "label": "vehicle",
         "color": "#ef4444"}
    m = bookmark_marker(b)
    assert m == {"id": "bookmark-7", "t": at(5), "end_t": at(6), "kind": "bookmark",
                 "label": "vehicle: Truck at gate", "color": "#ef4444"}
    assert bookmark_marker({**b, "end_time": None, "label": None, "color": None})["label"] == "Truck at gate"


# ---------------------------------------------------------------- bookmarks API client
BOOKMARK = {"id": 3, "camera_id": 1, "camera_name": "Gate", "profile": "main", "start_time": iso(MS0),
            "end_time": None, "note": "Truck", "label": None, "color": "#f59e0b", "author": None,
            "created_at": iso(MS0), "updated_at": iso(MS0)}


@respx.mock
def test_bookmark_search_sends_filters():
    route = respx.get(f"{BASE}/api/v1/bookmarks").mock(return_value=httpx.Response(
        200, json={"items": [BOOKMARK], "total": 7, "limit": 100, "offset": 0}))
    rows, total = CentralApi(BASE).bookmarks(camera_id=1, profile="main", q="  truck ", start=T0,
                                             end=T0 + timedelta(days=1), order="desc", limit=100)
    assert total == 7 and rows[0].note == "Truck" and rows[0].to_qml()["camera_name"] == "Gate"
    params = route.calls.last.request.url.params
    assert params["camera_id"] == "1" and params["profile"] == "main" and params["q"] == "truck"
    assert params["order"] == "desc" and params["limit"] == "100" and params["start"].startswith("2026-11-09T12:00")
    CentralApi(BASE).bookmarks(order="desc")  # "all cameras", no search: no empty filters sent
    assert set(route.calls.last.request.url.params.keys()) == {"order", "limit"}


@respx.mock
def test_bookmark_create_update_delete():
    create = respx.post(f"{BASE}/api/v1/bookmarks").mock(return_value=httpx.Response(201, json=BOOKMARK))
    patch = respx.patch(f"{BASE}/api/v1/bookmarks/3").mock(return_value=httpx.Response(200, json={**BOOKMARK, "note": "Car"}))
    delete = respx.delete(f"{BASE}/api/v1/bookmarks/3").mock(return_value=httpx.Response(204))
    api = CentralApi(BASE)
    assert api.create_bookmark({"camera_id": 1, "start_time": iso(MS0), "note": "Truck"}).id == 3
    assert b'"note":"Truck"' in create.calls.last.request.content
    assert api.update_bookmark(3, {"note": "Car"}).note == "Car"
    assert patch.called
    api.delete_bookmark(3)
    assert delete.called


@respx.mock
def test_bookmark_errors_are_readable():
    respx.post(f"{BASE}/api/v1/bookmarks").mock(return_value=httpx.Response(404, json={"detail": "Camera not found"}))
    with pytest.raises(ApiError) as err:
        CentralApi(BASE).create_bookmark({"camera_id": 99, "start_time": iso(MS0), "note": "x"})
    assert err.value.status == 404 and str(err.value) == "Camera not found"


# ---------------------------------------------------------------- PlaybackStore.thumbAt
class _Nodes:
    def __init__(self, urls):
        self.urls = urls

    def api_url(self, node_id):
        return self.urls.get(node_id)


def test_store_thumb_at_uses_the_node_holding_the_chunk():
    from app.features.playback.store import PlaybackStore

    store = PlaybackStore.__new__(PlaybackStore)  # only the pieces thumbAt reads
    store._timeline = {"segments": SEGS}
    store._nodes = _Nodes({2: "http://node-2:7100"})
    assert PlaybackStore.thumbAt(store, MS0 + 70 * S) == {
        "url": "http://node-2:7100/api/v1/media/b/thumb.jpg?at_ms=0&w=240", "at": MS0 + 60 * S}
    assert PlaybackStore.thumbAt(store, MS0 + 10 * S) == {}   # node 1 unknown
    assert PlaybackStore.thumbAt(store, MS0 + 150 * S) == {}  # gap
