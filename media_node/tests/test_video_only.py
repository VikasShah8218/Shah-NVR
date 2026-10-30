"""Video-only rendition for browsers (app/recordings/utils.py): H.264 + PCM as MediaMTX lays it out."""

import struct

from app.recordings.utils import _children, _find, video_only_init, video_only_part, video_track_ids

BASE_IS_MOOF = 0x020000
VIDEO, AUDIO = 1, 2


def box(typ, *parts):
    body = b"".join(parts)
    return struct.pack(">I4s", len(body) + 8, typ) + body


def full(typ, flags, *parts):
    return box(typ, struct.pack(">I", flags), *parts)


def trak(track_id, handler):
    tkhd = full(b"tkhd", 0, bytes(8), struct.pack(">I", track_id), bytes(68))
    mdia = box(b"mdia", full(b"mdhd", 0, bytes(8), struct.pack(">I", 90000), bytes(8)),
               full(b"hdlr", 0, bytes(4), handler, bytes(12)))
    return box(b"trak", tkhd, mdia)


def init_segment():
    trex = [full(b"trex", 0, struct.pack(">IIIII", i, 1, 0, 0, 0)) for i in (VIDEO, AUDIO)]
    moov = box(b"moov", box(b"mvhd", bytes(100)), trak(VIDEO, b"vide"), trak(AUDIO, b"soun"),
               box(b"mvex", *trex), box(b"udta", b"x"))
    return box(b"ftyp", b"iso5"), moov


def traf(track_id, sizes, offset):
    samples = b"".join(struct.pack(">II", 100, s) for s in sizes)
    trun = full(b"trun", 0x301, struct.pack(">Ii", len(sizes), offset), samples)
    tfhd = full(b"tfhd", BASE_IS_MOOF, struct.pack(">I", track_id))
    return box(b"traf", tfhd, full(b"tfdt", 0x01000000, bytes(8)), trun)


def fragment(order):
    """moof+mdat with one traf per (track, payload), the samples stored in that order."""
    mfhd = full(b"mfhd", 0, struct.pack(">I", 7))
    trafs = [traf(t, [len(p)], 0) for t, p in order]
    moof_size = 8 + len(mfhd) + sum(len(t) for t in trafs)
    offset, trafs = moof_size + 8, []
    for track, payload in order:
        trafs.append(traf(track, [len(payload)], offset))
        offset += len(payload)
    return box(b"moof", mfhd, *trafs) + box(b"mdat", *(p for _, p in order))


def read_samples(data):
    """Follow each trun's data_offset like a player does: {track: bytes}."""
    found = {}
    for typ, s, e in _children(data):
        if typ != b"moof":
            continue
        for t2, s2, e2 in _children(data, s, e):
            if t2 != b"traf":
                continue
            tfhd = _find(data, s2, e2, b"tfhd")
            trun = _find(data, s2, e2, b"trun")
            track = struct.unpack_from(">I", data, tfhd[0] + 4)[0]
            offset = struct.unpack_from(">i", data, trun[0] + 8)[0]
            size = struct.unpack_from(">I", data, trun[0] + 16)[0]
            found[track] = found.get(track, b"") + data[s - 8 + offset : s - 8 + offset + size]
    return found


def test_init_keeps_only_the_video_track():
    ftyp, moov = init_segment()
    init = ftyp + moov
    assert video_track_ids(init) == {VIDEO}
    out = video_only_init(init, {VIDEO})
    assert out.startswith(ftyp) and video_track_ids(out) == {VIDEO}
    moov_s, moov_e = _find(out, 0, len(out), b"moov")
    assert moov_e == len(out)                      # box sizes were rewritten
    assert [t for t, _, _ in _children(out, moov_s, moov_e)] == [b"mvhd", b"trak", b"mvex", b"udta"]
    mvex = _find(out, moov_s, moov_e, b"mvex")
    assert len(list(_children(out, *mvex))) == 1


def test_part_keeps_video_samples_and_drops_audio_bytes():
    # MediaMTX writes the tracks in either order within a fragment.
    video_a, video_b, pcm = b"V" * 500, b"W" * 300, b"a" * 160
    part = fragment([(VIDEO, video_a), (AUDIO, pcm)]) + fragment([(AUDIO, pcm), (VIDEO, video_b)])
    out = video_only_part(part, {VIDEO})
    assert read_samples(out) == {VIDEO: video_a + video_b}
    assert b"a" * 160 not in out
    assert len(out) < len(part)


def test_a_fragment_of_audio_alone_disappears():
    part = fragment([(AUDIO, b"a" * 160)]) + fragment([(VIDEO, b"V" * 50)])
    assert read_samples(video_only_part(part, {VIDEO})) == {VIDEO: b"V" * 50}
