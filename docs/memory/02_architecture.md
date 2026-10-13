# 02: System architecture

## 1. Big picture
```
                    ┌──────────────────────────── nvr_client (React, :5180) ───────────────────────────┐
                    │  REST (CORS) to central            read-only REST + recorded media to nodes       │
                    │  WebRTC WHEP / LL-HLS live straight from node MediaMTX                            │
                    └──────────┬──────────────────────────────────────────────┬────────────────────────┘
                               │                                              │
┌──────────────────────────────▼───────────────┐            ┌────────────────▼─────────────────────────────────┐
│ CENTRAL MANAGER  (FastAPI :8000)             │  internal  │ MEDIA NODE  (FastAPI agent :7100)                │
│ PostgreSQL "nvr" via Tortoise + Aerich       │◄──REST────►│ SQLite node_state.sqlite3 (Tortoise, auto schema)│
│ apps: cameras nodes assignments recordings   │  register  │ apps: node  mediamtx  recordings                 │
│       playback cluster                       │  heartbeat │ child process: MediaMTX v1.21.2                  │
│ loops: scheduler(5s) node-health(5s)         │  assign.   │   RTSP :8554  LL-HLS :8888  WebRTC :8889         │
│        retention(600s)                       │  segments  │   API 127.0.0.1:9997  metrics 127.0.0.1:9998     │
│ NEVER handles video                          │  deletions │ disk: data/recordings/cam-<id>/<profile>/<date>/ │
└──────────────────────────────────────────────┘            └──────────────────────▲───────────────────────────┘
                                                                                   │ RTSP pull (TCP), 1 connection
                                                                              IP cameras
```

**Principles (do not break these):**
1. **The central manager never carries video.** It returns URLs; video goes node → client.
2. **The node never connects to PostgreSQL.** All state changes go through the central manager's internal API. The node keeps a local SQLite queue so it works offline.
3. **One upstream connection per camera profile.** MediaMTX fans it out to the recorder and every viewer.
4. **No decoding or transcoding** in the normal path. Recording is MediaMTX stream copy. Playback serves byte slices of the recorded files.
5. **Level-triggered reconciliation.** Every loop converges actual state to desired state, so it is idempotent and survives restarts.
6. **Continuity first.** Nodes keep recording on cached assignments when the central manager is down. A recording gap is worse than a duplicate.

## 2. Technology choices
| Layer | Choice | Notes |
|---|---|---|
| Backend language | Python 3.12 (server) / 3.13 (dev PC) | `workon nvr` venv |
| API framework | FastAPI, uvicorn (`uvicorn.run(app)` in main.py) | tested with fastapi 0.143, uvicorn 0.54 |
| Validation / settings | Pydantic v2, pydantic-settings | `.env` next to main.py |
| ORM | Tortoise ORM **1.1.8** (major v1) | Aerich 0.10.1 warns "use native migrations for tortoise>=1.0", but works |
| DB central | PostgreSQL (asyncpg) | DB `nvr`, user `postgres` (password in environment.local.md) |
| DB node | SQLite (aiosqlite) | `media_node/data/node_state.sqlite3` |
| Media engine | **MediaMTX v1.21.2** | binary in `media_node/bin/` (git-ignored; download from GitHub releases) |
| HTTP client | httpx (async) | node → central, node → MediaMTX API |
| Metrics | psutil, `nvidia-smi` | GPU is NVIDIA-only |
| Timezone data | `tzdata` package | **required on Windows**, or Tortoise crashes (ZoneInfo "UTC" not found) |
| Frontend | Vite 8, React 19, TS 6, Tailwind v4, shadcn/ui (radix-nova), TanStack Query 5, React Router 7, hls.js, recharts 3, sonner, date-fns, lucide | see 05 |

## 3. Ports
| Port | Who | Notes |
|---|---|---|
| 8000/tcp | central API | `/docs` Swagger |
| 7100/tcp | node agent API | recorded media, status, logs |
| 8554/tcp | MediaMTX RTSP | live RTSP, e.g. `rtsp://<node>:8554/cam-1/main` |
| 8000/udp, 8001/udp | MediaMTX RTP/RTCP | UDP, so no clash with central's TCP 8000 |
| 8888/tcp | MediaMTX LL-HLS | `http://<node>:8888/cam-1/main/index.m3u8` |
| 8889/tcp, 8189/udp | MediaMTX WebRTC (WHEP) + ICE | `http://<node>:8889/cam-1/main/whep` |
| 9997, 9998 | MediaMTX API / metrics | bound to 127.0.0.1 only |
| 8654/tcp | camera simulator (a separate MediaMTX) | dev only |
| 5180/tcp | nvr_client Vite dev server | 5173 is taken by the user's HID Trinetra app |

Second node on the same PC: change every port (example: `PORT=7200 MEDIAMTX_API_PORT=9897 MEDIAMTX_METRICS_PORT=9898 RTSP_PORT=8564 RTP_PORT=8010 RTCP_PORT=8011 HLS_PORT=8898 WEBRTC_PORT=8899 WEBRTC_UDP_PORT=8199`) plus `NODE_NAME`, `DATA_DIR` and `RECORDINGS_DIR`.

## 4. Naming conventions
- MediaMTX path: **`cam-<camera_id>/<profile>`**, e.g. `cam-1/main`. The node manages only paths starting with `cam-`.
- Recording file: `RECORDINGS_DIR/cam-<id>/<profile>/<YYYY-MM-DD>/<HH-MM-SS-ffffff>.mp4`. MediaMTX writes this from `recordPath: <dir>/%path/%Y-%m-%d/%H-%M-%S-%f`. **The filename time is the node's local time.** `parse_rel_path` converts it to UTC.
- Segment id: `uuid5(NAMESPACE_URL, "shah-nvr://<node_name>/<rel_path>")`. It is deterministic, which makes uploads idempotent.
- Camera and node IDs are integers (easy to use in Postman). Segment IDs are UUIDs.

## 5. Flow A: recording (camera → disk → catalog)
**Central manager:**
1. On startup: Tortoise starts, then the loops start: `node-health` (5 s), `scheduler` (5 s), `retention` (600 s).
2. `scheduler_tick` (app/assignments/services.py):
   - For each enabled camera with no node (or on a DRAINING/OFFLINE node, or on an UNREACHABLE node whose lease expired more than FAILOVER_GRACE ago), pick a node.
   - Selection, `pick_node`: least loaded by `assigned/capacity`. Eligible nodes are READY/ACTIVE, with a fresh heartbeat, under capacity, and disk used below 97%.
   - `assign_camera` runs in one transaction: `SELECT … FOR UPDATE`, `generation += 1`, set node and lease, close the open `AssignmentHistory` and open a new one, and set stream statuses to ASSIGNED.
   - Disabled cameras are released (node set to null, generation bumped).
   - At most `MAX_MOVES_PER_CYCLE` (20) moves per cycle.

**Media node:**
3. On startup:
   - Load the cached node_id, assignments and quota from the KeyValue store.
   - `kill_orphan_mediamtx()`: kill any mediamtx process listening on our API or RTSP port.
   - Write `data/mediamtx.yml` and start MediaMTX (supervisor with backoff restart). Wait until `/v3/config/global/get` answers, then `POST /internal/v1/nodes/register` (upsert by name).
4. `heartbeat_tick` (5 s):
   - Sends metrics (CPU, cores, RAM, GPUs, disk, recordings_bytes, net Mbps, MediaMTX state, pending uploads).
   - The response renews leases for all of this node's assignments and carries `storage_quota_bytes`.
   - A 404 response means central lost the node, so re-register.
5. `reconcile_tick` (5 s):
   - `GET /internal/v1/nodes/{id}/assignments` returns the desired cameras with **decrypted source URLs** (credentials injected by `build_source_url`). On failure, use the SQLite cache.
   - Compute the desired MediaMTX paths: `{source, record, sourceOnDemand: not record, rtspTransport}`.
   - Diff against `GET /v3/config/paths/list`, then add, patch or delete.
6. MediaMTX pulls RTSP and records fMP4 chunks of `SEGMENT_SECONDS` (60 s) with 1 s fragments. MediaMTX cuts a new chunk at the first keyframe after 60 s.
7. `scan_tick` (5 s):
   - Lists the newest two day folders. A file is finished when a newer file exists or its mtime is more than 30 s old.
   - `index_fmp4()` (reads box headers only) produces the init size, parts (offset, size, duration, keyframe flag), tracks (timescale, first tfdt) and codec.
   - Saves a `LocalSegment` (uploaded=False).
   - The first scan after startup checks **all** folders (crash recovery). Unreadable files go into `SkippedFile`.
8. `upload_tick` (3 s): batches of up to 200 → `POST /internal/v1/recordings/segments`. The central side is idempotent (bulk create, ignoring existing IDs) and updates `CameraStream.last_segment_at`.
9. `stream_status_tick` (10 s): reads MediaMTX `/v3/paths/list` and reports one of CONNECTING, IDLE, STREAMING, RECORDING or NOT_RECORDING per stream. Central ignores reports from a node that no longer owns the camera.

## 6. Flow B: live viewing
1. Client: `GET /api/v1/cameras/{id}/live` returns, for each profile, `rtsp://host:8554/cam-1/main`, `http://host:8888/cam-1/main/index.m3u8` and `http://host:8889/cam-1/main` (the WebRTC page; append `/whep` for WHEP).
2. VLC: open the RTSP URL. Browser: the React `LivePlayer` tries **WHEP** first (non-trickle, 12 s timeout) and falls back to **hls.js LL-HLS**.
3. A `record=false` stream is `sourceOnDemand`: MediaMTX connects to the camera only while someone watches (status IDLE).
4. The `live` query refetches every 15 s, so a camera that moved to another node gets its new URLs and the player reconnects.

## 7. Flow C: recorded playback (HLS VOD, no remux, no copy)
1. Client: `GET /api/v1/playback/{camera_id}/index.m3u8?profile=main&start=…&end=…` (or `?minutes=N`). Open it directly in VLC or hls.js.
2. Central (`app/playback/utils.py::build_vod_playlist`):
   - Finds the AVAILABLE segments that overlap the range and skips nodes that are UNREACHABLE or OFFLINE.
   - Walks each segment's `parts` (durations in ms), keeping only parts inside the range. Parts already covered by an earlier segment (failover overlap) are dropped.
   - Writes `#EXT-X-MAP:URI=<node>/api/v1/media/<seg>/init.mp4`, `#EXT-X-PROGRAM-DATE-TIME`, `#EXTINF` and `<node>/api/v1/media/<seg>/part/<n>.m4s`.
   - Adds `#EXT-X-DISCONTINUITY` **only** at a real gap (more than 1 s) or a codec change.
   - Does not write `EXT-X-INDEPENDENT-SEGMENTS`, because parts may start mid-GOP.
3. Node (`app/recordings/router.py`):
   - `init.mp4` returns bytes `[0, init_size)`.
   - `part/<n>.m4s` returns `bytes[o:o+s]` **with every `tfdt` rewritten** to absolute time since 2020-01-01 (`rebase_timestamps`). Timestamps therefore increase across chunks and nodes.
   - `file.mp4` returns the whole chunk for download.
4. The client's hls.js `playingDate` (from PROGRAM-DATE-TIME) gives the real recorded wall-clock time. This was verified to match the camera's burned-in clock exactly.

## 8. Flow D: failover and ownership
- Timings:

  | Setting | Value |
  |---|---|
  | Heartbeat | every 5 s |
  | `HEARTBEAT_TIMEOUT_SECONDS` | 15 (node → UNREACHABLE) |
  | `LEASE_TTL_SECONDS` | 30 |
  | `FAILOVER_GRACE_SECONDS` | 10 |

  Measured locally: a hard kill led to UNREACHABLE at about 13 s, reassignment at about 39 s, and recording on the new node at about 43 s.
- The reassignment bumps the generation and opens a new history row.
- **A partitioned old node keeps recording** from its cache. When it reconnects, its assignments no longer include the camera, so reconcile deletes the path (self-fencing).
- Segments recorded by the old node during the overlap are **kept**. The playlist dedupes overlapping parts by time.
- When a node restarts, its first scan indexes chunks written before the crash, including the truncated last one (cut at the last complete fragment).

## 9. Flow E: retention, disk pressure and quota
- **Retention** (central, every 600 s): segments with `end_time < now − camera.retention_days` become DELETING.
  - The node's `deletion_tick` (60 s) calls `GET /internal/v1/nodes/{id}/deletions`, deletes the files and empty day folders, and confirms with `POST …/deleted`.
  - Central then deletes those rows.
  - Confirmations that fail are kept in KeyValue `pending_deleted` and retried.
- **Disk pressure** (node): above `DISK_MAX_USED_PERCENT` (95), delete the oldest chunks until below `DISK_TARGET_USED_PERCENT` (92). Chunks younger than `DISK_MIN_KEEP_HOURS` (1 h) are never deleted.
- **Storage quota** (node, set from central):
  - `MediaNode.storage_quota_bytes`, set with `PATCH /api/v1/nodes/{id}` `{storage_quota_gb}` (null = unlimited).
  - It travels in the heartbeat response and is cached in KeyValue `storage_quota_bytes`.
  - When `recordings_bytes` > 95% of the quota, delete **just enough** of the oldest chunks to get under 90%. Same 1 h guard.

## 10. State machines
- **Node:** register → READY. A heartbeat moves READY/ACTIVE/UNREACHABLE to ACTIVE if it has assignments, otherwise READY. DRAINING and CORDONED are kept. A missed heartbeat (15 s) moves READY/ACTIVE/DRAINING/CORDONED to UNREACHABLE. Admin actions: drain to DRAINING, cordon to CORDONED, activate to READY. OFFLINE exists in the enum, but no endpoint sets it.
- **Stream** (`CameraStream.status`):
  - UNASSIGNED becomes ASSIGNED (scheduler), then CONNECTING, then STREAMING or RECORDING (node reports).
  - NOT_RECORDING: the stream is ready, but no chunk has finished in 2×segment + 30 s.
  - IDLE: on-demand, nobody watching.
  - DISABLED: the camera is disabled.
  - UNKNOWN: central marks it after 60 s with no report.
- **Segment** (central): AVAILABLE becomes DELETING (retention), and the row is deleted once the node confirms.

## 11. Data model (central, PostgreSQL)
| Table | Columns (key ones) |
|---|---|
| `cameras` | id int PK, name, description, username, password (**plaintext for now**), enabled, retention_days, created_at, updated_at |
| `camera_streams` | id, camera FK CASCADE, profile, source_url, record, rtsp_transport, status, status_detail, bytes_received, last_status_at, last_segment_at; unique (camera, profile) |
| `media_nodes` | id, name UNIQUE, api_url, media_host, rtsp_port, hls_port, webrtc_port, capacity_cameras, **storage_quota_bytes** (null), version, mediamtx_version, state, last_heartbeat_at, metrics JSON, registered_at, updated_at |
| `camera_assignments` | id, camera O2O CASCADE, node FK SET_NULL (null = unassigned), generation, lease_expires_at, reason, timestamps. **The row is kept forever**, so the generation keeps increasing. |
| `assignment_history` | camera, node, generation, reason, started_at, ended_at |
| `recording_segments` | id UUID (from node), camera FK, profile, node FK, generation, start_time, end_time, duration_ms, size_bytes, codec, file_path (relative), **parts JSON (list of ms durations)**, status AVAILABLE/DELETING, created_at; indexes (camera_id, profile, start_time) and (status, end_time) |
| `aerich` | migration bookkeeping |

The node's SQLite holds:
- `key_value` (node_id, assignments, storage_quota_bytes, pending_deleted);
- `local_segments` (id, camera_id, profile, generation, rel_path UNIQUE, start/end, duration, size, init_size, codec, **parts JSON [{o,s,d,k}]**, **tracks JSON {tid:{ts,t0}}**, uploaded);
- `skipped_files`.
