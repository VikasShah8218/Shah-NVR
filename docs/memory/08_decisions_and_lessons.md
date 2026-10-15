# 08: Decisions, rationale, bugs found and lessons

## 1. Architecture decisions (and why)
| # | Decision | Why / alternatives rejected |
|---|---|---|
| D1 | Central manager = FastAPI modular monolith; media node = separate FastAPI agent | Matches the user's "main + slave servers" request. 13 microservices would be overkill (the spec agrees). |
| D2 | **MediaMTX** as the media engine (not go2rtc) | Built-in fMP4 recording, LL-HLS, WebRTC, RTSP, Control API, metrics and JWT auth for later. go2rtc is better for home setups and odd cameras but has no recording or LL-HLS. Frigate uses go2rtc+FFmpeg; we don't copy that. |
| D3 | **No separate FFmpeg recorder** | MediaMTX already pulls, fans out and records. FFmpeg is kept only for future transcoding (MJPEG, H.265→H.264, G.711→AAC). |
| D4 | **Node never touches PostgreSQL** | Security, one writer, and nodes keep recording when the DB or central is down (SQLite queue + cache). |
| D5 | HLS-first delivery (LL-HLS live, HLS VOD playback); WebRTC for low latency; RTSP for VLC/desktop | The user wanted HLS and wide compatibility. Browsers can't do RTSP. MediaMTX can't serve recordings over RTSP. |
| D6 | **HLS VOD by byte-slicing the recorded fMP4 files** | No remux, no duplicate storage, no CPU. One playlist can span chunks and nodes. Parts are served as URL slices (`/part/N.m4s`), **not HTTP Range**, so it works with VLC and any player without byte-range support. |
| D7 | Central stores only **part durations**; the node keeps byte offsets | The playlist is built without calling nodes; the DB rows stay small. |
| D8 | **Absolute-timeline tfdt rebasing** (epoch 2020-01-01) when serving parts | MediaMTX restarts tfdt at 0 per file; FFmpeg-based players dropped 1 s per join. Rebasing gives monotonic timestamps across chunks and nodes, with DISCONTINUITY only at real gaps. |
| D9 | **Continuity-first fencing** | A recording gap is worse than a duplicate. A partitioned node keeps recording; overlap segments are kept; the playlist dedupes by time; the old node self-fences on reconnect. (The spec's "reject stale writes" was changed.) |
| D10 | Directory scanning instead of MediaMTX `runOnRecordSegmentComplete` hooks | Same behaviour on every OS, no shell quoting, and doubles as crash recovery. |
| D11 | Integer IDs for cameras and nodes; deterministic UUIDv5 for segments | Easy to use in Postman; idempotent uploads. |
| D12 | Agent owns retention (`recordDeleteAfter: 0s`) | The catalog and files stay consistent; supports holds and quotas later. |
| D13 | Single central instance, asyncio lock in the scheduler | Simplicity. A PostgreSQL advisory lock is the planned leader election. |
| D14 | Storage quota enforced **on the node**, configured centrally, cached locally | It works while central is down; deletes exactly enough (95% → 90%). |
| D15 | Front end: React + TS + Tailwind + shadcn/ui (user's choice over the recommended Mantine), Dusk slate theme | The user wanted a clean, soft-dark UI. Plain shadcn tables were used instead of TanStack Table (small data sets). |
| D16 | Live player: WebRTC (WHEP) first, LL-HLS fallback (user's choice) | Lowest latency; the fallback covers networks where ICE fails. Verified remotely. |
| D17 | API types generated from FastAPI OpenAPI (`openapi-typescript` + `openapi-fetch`) | Keeps the UI in sync; offline export script avoids needing running servers. |
| D18 | No auth / JWT / nginx in this phase | Explicit user instruction. The plan originally had JWT and nginx `auth_request`; postponed. |

## 2. Bugs found during testing (and fixes): don't reintroduce them
1. **tzdata missing on Windows.** Tortoise `ZoneInfo("UTC")` crashed and central returned 500 on register. Fix: `tzdata` added to both requirements.
2. **Orphan MediaMTX.** A hard-killed agent left mediamtx holding the ports, so the next start failed. Fix: `kill_orphan_mediamtx()` via psutil at supervisor start.
3. **Frames dropped at chunk joins.** Each chunk's tfdt restarts at 0; FFmpeg ignores DISCONTINUITY for fMP4 and discarded 25 frames (1 s) per join. Fix: tfdt rebasing (D8). After the fix, 900/900 frames in 36 s, and 3450 frames / 138 s across two nodes.
4. **Real camera: parts of about 30 s.**
   - Cause: MediaMTX closes a fragment *after* the sample at exactly 1 s, so fragments hold 31 frames at 30 fps. They line up with a 30-frame (or Axis default 32-frame) GOP only every ~30 s, so the keyframe-only grouping made 2 parts per chunk.
   - Tried: forcing GOP 30 via the Axis URL (still 2 parts) and 250 ms fragments (only 2/4 aligned, at 4× the disk writes).
   - **Fix:** cut a part at 1.5× target even mid-GOP (parts of about 6 s), store a `k` keyframe flag, and drop `EXT-X-INDEPENDENT-SEGMENTS`. A seek into a mid-GOP part waits at most one GOP. Verified: 10 parts of ~6.1 s per 61 s chunk; a part decodes alone, dropping only the frames before its first keyframe.
5. **Quota cleanup deleted everything.** It deleted batches of 50 before re-checking. Fix: pick the oldest chunks one by one until under 90%. Verified: 2 chunks per cycle.
6. **Playback URL rebuilt every render** (`Date.now()` in the end time), which would have reloaded the player constantly. Fix: a `playTo` state fixed when playback starts.
7. **Vite port clash.** The HID Trinetra app listens on `::1:5173`, and `localhost` resolved to it. Fix: nvr_client uses 5180 with strictPort.
8. **shadcn Sheet width.** `sm:max-w-xl` lost to the built-in `data-[side=right]:sm:max-w-sm`. Fix: use `data-[side=right]:sm:max-w-xl`.
9. **Toggle "on" state invisible** in the dark theme (`bg-muted`). Fix: `bg-primary/20 text-primary` in `ui/toggle.tsx`.
10. **Timeline ticks at 01:30, 03:30…** because they were aligned to UTC and the user is UTC+05:30. Fix: align with `getTimezoneOffset`; anchor edge labels inward.
11. **The playback video was too tall**, which hid the timeline. Fix: cap the width at `55vh × 16/9`.
12. **Live tile backoff never reset.** Fix: a failure-count ref reset on `playing`.
13. The FFmpeg drawtext in the camera simulator failed (no fontconfig). Fix: an explicit fontfile with an escaped drive colon.

## 3. Lessons / facts worth remembering
- MediaMTX v1.21.2 config keys verified from its bundled `mediamtx.yml`: `recordPath` must contain `%s` or `%Y %m %d %H %M %S`; `%path` with `/` creates subfolders; date subfolders work; API path names with `/` work.
- MediaMTX `/v3/config/paths/list` returns `source` unredacted (credentials included), so the diff/patch logic doesn't loop.
- `sourceOnDemand` paths connect on the first reader (WebRTC, HLS or RTSP), so the status IDLE is expected.
- In WebRTC through MediaMTX, ICE uses interface IPs; the node also offers its advertised LAN IP (`webrtcAdditionalHosts`).
- Axis: RTSP `/axis-media/media.amp` with URL parameters `videocodec, resolution, fps, videokeyframeinterval` (per stream; doesn't change the camera's saved settings). VAPIX: `/axis-cgi/param.cgi?action=list&group=root.Brand,...` with digest auth.
- The Axis M1125 scene compresses to about 180 kbps at 1080p30 (≈1.3 MB per minute). Size estimates must use real cameras.
- Aerich 0.10 + Tortoise 1.1.8: `aerich init` writes `[tool.tortoise]` (not `[tool.aerich]`) in pyproject; it works despite the "native migrations" warning.
- Tortoise: `fetch_related` on a missing reverse O2O is unreliable; query the related model directly.
- An npm peer-dependency conflict (openapi-typescript wants TS 5) is fixed with `overrides` rather than `--legacy-peer-deps`.
- Tyco/other VMS "small exports" re-encode (offline CRF H.265); camera encoders are real-time and wasteful on static scenes. The way to save storage: smart codecs, H.265, motion retention, keyframe thinning, GPU re-encode for old footage.
