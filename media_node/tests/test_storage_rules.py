from pathlib import Path

from app.storage.utils import (
    ERROR,
    FULL,
    OK,
    UNAVAILABLE,
    Volume,
    all_full,
    classify_error,
    pick_target,
    update_full,
)

GB = 1024**3


def vol(key, position, quota=None, used=0, disk=10.0, state=OK, accepting=True, default=False):
    return Volume(key=key, central_id=key, path=Path(f"X:/v{key}"), position=position, quota_bytes=quota,
                  accepting=accepting, is_default=default, state=state, recordings_bytes=used,
                  disk_used_percent=disk)


def test_full_hysteresis_on_cap():
    v = vol(1, 0, quota=100 * GB, used=94 * GB)
    assert not update_full(v, 95, 92)
    v.recordings_bytes = 95 * GB
    assert update_full(v, 95, 92)           # >= 95% of the cap
    v.recordings_bytes = 92 * GB
    assert update_full(v, 95, 92)           # stays full until below 90%
    v.recordings_bytes = int(89.9 * GB)
    assert not update_full(v, 95, 92)


def test_full_on_disk_without_cap():
    v = vol(1, 0, quota=None, disk=96.0)
    assert update_full(v, 95, 92)
    v.disk_used_percent = 93.0
    assert update_full(v, 95, 92)           # hysteresis on the disk too
    v.disk_used_percent = 91.0
    assert not update_full(v, 95, 92)


def test_fill_in_order():
    d = vol(None, 0, default=True)
    a, b = vol(1, 1), vol(2, 2)
    assert pick_target([b, a, d]).key is None          # lowest position first
    d.full = True
    assert pick_target([b, a, d]).key == 1             # next in order
    a.accepting = False
    assert pick_target([b, a, d]).key == 2             # paused volumes are skipped
    b.state = UNAVAILABLE
    assert pick_target([b, a, d]).key is None          # everything else unusable: keep writing to the first full one


def test_all_full_and_fallback():
    d = vol(None, 0, default=True)
    a = vol(1, 1)
    d.full = a.full = True
    assert all_full([d, a])
    assert pick_target([d, a]).key is None             # write to the first; cleanup overwrites the oldest
    a.full = False
    assert not all_full([d, a])
    d.state, a.state = UNAVAILABLE, ERROR
    assert pick_target([d, a]).key is None             # nothing healthy: fall back to the default folder
    assert not all_full([d, a])                        # never overwrite because storage is *offline*


def test_classify_errors():
    unc = r"\\192.168.1.9\nvr"
    state, detail = classify_error(PermissionError(13, "denied"), unc)
    assert state == ERROR and "cmdkey /add:192.168.1.9" in detail
    gone = OSError(); gone.winerror = 53
    assert classify_error(gone, unc)[0] == UNAVAILABLE
    assert classify_error(FileNotFoundError(), r"Q:\nvr") == (UNAVAILABLE, "Drive or folder not found")
    assert classify_error(TimeoutError(), unc)[0] == UNAVAILABLE
    assert classify_error(PermissionError(), r"D:\nvr")[0] == ERROR


def test_report_state_names_match_central():
    # The node reports these strings; central's VolumeState enum must accept them.
    assert {OK, FULL, UNAVAILABLE, ERROR} <= {"PENDING", "OK", "FULL", "UNAVAILABLE", "ERROR"}


def test_hard_cap_trim_keeps_the_volume_full():
    # Trimming an over-cap volume must not make it "free" again, or recording would jump back to it
    # and skip the later volumes (fill order broken).
    from app.recordings.services import CAP_TRIM_TO
    from app.storage.utils import FREE_BELOW, FULL_AT

    assert FREE_BELOW < FULL_AT <= CAP_TRIM_TO <= 1.0
