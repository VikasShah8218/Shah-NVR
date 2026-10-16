# Shah-NVR

A distributed network video recorder (NVR): two backend services and a web UI.

| Service | Folder | Role |
|---|---|---|
| **Central Manager** | `central_manager/` | The "main server". Camera registry, node registry, scheduler and failover, recording catalog, live-URL lookup and HLS playback playlists. **Never handles video.** |
| **Media Node** | `media_node/` | The "recording/streaming server". Runs MediaMTX, pulls the cameras it's assigned, records 60-second fMP4 chunks, indexes them, reports them to the central manager and serves recorded video. **Never connects to PostgreSQL.** |
| **Web UI** | `nvr_client/` | React + TypeScript client for testing every feature (see [nvr_client/README.md](nvr_client/README.md)). |

```
Camera ──RTSP──► Media Node (MediaMTX) ──► chunks on disk ──► chunk index ──► Central (PostgreSQL)
                     │
                     ├── Live:     RTSP / LL-HLS / WebRTC ──► VLC, browser
                     └── Recorded: init + parts (byte slices) ◄── HLS playlist built by Central
```

Authentication and TLS aren't implemented yet (planned for a later phase).

## H2: camera video settings (server, node and web only)

The web camera-detail **Video** tab reads the actual encoder configuration and advertised options through
central → node → camera. It supports H.264/H.265, resolution, frame rate, bitrate, GOP, quality and codec
profile; CBR/VBR is editable only when exposed through Media2. Media2 is preferred, with a Media1 read
fallback. Unsupported/unknown limits stay read-only. Desktop support is deliberately unchanged.

For an existing installation, back up PostgreSQL, stop central, then run the **existing** migrations:

```powershell
cd central_manager
aerich upgrade
```

This applies migrations 5 (encoder journal) and 6 (recording decoder fingerprint); do not run
`init-db` or generate new migrations on an existing installation. Restart central and the media node,
then rebuild/restart `nvr_client`. These migrations target PostgreSQL, the supported central database.
New in-memory SQLite databases are used only by tests.

Workflow and safeguards:

- Select main/sub. Manually added RTSP streams require an explicit ONVIF profile mapping; this does not
  change their RTSP URL. Use the same canonical ONVIF address for duplicate entries of one physical device.
- Presets propose editable values within advertised limits. Estimates are decimal video GB/day at the
  bitrate limit (`Mbps × 10.8`), excluding audio/overhead; VBR varies. Same bitrate means the same estimate
  regardless of codec. "Best quality" is a suggestion, not a measured quality guarantee.
- Review before applying. Revisions reject stale edits; shared encoders require acknowledgement.
  A durable device mutex and operation IDs protect concurrent/repeated requests. The node sends no blind
  Set retry and never falls back to another media service after sending a Set.
- Readback verification is separate from recovery. Only the affected device's assigned MediaMTX paths
  are restarted; heartbeat and recording evidence remain pending until observed. Inspect live view and
  a new recorded chunk as well. On-demand streams may remain idle until watched.
- Unknown outcomes stay locked. Wait two minutes, then use **Check uncertain operation** for fresh
  readback on the original node. Review actual values before another action. Restore is explicit,
  capability-checked and uses saved previous values; it is never an automatic retry or rollback.
- Bulk copies changed fields only, at most 20 targets, with per-camera preflight/results. Shared or
  unsupported targets are skipped, not silently changed to alternatives. A successful source apply
  clears its draft; create a draft before preflighting bulk targets.
- New recording indexes fingerprint decoder configuration, so resolution/SPS/PPS changes as well as
  codec changes produce HLS discontinuities. Existing recordings are not rewritten. H.265 decoding
  still depends on the browser/device; an H.264 substream does not make H.265 main recordings compatible.

Security remains the existing trusted-network model: these APIs are not authenticated. Do not expose
central or node ports publicly. Continue using one central process and one agent process per node.
Camera firmware/vendor behavior and browser playback require physical-camera acceptance testing.

Automated checks (no camera writes):

```powershell
cd central_manager
python -m pytest tests -q
cd ../media_node
python -m pytest tests -q
cd ../nvr_client
npm.cmd run test:encoder
npm.cmd run build
npm.cmd run lint
```

Central tests force an in-memory database before importing application settings. Node encoder tests use
an HTTP/SOAP camera simulator, covering Media1/2, readback, timeout uncertainty, stale/shared settings and
targeted restart. Physical acceptance: apply a small bitrate change on one approved test camera, check
live + recording, restore, then test H.265 (on a capable camera), main/sub isolation, shared encoders and
mixed-success bulk. Confirm that camera names/metadata and the existing desktop still behave normally.

---

## 1. Requirements

- Python 3.12+ (tested on 3.13) and the `nvr` virtualenv (`workon nvr`)
- PostgreSQL with a database named `nvr`
- FFmpeg on PATH (only needed for the camera simulator)
- MediaMTX: already in `media_node/bin/mediamtx.exe` (v1.21.2, Windows amd64). On Linux, download the matching build from https://github.com/bluenviron/mediamtx/releases and set `MEDIAMTX_BIN`.

```bash
workon nvr
pip install -r central_manager/requirements.txt -r media_node/requirements.txt
```

## 2. Configure

Each service reads the `.env` next to its `main.py` (`.env.example` lists every option).

- `central_manager/.env`: set `DB_USER` / `DB_PASSWORD`.
- `media_node/.env`: set `PUBLIC_HOST` to this machine's LAN IP if VLC runs on another PC. `127.0.0.1` works for same-PC testing.

## 3. Create the database tables (Aerich)

```bash
cd central_manager
aerich init-db            # first time only: creates tables + first migration
# after changing models later:
aerich migrate --name <change>
aerich upgrade
```

Aerich is already initialised (`pyproject.toml` and `migrations/` exist). The media node uses its own small SQLite file (`media_node/data/node_state.sqlite3`), whose tables are created automatically.

## 4. Run

Use three terminals, all with `workon nvr`:

```bash
# 1) Central manager   -> http://localhost:8000/docs
cd central_manager && py main.py

# 2) Media node        -> http://localhost:7100/docs
cd media_node && py main.py

# 3) (optional) fake cameras if you have no real ones
py tools/camera_simulator.py --count 2      # rtsp://127.0.0.1:8654/sim-1, sim-2

# 4) (optional) web UI                       -> http://localhost:5180
cd nvr_client && npm install && npm run dev
```

The media node starts MediaMTX itself, registers with the central manager and starts sending heartbeats.

## 5. Test with Postman + VLC

Import `docs/Shah-NVR.postman_collection.json` into Postman. The steps below use curl so you can see each request.

**Add a camera** (the scheduler assigns it to a node within about 5 s):

```bash
curl -X POST http://localhost:8000/api/v1/cameras -H "Content-Type: application/json" -d '{
  "name": "Gate Camera",
  "username": "admin", "password": "secret",
  "streams": [
    {"profile": "main", "source_url": "rtsp://192.168.1.64:554/Streaming/Channels/101", "record": true},
    {"profile": "sub",  "source_url": "rtsp://192.168.1.64:554/Streaming/Channels/102", "record": false}
  ]
}'
```
(With the simulator, use `rtsp://127.0.0.1:8654/sim-1` and `sim-2`. The username and password are added to the URL automatically.)

**Watch live:** `GET /api/v1/cameras/1/live` returns the URLs. In VLC, open **Media → Open Network Stream**:
- `rtsp://<node>:8554/cam-1/main` (lowest delay)
- `http://<node>:8888/cam-1/main/index.m3u8` (LL-HLS)

**Watch recordings:** wait until at least one 60-second chunk has finished, then open this in VLC:
```
http://localhost:8000/api/v1/playback/1/index.m3u8?minutes=10
http://localhost:8000/api/v1/playback/1/index.m3u8?start=2026-10-12T10:00:00Z&end=2026-10-12T10:30:00Z
```
Times are UTC: use the `Z` suffix, or an offset such as `+05:30` written as `%2B05:30` in a URL.

**Timeline (segments + gaps):** `GET /api/v1/cameras/1/recordings?minutes=60`

## 6. API overview

| Area | Endpoint |
|---|---|
| Cameras | `POST/GET /api/v1/cameras`, `GET/PATCH/DELETE /api/v1/cameras/{id}`, `POST/PATCH/DELETE /api/v1/cameras/{id}/streams[/{profile}]` |
| Live | `GET /api/v1/cameras/{id}/live` |
| Recordings | `GET /api/v1/cameras/{id}/recordings?minutes=` or `?start=&end=` |
| Playback (HLS VOD) | `GET /api/v1/playback/{id}/index.m3u8?minutes=` or `?start=&end=` |
| Nodes | `GET /api/v1/nodes`, `PATCH /api/v1/nodes/{id}` (capacity, `storage_quota_gb`), `POST /api/v1/nodes/{id}/drain\|cordon\|activate`, `DELETE /api/v1/nodes/{id}` |
| Assignments | `GET /api/v1/assignments`, `PUT /api/v1/assignments/{camera_id}`, `GET /api/v1/assignments/{camera_id}/history`, `POST /api/v1/assignments/run-scheduler` |
| Cluster | `GET /api/v1/cluster/health` |
| Internal (node → central) | `/internal/v1/...`: register, heartbeat, assignments, stream status, segments, deletions |
| Media node | `GET /api/v1/status`, `/api/v1/assignments`, `/api/v1/mediamtx/paths`, `/api/v1/segments`, `/api/v1/logs?source=agent\|mediamtx`, `/api/v1/media/{segment}/init.mp4\|part/{n}.m4s\|file.mp4` |

## 7. How it works

**Recording**
1. The scheduler (central, every 5 s) places each enabled camera on the least-loaded healthy node and records the move with an increasing `generation`.
2. The node's reconcile loop (every 5 s) fetches its assignments and adds or removes MediaMTX paths through the MediaMTX API. One camera connection is shared by recording and all live viewers.
3. MediaMTX writes `data/recordings/cam-<id>/<profile>/<date>/<time>.mp4` as fMP4 (1-second fragments, 60-second chunks).
4. The scanner finds finished chunks and indexes them by reading box headers only (no decoding). It records where each ~4-second part sits in the file, starting parts on keyframes whenever the camera's GOP allows. Set the camera's keyframe interval to its FPS (1 s GOP) for best seeking.
5. The uploader sends chunk metadata to the central manager in batches. It's idempotent (deterministic IDs) and queued in local SQLite, so nothing is lost while the central manager is down.

**Playback**
1. The central manager finds the chunks for the time range and writes an HLS VOD playlist. Its URLs point **directly at the node(s)** holding each chunk, so one playlist can span several nodes.
2. The node serves each part as a byte slice of the original file. It rewrites the 8-byte fragment timestamps to one absolute timeline, so chunks join seamlessly across files and nodes. Video data is never re-encoded or copied.

**Failover**
- A node that misses heartbeats for 15 s becomes `UNREACHABLE`. Once its 30-second lease plus a 10-second grace period runs out, its cameras move to another node with `generation + 1`. In testing, recording resumed about 43 s after a hard kill.
- If the central manager is down, nodes keep recording from their cached assignments and upload chunk metadata once it's back.
- A node that comes back stops cameras it no longer owns, and its startup scan indexes any chunks written while it was down. A chunk cut off mid-write is kept up to its last complete 1-second fragment.

**Retention:** every 10 minutes the central manager marks chunks older than the camera's `retention_days`. Nodes delete those files and confirm. Separately, each node deletes its oldest chunks itself if its disk goes above `DISK_MAX_USED_PERCENT`.

**Storage quota:** an admin can limit how much a node may use for recordings (`PATCH /api/v1/nodes/{id}` with `storage_quota_gb`, or the Media Nodes page). The node receives the quota in every heartbeat and caches it locally. Above 95% of the quota it deletes just enough of its oldest chunks to get back under 90%, and confirms the deletions to the central manager.

**Node metrics:** each heartbeat reports CPU (percent and cores), RAM, NVIDIA GPU (via `nvidia-smi`, when present), network in/out, disk and the bytes used by recordings.

## 8. Two nodes on one PC (failover testing)

Copy `media_node/.env` values into environment variables, or use a second copy of the folder, and change `NODE_NAME`, `PORT`, every MediaMTX port, `DATA_DIR` and `RECORDINGS_DIR`. For example: `NODE_NAME=node-2 PORT=7200 MEDIAMTX_API_PORT=9897 MEDIAMTX_METRICS_PORT=9898 RTSP_PORT=8564 RTP_PORT=8010 RTCP_PORT=8011 HLS_PORT=8898 WEBRTC_PORT=8899 WEBRTC_UDP_PORT=8199 DATA_DIR=./data2 RECORDINGS_DIR=./data2/recordings`.

## 9. Known limits (current phase)

- No authentication or TLS (planned). `CORS_ORIGINS` defaults to `*` for the web UI; restrict it in production.
- GPU metrics are NVIDIA-only for now.
- Run **one** central manager instance; the scheduler has no leader election yet.
- Camera passwords are stored in plain text in PostgreSQL (encryption is planned with auth).
- Playback ranges are limited to `PLAYBACK_MAX_HOURS` (default 24 h) per request.
- `recording_segments` isn't partitioned yet. Add time partitioning before running large camera counts.
