# 04: media_node (recorder and streamer)

Path: `media_node/`. Run it with `py main.py`. It starts **MediaMTX as a child process**, so `media_node/bin/mediamtx.exe` must exist. That folder is git-ignored; download it from
https://github.com/bluenviron/mediamtx/releases (we use **v1.21.2**, `mediamtx_v1.21.2_windows_amd64.zip`).

## 1. Files
```
media_node/
├── main.py                  logging (+ RingBufferHandler), lifespan: Tortoise(SQLite, generate_schemas) → load_local_state
│                            → supervisor.start() → register() → 6 loops; CORS GET * ; routers
├── settings/settings.py     Settings + validator making DATA_DIR/RECORDINGS_DIR/MEDIAMTX_BIN relative to the media_node folder
├── database/config.py       TORTOISE_ORM sqlite://<DATA_DIR>/node_state.sqlite3 (creates DATA_DIR on import!)
├── utilities/common.py      utcnow, run_periodic
├── utilities/logbuffer.py   RingBufferHandler(deque 2000) → log_buffer (served by /api/v1/logs)
├── bin/                     mediamtx.exe (+ LICENSE, default mediamtx.yml), git-ignored
├── data/                    runtime (git-ignored): node_state.sqlite3, mediamtx.yml (generated), logs/mediamtx.log, recordings/
└── app/
    ├── node/        models.py (KeyValue), utils.py (NodeRuntime `runtime`, CentralClient `central`, CentralError),
    │                services.py (load_local_state, register, heartbeat_tick, apply_storage_quota, refresh_assignments,
    │                stream_status_tick, disk_info), metrics.py (cpu_memory, network_rates, gpus), router.py, schemas.py
    ├── mediamtx/    utils.py (MediaMTXClient `mtx`, render_config, write_config, MANAGED_PREFIX="cam-"),
    │                services.py (kill_orphan_mediamtx, _rotate log, MediaMTXSupervisor `supervisor`, desired_paths, reconcile_tick)
    └── recordings/  models.py (LocalSegment, SkippedFile), utils.py (fMP4 indexer, rebase_timestamps, parse_rel_path,
                     segment_uuid), services.py (scan/upload/deletion/quota/disk-pressure), router.py (media serving), schemas.py
```

## 2. Settings (`.env`; relative paths are relative to `media_node/`)
| Name | Default | Notes |
|---|---|---|
| NODE_NAME | node-1 | unique per node; server uses `shah-ho-node-1` |
| HOST / PORT | 0.0.0.0 / 7100 | agent API |
| PUBLIC_HOST | auto | **Host put into every client link** (live RTSP/HLS/WebRTC, playback, downloads). `auto` = this PC's LAN IP via `utilities/netaddr.py`, skipping VPN-overlay 100.64/10, link-local and VMware/Hyper-V/WSL/Docker/VPN adapters. It prefers the default-route IP, re-detects every `ADDRESS_CHECK_INTERVAL_SECONDS` (120) and re-registers on change. An explicit IP/hostname overrides it. It also feeds MediaMTX `webrtcAdditionalHosts`. The heartbeat reports `addresses` for the UI. |
| CAPACITY_CAMERAS | 100 | sent on register (the central UI can change it) |
| CENTRAL_URL | http://127.0.0.1:8000 | |
| DATA_DIR / RECORDINGS_DIR | ./data / ./data/recordings | |
| MEDIAMTX_BIN | ./bin/mediamtx.exe | |
| MEDIAMTX_API_PORT / METRICS | 9997 / 9998 | bound to 127.0.0.1 |
| RTSP_PORT, RTP_PORT, RTCP_PORT | 8554, 8000, 8001 | |
| HLS_PORT, HLS_VARIANT | 8888, lowLatency | |
| WEBRTC_PORT, WEBRTC_UDP_PORT | 8889, 8189 | |
| SEGMENT_SECONDS | 60 | chunk length (MediaMTX recordSegmentDuration) |
| PART_SECONDS | 1.0 | MediaMTX recordPartDuration (also the most data lost on a power cut) |
| HLS_PART_TARGET_SECONDS | 4.0 | playback part target (forced cut at 1.5× = 6 s) |
| HEARTBEAT/RECONCILE/SCAN/UPLOAD/STATUS/DELETION intervals | 5/5/5/3/10/60 s | |
| DISK_MAX_USED_PERCENT / DISK_TARGET_USED_PERCENT / DISK_MIN_KEEP_HOURS | 95 / 92 / 1 | disk-pressure cleanup |

`settings.api_url` = `http://<settings.public_host>:PORT` (`public_host` resolves `auto`); `settings.mediamtx_api` = `http://127.0.0.1:<api port>`; `settings.db_path` = `DATA_DIR/node_state.sqlite3`.

## 3. MediaMTX integration
- **Generated config** (`render_config()`, rewritten on every start):
  - API and metrics on 127.0.0.1. `playback: false`, `pprof: false`.
  - RTSP with `rtspTransports: [tcp, udp]`. RTMP, SRT and MoQ disabled.
  - HLS: `hlsVariant: lowLatency`, `hlsAlwaysRemux: false` (the muxer is created only when someone watches), `hlsAllowOrigins: ["*"]`.
  - WebRTC on 8889 with UDP 8189.
  - `pathDefaults`: `record: false`, `recordPath: "<RECORDINGS_DIR>/%path/%Y-%m-%d/%H-%M-%S-%f"`, `recordFormat: fmp4`, `recordPartDuration: 1000ms`, `recordSegmentDuration: 60000ms`, **`recordDeleteAfter: 0s`** (the agent owns retention).
  - `paths: {}`: there are no static paths. Unknown paths can't be published.
  - Default auth: anyone may read/publish, and the API is reachable from localhost only.
- **Control API v3** used by `MediaMTXClient`:
  - `GET /v3/config/global/get` (ping); `GET /v3/info` (version).
  - `GET /v3/config/paths/list?page=&itemsPerPage=1000` (paged).
  - `POST /v3/config/paths/add/{name}`, `PATCH /v3/config/paths/patch/{name}`, `DELETE /v3/config/paths/delete/{name}`.
  - `GET /v3/paths/list` (runtime: `ready`, `readyTime`, `tracks`, `bytesReceived`, `bytesSent`, `readers`).
  - Path names containing `/` work in these URLs (verified).
  - Changes made through the API are **not persisted**: after a MediaMTX restart, the reconcile loop adds every path again.
- **Supervisor**:
  - Starts `mediamtx.exe data/mediamtx.yml` with cwd=DATA_DIR and stdout/stderr appended to `data/logs/mediamtx.log` (rotated to `.log.1` above 20 MB).
  - Restarts with backoff from 1 s up to 30 s.
  - `kill_orphan_mediamtx()` uses psutil to find a process named *mediamtx* listening on our API or RTSP port and kills it. That happens when the agent was hard-killed and its child survived.
- **Per-path config** set by reconcile: `source` (with credentials), `record`, `sourceOnDemand = not record`, and `rtspTransport` (RTSP sources only). Patches send only the changed keys.
- **Hooks** (`runOnRecordSegmentComplete`) are **not used**. Detection uses directory scanning, which works the same on every OS and doesn't depend on shell quoting.

## 4. Recording pipeline details
- **Finished-chunk detection** (`_list_finished_files`): for each `cam-*/<profile>/<day>/` folder, files sorted by name. Every file except the newest is finished. The newest counts as finished only when its mtime is more than 30 s old. After the first full scan, only the newest 2 day folders are listed (performance). An in-memory `_known` set is seeded from the DB (last 3 days).
- **parse_rel_path** turns `cam-12/main/2026-10-11/10-00-00-123456.mp4` into camera 12, profile main, and a start time. The start time is parsed as **local time** (MediaMTX formats paths in local time) and converted to UTC.
- **index_fmp4(path, part_target_seconds)**:
  - Walks the top-level boxes: `ftyp`, `moov` (parsed for tracks), then repeated `moof`/`mdat` pairs. It stops at a truncated box, which is how crash recovery works.
  - `_parse_moov` reads, per `trak`: `tkhd` track_id (offset 12 for v0, 20 for v1), `mdhd` timescale (offset 12 for v0, 20 for v1), `hdlr` handler (offset 8), and the first `stsd` entry fourcc mapped to a codec (avc1/avc3=h264, hvc1/hev1=h265, mp4a=aac, Opus, alaw, ulaw…). It also reads `mvex/trex` defaults.
  - `_parse_traf` reads `tfhd` (flags 0x01 base offset, 0x02 sdi, 0x08 default duration, 0x10 size, 0x20 flags), `tfdt` (v1 = 64-bit) and `trun` (0x001 data offset, 0x004 first-sample flags, 0x100 duration, 0x200 size, 0x400 flags, 0x800 cto). The keyframe test is `!(flags & 0x00010000)`.
  - The reference track is the first `vide` track.
  - **Grouping:** start a new part when `current_ticks >= target` **and** (the fragment starts with a keyframe **or** `current_ticks >= 1.5×target`).
  - Output: `init_size` (offset of the first moof), `parts=[{o, s, d(ms), k(bool)}]`, `tracks={tid:{ts, t0(first tfdt)}}`, `duration_ms` (sum of parts), `size_bytes` (end of the last complete fragment), `codec` (e.g. `h264` or `h264+aac`).
- **MediaMTX fMP4 facts** (measured):
  - Each chunk starts with ftyp+moov and begins with a keyframe.
  - Each fragment's `tfdt` is version 1 and **starts at 0 in every file**; the video timescale is 90000.
  - A fragment closes **after** the sample at exactly partDuration, so it holds 31 frames at 30 fps. That's why the GOP rarely lines up (see 08).
- **rebase_timestamps(data, tracks, start_time):** for every moof/traf, `new_tfdt = old − t0 + round((start_time − 2020-01-01).seconds × timescale)`, written in place as 8 bytes (v1 only). Video bytes are never changed.
- **Upload:** items carry `parts` as a list of durations only (`[p["d"]…]`). Central doesn't need offsets.

## 5. Deletion, disk pressure, quota (`recordings/services.py`)
- `deletion_tick` (60 s): central deletions → `_delete_local` (path safety check: the target must be inside RECORDINGS_DIR; removes the file and the empty day folder; deletes the LocalSegment row), then `disk_pressure_cleanup()`, then `quota_cleanup()`, then `_confirm(ids)` with a KeyValue retry queue.
- `recordings_used_bytes(max_age_seconds=30)` is the `Sum(size_bytes)` of LocalSegment, cached.
- `quota_cleanup()`: if `used > quota×0.95`, pick the oldest chunks (only those older than DISK_MIN_KEEP_HOURS) **one by one until `used ≤ quota×0.90`**, delete them, and loop. The first version deleted batches of 50 and wiped everything; that was fixed.
- The quota comes from the heartbeat response (`apply_storage_quota`) and is stored in KeyValue `storage_quota_bytes`, so it survives restarts and central outages.

## 6. Status logic (`stream_status_tick`)
Order of checks:
1. MediaMTX down: CONNECTING ("media engine down").
2. Not ready and `record=false`: **IDLE** (on demand).
3. Not ready: CONNECTING.
4. Ready and `record=false`: STREAMING.
5. Ready and `record=true`: RECORDING if the last chunk end is within 2×segment + 30 s, or the stream became ready less than 1.5×segment + 30 s ago. Otherwise NOT_RECORDING.

`detail` lists the track codecs from MediaMTX (e.g. "H264").

## 7. Metrics (`node/metrics.py`)
- `cpu_memory()`: psutil `cpu_percent(interval=None)`, logical cpu_count, memory total, used (= total − available) and percent.
- `network_rates()`: whole-host `net_io_counters` delta in Mbit/s since the previous call.
- `gpus()`: `nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits`. Cached 10 s, 2 s timeout, MiB converted to bytes. Returns `[]` when there's no NVIDIA card. Dev PC: RTX 3050 Laptop 4 GB. Server: RTX 3050 8 GB.

## 8. Node API (all GET, CORS `*`)
`/api/v1/status`, `/api/v1/assignments`, `/api/v1/mediamtx/paths`, `/api/v1/segments?camera_id&limit`,
`/api/v1/logs?source=agent|mediamtx&lines=1..2000` (agent lines come from the ring buffer, MediaMTX lines from the last 256 KB of the log file),
`/api/v1/media/{id}/init.mp4`, `/part/{n}.m4s` (Cache-Control immutable), `/file.mp4`. See 06.

## 9. Gotchas
- Importing `database/config.py` **creates DATA_DIR**, so importing `main` (for example from `tools/export_openapi.py`) creates `media_node/data/`. The export script sets a temporary DATA_DIR. Delete stray `data/` folders created by tests.
- Windows: `taskkill /F` on the agent leaves MediaMTX running. The next start kills it (orphan logic).
- Ctrl+C in a console stops both, since they share the console group.
- Agent stdout encoding on Windows: run with `PYTHONUNBUFFERED=1` when redirecting to a file (the server launcher does).


## 10. Storage volumes (added 2026-10-15): several drives and network shares
A node records to a list of **volumes**, configured in central (Node → Storage tab), not in `.env`.
- **Default volume:** `RECORDINGS_DIR`, key `None` locally. Central auto-creates it on the first heartbeat that
  reports `default_recordings_dir`, seeding its cap from the old node-wide `storage_quota_bytes`.
- **Other volumes:** keyed by their central id.
- **Configuration:** comes in every heartbeat response (`volumes`) and is cached in KeyValue `volumes`. The old
  KeyValue `storage_quota_bytes` is kept as the legacy cap when central sends no volumes.
- **`app/storage/utils.py`** (pure, tested):
  - `Volume`, `update_full` (FULL at ≥ 95% of the cap or disk ≥ `DISK_MAX_USED_PERCENT`; free again below 90% and
    `DISK_TARGET_USED_PERCENT`).
  - `pick_target`: fill in order. It takes the first accepting, OK, not-full volume. If all are full it keeps the first
    one; if none is healthy it uses the default.
  - `classify_error` maps errors to messages, e.g. "Access denied… cmdkey /add:host", "Network share not reachable",
    "Drive or folder not found".
- **`app/storage/services.py` `storage`:**
  - `storage_tick` runs every `STORAGE_CHECK_INTERVAL_SECONDS` in **its own loop**. Each check runs in a worker thread
    with a 10 s timeout, because a dead SMB share can block for 20–30 s and must never delay heartbeats.
  - It creates the folder if missing, probes a write every 60 s, sums `size_bytes` per `volume_id`, and recomputes
    FULL and the target.
  - `local_drives()` (psutil, fixed drives) is sent in the heartbeat as `drives`.
- **MediaMTX:** `desired_paths()` sets a per-path `recordPath = <target>/%path/%Y-%m-%d/%H-%M-%S-%f`. A target switch
  is PATCHed by `reconcile_tick`, giving a 1–2 s gap while the path reloads.
- **Index:**
  - `LocalSegment.volume_id` / `SkippedFile.volume_id` are added to old SQLite files by `database/migrate.py`
    (idempotent `ALTER TABLE`).
  - `rel_path` stays globally unique, because it contains the camera and a microsecond timestamp.
  - Segment id: `uuid5(node, rel)` for the default volume (old ids unchanged), `uuid5(node, f"v{id}/{rel}")` otherwise.
- **Upload / serving:**
  - Uploads carry `volume_id` (central id).
  - Serving resolves the volume's folder. An offline volume answers **503 "Storage offline"** at once instead of
    touching the dead path.
- **Cleanup** (`deletion_tick`), in order:
  1. Central retention, deleting **by id via the local row**.
  2. `disk_safety_cleanup`, per volume, which protects the OS drive.
  3. `cap_cleanup`: a volume over its cap is trimmed to **99%** (`CAP_TRIM_TO`) only.
  4. `overwrite_cleanup`: only when every accepting volume is FULL. It deletes the oldest chunks **one by one with a
     running per-volume estimate**, stopping as soon as one volume is free again.
  - Chunks on offline volumes are skipped (not confirmed), so they are retried later.
  - Problems are logged once (`_report_once`), not every tick.
- **Bugs found while testing, don't reintroduce them:**
  - Trimming an over-cap volume to 90% made it "free" again. Recording jumped back to it and the later volumes were
    never used. That's why it trims to 99%.
  - The overwrite deleted a whole batch of 50 oldest chunks before re-checking and **wiped entire volumes**. It now
    selects chunk by chunk.
- Removing a volume in central: the node forgets its local rows (the files are left on disk).
- Tests: `media_node/tests` (rules, config mapping, SQLite migration, overwrite selection), run with
  `py -m pytest` (`DATA_DIR` set to a scratch folder).
