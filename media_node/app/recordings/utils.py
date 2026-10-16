"""Fragmented-MP4 indexer and recording-path helpers.

MediaMTX records each chunk as:  ftyp + moov (init)  then  [moof + mdat] * N  (one per ~1 s).
We read only box headers / small moof boxes (never the video payload) and group fragments
into parts of ~HLS_PART_TARGET_SECONDS, starting on keyframes where possible. Each part becomes one HLS media
segment, served as a byte slice of the original file - no remux, no copy.

MediaMTX restarts timestamps at 0 in every chunk. When a part is served, the 8-byte `tfdt`
(decode time) of each fragment is rewritten to an absolute timeline (seconds since
TIMELINE_EPOCH), so timestamps keep increasing across chunks and nodes and players never
see time jump backwards. Only those header bytes change; video data is untouched.
"""

import os
import hashlib
import json
import struct
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SAMPLE_IS_NON_SYNC = 0x00010000
TIMELINE_EPOCH = datetime(2020, 1, 1, tzinfo=timezone.utc)

CODEC_NAMES = {
    b"avc1": "h264", b"avc3": "h264",
    b"hvc1": "h265", b"hev1": "h265",
    b"av01": "av1", b"vp09": "vp9",
    b"mp4a": "aac", b"Opus": "opus", b"alaw": "g711a", b"ulaw": "g711u", b"ipcm": "lpcm",
}


class Mp4IndexError(Exception):
    pass


@dataclass
class Track:
    track_id: int
    handler: str = ""
    timescale: int = 0
    codec: str | None = None
    default_duration: int = 0
    default_flags: int = 0
    config_signature: str | None = None


@dataclass
class Fragment:
    offset: int
    end: int
    ticks: int  # duration in the reference track's timescale
    keyframe: bool


@dataclass
class Mp4Index:
    init_size: int
    size_bytes: int  # bytes of complete boxes (a truncated tail is ignored)
    duration_ms: int
    codec: str | None
    parts: list[dict] = field(default_factory=list)  # [{"o", "s", "d"}]
    tracks: dict[str, dict] = field(default_factory=dict)  # {track_id: {"ts": timescale, "t0": first tfdt}}


# ---------------------------------------------------------------- box helpers


def _children(data: bytes, start: int = 0, end: int | None = None):
    """Yield (type, payload_start, box_end) for boxes inside data[start:end]."""
    end = len(data) if end is None else end
    pos = start
    while pos + 8 <= end:
        size, typ = struct.unpack_from(">I4s", data, pos)
        hdr = 8
        if size == 1:
            if pos + 16 > end:
                return
            size = struct.unpack_from(">Q", data, pos + 8)[0]
            hdr = 16
        elif size == 0:
            size = end - pos
        if size < hdr or pos + size > end:
            return
        yield typ, pos + hdr, pos + size
        pos += size


def _find(data: bytes, start: int, end: int, typ: bytes):
    for t, s, e in _children(data, start, end):
        if t == typ:
            return s, e
    return None


def _parse_moov(moov: bytes) -> dict[int, Track]:
    tracks: dict[int, Track] = {}
    trex: dict[int, tuple[int, int]] = {}
    for typ, s, e in _children(moov):
        if typ == b"trak":
            tkhd = _find(moov, s, e, b"tkhd")
            mdia = _find(moov, s, e, b"mdia")
            if not tkhd or not mdia:
                continue
            version = moov[tkhd[0]]
            track_id = struct.unpack_from(">I", moov, tkhd[0] + (20 if version == 1 else 12))[0]
            track = Track(track_id=track_id)
            mdhd = _find(moov, mdia[0], mdia[1], b"mdhd")
            if mdhd:
                v = moov[mdhd[0]]
                track.timescale = struct.unpack_from(">I", moov, mdhd[0] + (20 if v == 1 else 12))[0]
            hdlr = _find(moov, mdia[0], mdia[1], b"hdlr")
            if hdlr:
                track.handler = moov[hdlr[0] + 8 : hdlr[0] + 12].decode("ascii", "replace")
            minf = _find(moov, mdia[0], mdia[1], b"minf")
            stbl = _find(moov, minf[0], minf[1], b"stbl") if minf else None
            stsd = _find(moov, stbl[0], stbl[1], b"stsd") if stbl else None
            if stsd and stsd[0] + 16 <= stsd[1]:
                fourcc = moov[stsd[0] + 12 : stsd[0] + 16]
                track.codec = CODEC_NAMES.get(fourcc, fourcc.decode("ascii", "replace").strip())
                # Includes sample entry dimensions + avcC/hvcC (SPS/PPS/VPS), but not per-file timestamps.
                track.config_signature = hashlib.sha256(moov[stsd[0]:stsd[1]]).hexdigest()
            tracks[track_id] = track
        elif typ == b"mvex":
            for t2, s2, _ in _children(moov, s, e):
                if t2 == b"trex":
                    tid, _sdi, ddur, _dsize, dflags = struct.unpack_from(">IIIII", moov, s2 + 4)
                    trex[tid] = (ddur, dflags)
    for tid, (ddur, dflags) in trex.items():
        if tid in tracks:
            tracks[tid].default_duration = ddur
            tracks[tid].default_flags = dflags
    return tracks


def _parse_traf(moof: bytes, s: int, e: int, tracks: dict[int, Track]) -> tuple[int, int, bool | None, int | None]:
    """Return (track_id, total_ticks, first_sample_is_sync, base_decode_time)."""
    track_id, ticks, first_sync, base_time = 0, 0, None, None
    def_dur = def_flags = 0
    for typ, ps, pe in _children(moof, s, e):
        if typ == b"tfhd":
            flags = int.from_bytes(moof[ps + 1 : ps + 4], "big")
            track_id = struct.unpack_from(">I", moof, ps + 4)[0]
            t = tracks.get(track_id)
            def_dur = t.default_duration if t else 0
            def_flags = t.default_flags if t else 0
            p = ps + 8
            if flags & 0x01:
                p += 8
            if flags & 0x02:
                p += 4
            if flags & 0x08:
                def_dur = struct.unpack_from(">I", moof, p)[0]
                p += 4
            if flags & 0x10:
                p += 4
            if flags & 0x20:
                def_flags = struct.unpack_from(">I", moof, p)[0]
        elif typ == b"tfdt":
            base_time = struct.unpack_from(">Q" if moof[ps] == 1 else ">I", moof, ps + 4)[0]
        elif typ == b"trun":
            flags = int.from_bytes(moof[ps + 1 : ps + 4], "big")
            count = struct.unpack_from(">I", moof, ps + 4)[0]
            p = ps + 8
            if flags & 0x001:
                p += 4
            first_flags = None
            if flags & 0x004:
                first_flags = struct.unpack_from(">I", moof, p)[0]
                p += 4
            for i in range(count):
                dur, sflags = def_dur, def_flags
                if flags & 0x100:
                    dur = struct.unpack_from(">I", moof, p)[0]
                    p += 4
                if flags & 0x200:
                    p += 4
                if flags & 0x400:
                    sflags = struct.unpack_from(">I", moof, p)[0]
                    p += 4
                if flags & 0x800:
                    p += 4
                if i == 0 and first_flags is not None:
                    sflags = first_flags
                if i == 0 and first_sync is None:
                    first_sync = not (sflags & SAMPLE_IS_NON_SYNC)
                ticks += dur
    return track_id, ticks, first_sync, base_time


# ---------------------------------------------------------------- public API


def index_fmp4(path: Path, part_target_seconds: float) -> Mp4Index:
    file_size = os.path.getsize(path)
    tracks: dict[int, Track] = {}
    init_size = None
    fragments: list[Fragment] = []
    pending_moof: tuple[int, bytes] | None = None
    complete_end = 0
    ref_track: Track | None = None
    first_tfdt: dict[int, int] = {}

    with open(path, "rb") as f:
        pos = 0
        while pos + 8 <= file_size:
            f.seek(pos)
            header = f.read(16)
            size, typ = struct.unpack_from(">I4s", header)
            hdr = 8
            if size == 1:
                size, hdr = struct.unpack_from(">Q", header, 8)[0], 16
            elif size == 0:
                size = file_size - pos
            if size < hdr or pos + size > file_size:
                break  # truncated tail (e.g. power loss while writing)

            if typ == b"moov":
                f.seek(pos + hdr)
                tracks = _parse_moov(f.read(size - hdr))
                videos = [t for t in tracks.values() if t.handler == "vide"]
                ref_track = videos[0] if videos else next(iter(tracks.values()), None)
            elif typ == b"moof":
                if init_size is None:
                    init_size = pos
                f.seek(pos + hdr)
                pending_moof = (pos, f.read(size - hdr))
            elif typ == b"mdat" and pending_moof is not None:
                moof_pos, moof = pending_moof
                pending_moof = None
                ticks, keyframe = 0, False
                for t, s, e in _children(moof):
                    if t == b"traf":
                        tid, tr_ticks, first_sync, base_time = _parse_traf(moof, s, e, tracks)
                        if base_time is not None:
                            first_tfdt.setdefault(tid, base_time)
                        if ref_track and tid == ref_track.track_id:
                            ticks, keyframe = tr_ticks, bool(first_sync)
                fragments.append(Fragment(offset=moof_pos, end=pos + size, ticks=ticks, keyframe=keyframe))
                complete_end = pos + size
            pos += size

    if ref_track is None or not ref_track.timescale:
        raise Mp4IndexError("no usable track / timescale in moov")
    if init_size is None or not fragments:
        raise Mp4IndexError("no complete fragments")

    # Prefer to start each part on a fragment that begins with a keyframe. If the camera GOP
    # does not line up with MediaMTX fragments (e.g. GOP 32 frames @ 30 fps vs 1 s fragments),
    # such fragments are rare, so cut anyway at 1.5x the target: playback stays continuous and a
    # seek into that part only waits for the next keyframe (<= one GOP).
    timescale = ref_track.timescale
    target_ticks = int(part_target_seconds * timescale)
    max_ticks = int(part_target_seconds * 1.5 * timescale)
    groups: list[list[Fragment]] = []
    current: list[Fragment] = []
    current_ticks = 0
    for frag in fragments:
        if current and current_ticks >= target_ticks and (frag.keyframe or current_ticks >= max_ticks):
            groups.append(current)
            current, current_ticks = [], 0
        current.append(frag)
        current_ticks += frag.ticks
    if current:
        groups.append(current)

    parts = []
    for g in groups:
        ticks = sum(fr.ticks for fr in g)
        parts.append({
            "o": g[0].offset,
            "s": g[-1].end - g[0].offset,
            "d": round(ticks * 1000 / timescale),
            "k": g[0].keyframe,  # part starts with a keyframe (clean random access)
        })

    codecs = [t.codec for t in sorted(tracks.values(), key=lambda t: t.handler != "vide") if t.codec]
    return Mp4Index(
        init_size=init_size,
        size_bytes=complete_end,
        duration_ms=sum(p["d"] for p in parts),
        codec="+".join(codecs) or None,
        parts=parts,
        tracks={str(tid): {"ts": t.timescale, "t0": first_tfdt.get(tid, 0), "config": t.config_signature}
                for tid, t in tracks.items() if t.timescale},
    )


def decoder_signature(tracks: dict[str, dict]) -> str | None:
    """Stable decoding configuration across chunks. Legacy indexes have no signature."""
    if not tracks or any(not t.get("config") for t in tracks.values()):
        return None
    config = sorted((tid, t["ts"], t["config"]) for tid, t in tracks.items())
    return hashlib.sha256(json.dumps(config).encode()).hexdigest()


def rebase_timestamps(data: bytearray, tracks: dict[str, dict], start_time: datetime) -> bytearray:
    """Rewrite every fragment's tfdt in `data` (a run of moof+mdat boxes) in place:
    new = original - first_tfdt_of_file + (start_time - TIMELINE_EPOCH) * timescale."""
    offset_seconds = (start_time - TIMELINE_EPOCH).total_seconds()
    for typ, s, e in _children(data):
        if typ != b"moof":
            continue
        for t2, s2, e2 in _children(data, s, e):
            if t2 != b"traf":
                continue
            track = None
            for t3, s3, _ in _children(data, s2, e2):
                if t3 == b"tfhd":
                    track = tracks.get(str(struct.unpack_from(">I", data, s3 + 4)[0]))
                elif t3 == b"tfdt" and track and data[s3] == 1:  # only 64-bit tfdt can hold absolute time
                    old = struct.unpack_from(">Q", data, s3 + 4)[0]
                    new = old - track["t0"] + round(offset_seconds * track["ts"])
                    struct.pack_into(">Q", data, s3 + 4, max(new, 0))
    return data


# ---------------------------------------------------------------- recording paths

# MediaMTX recordPath:  <RECORDINGS_DIR>/%path/%Y-%m-%d/%H-%M-%S-%f.mp4
# with %path = "cam-<camera_id>/<profile>"  ->  cam-12/main/2026-10-11/10-00-00-123456.mp4


@dataclass
class RecordingFileInfo:
    camera_id: int
    profile: str
    start_time: datetime  # UTC


def parse_rel_path(rel_path: str) -> RecordingFileInfo:
    parts = rel_path.split("/")
    if len(parts) != 4 or not parts[0].startswith("cam-"):
        raise ValueError(f"unexpected recording path: {rel_path}")
    cam, profile, day, filename = parts
    stem = filename.rsplit(".", 1)[0]
    # MediaMTX formats the path using the node's local time zone.
    local = datetime.strptime(f"{day}_{stem}", "%Y-%m-%d_%H-%M-%S-%f").astimezone()
    return RecordingFileInfo(
        camera_id=int(cam.removeprefix("cam-")),
        profile=profile,
        start_time=local.astimezone(timezone.utc),
    )


def segment_uuid(node_name: str, rel_path: str) -> uuid.UUID:
    """Deterministic id: the same file always gets the same id (idempotent uploads)."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"shah-nvr://{node_name}/{rel_path}")
