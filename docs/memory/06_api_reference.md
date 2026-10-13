# 06: API reference

All payloads are JSON. Times are ISO-8601. **Naive datetimes in query parameters are treated as UTC.** Use `Z` or an offset, and URL-encode `+` as `%2B`.
There is no authentication yet. Swagger: central `:8000/docs`, node `:7100/docs`.

## 1. Central: public (`/api/v1`)
### Cameras
| Method | Path | Body / query | Notes |
|---|---|---|---|
| POST | `/cameras` | `CameraCreate` | 201 → CameraOut |
| GET | `/cameras?enabled=` | | list |
| GET | `/cameras/{id}` | | |
| PATCH | `/cameras/{id}` | `CameraUpdate` (any of name, description, username, password, enabled, retention_days) | enabled=false sets streams to DISABLED; the scheduler releases the camera |
| DELETE | `/cameras/{id}` | | 409 if recordings exist |
| POST | `/cameras/{id}/streams` | `StreamIn` | 409 if the profile exists |
| PATCH | `/cameras/{id}/streams/{profile}` | `StreamUpdate` (source_url, record, rtsp_transport) | the node picks it up on its next reconcile |
| DELETE | `/cameras/{id}/streams/{profile}` | | 409 if it's the last stream |
| GET | `/cameras/{id}/live?profile=` | | 409 if disabled or unassigned → LiveOut |
| GET | `/cameras/{id}/recordings?profile=main&start=&end=` or `&minutes=N` | | TimelineOut (segments + gaps + coverage) |

```jsonc
// CameraCreate
{ "name": "Gate Camera", "description": null, "username": "root", "password": "…",
  "enabled": true, "retention_days": 7,
  "streams": [
    { "profile": "main", "source_url": "rtsp://192.168.1.241:554/axis-media/media.amp?videocodec=h264&resolution=1920x1080&fps=30&videokeyframeinterval=30", "record": true,  "rtsp_transport": "tcp" },
    { "profile": "sub",  "source_url": "rtsp://192.168.1.241:554/axis-media/media.amp?videocodec=h264&resolution=640x360&fps=30&videokeyframeinterval=30",   "record": false, "rtsp_transport": "tcp" } ] }
// profile must match ^[a-z0-9_-]{1,32}$ ; source_url must start with rtsp/rtsps/rtmp/srt/http(s)
// rtsp_transport: tcp | udp | automatic

// CameraOut
{ "id": 1, "name": "...", "description": null, "username": "root", "has_password": true, "enabled": true,
  "retention_days": 7, "created_at": "...", "updated_at": "...",
  "streams": [ { "id": 1, "profile": "main", "source_url": "...", "record": true, "rtsp_transport": "tcp",
                 "status": "RECORDING", "status_detail": "H264", "bytes_received": 212375,
                 "last_status_at": "...", "last_segment_at": "..." } ],
  "assignment": { "node_id": 1, "node_name": "shah-ho-node-1", "generation": 1, "lease_expires_at": "..." } }

// LiveOut
{ "camera_id": 1, "node_id": 1, "node_name": "...", "generation": 1,
  "streams": [ { "profile": "main", "codec_note": "...",
                 "rtsp": "rtsp://100.64.182.102:8554/cam-1/main",
                 "hls": "http://100.64.182.102:8888/cam-1/main/index.m3u8",
                 "webrtc": "http://100.64.182.102:8889/cam-1/main" } ] }   // WHEP = webrtc + "/whep"

// TimelineOut
{ "camera_id": 1, "profile": "main", "start": "...", "end": "...", "recorded_seconds": 147.99,
  "coverage_percent": 11.1, "total_size_bytes": 3804758,
  "segments": [ { "id": "uuid", "profile": "main", "node_id": 1, "generation": 1, "start_time": "...", "end_time": "...",
                  "duration_ms": 60832, "size_bytes": 1363148, "codec": "h264", "status": "AVAILABLE" } ],
  "gaps": [ { "start_time": "...", "end_time": "...", "seconds": 14.79 } ] }
```

### Playback
| GET | `/playback/{camera_id}/index.m3u8?profile=main&start=&end=` or `&minutes=N` | → `application/vnd.apple.mpegurl` HLS VOD; 404 if nothing is playable |
|---|---|---|

```
#EXTM3U
#EXT-X-VERSION:7
#EXT-X-TARGETDURATION:7
#EXT-X-MEDIA-SEQUENCE:0
#EXT-X-PLAYLIST-TYPE:VOD
#EXT-X-MAP:URI="http://<node>:7100/api/v1/media/<seg>/init.mp4"
#EXT-X-PROGRAM-DATE-TIME:2026-10-12T09:16:37.052Z
#EXTINF:6.200,
http://<node>:7100/api/v1/media/<seg>/part/0.m4s
...
#EXT-X-DISCONTINUITY            (only at a real gap > 1 s or a codec change)
#EXT-X-ENDLIST
```

### Nodes, assignments, cluster
| Method | Path | Notes |
|---|---|---|
| GET | `/nodes`, `/nodes/{id}` | NodeOut (metrics = last heartbeat payload, assigned_cameras, storage_quota_bytes) |
| PATCH | `/nodes/{id}` | `{ "capacity_cameras": 40, "storage_quota_gb": 100 }`; `storage_quota_gb: null` removes the limit |
| POST | `/nodes/{id}/drain` · `/cordon` · `/activate` | state changes (activate → READY) |
| DELETE | `/nodes/{id}?force=false` | 409 while cameras are assigned; 409 with recordings unless force |
| GET | `/assignments?node_id=` | AssignmentOut[] |
| PUT | `/assignments/{camera_id}` | `{ "node_id": 2 }`: manual move (node must be READY/ACTIVE/CORDONED) |
| GET | `/assignments/{camera_id}/history?limit=50` | |
| POST | `/assignments/run-scheduler` | 204 |
| GET | `/cluster/health` | `{cameras_total, cameras_enabled, streams_by_status{}, nodes_by_state{}, segments_last_hour, segments_total}` |

## 2. Central: internal (`/internal/v1`, called by nodes only)
| Method | Path | Body → Response |
|---|---|---|
| POST | `/nodes/register` | `{name, api_url, media_host, rtsp_port, hls_port, webrtc_port, capacity_cameras, version, mediamtx_version}` → `{node_id, state, heartbeat_interval_seconds}` (upsert by name) |
| POST | `/nodes/{id}/heartbeat` | HeartbeatIn → `{node_id, state, lease_expires_at, assignments, storage_quota_bytes}` |
| GET | `/nodes/{id}/assignments` | → `{node_id, state, cameras:[{camera_id, camera_name, generation, streams:[{profile, path_name, source_url (WITH credentials), record, rtsp_transport}]}]}` |
| POST | `/nodes/{id}/stream-status` | `{items:[{camera_id, profile, status, detail, bytes_received}]}` → 204 (ignored for cameras the node doesn't own) |
| POST | `/recordings/segments` | `{node_id, items:[{id, camera_id, profile, generation, start_time, end_time, duration_ms, size_bytes, codec, file_path, parts:[ms…]}]}` (≤1000) → `{accepted, duplicates, ignored}` |
| GET | `/nodes/{id}/deletions?limit=500` | → `[{id, file_path}]` (status DELETING) |
| POST | `/nodes/{id}/deleted` | `{ids:[uuid…]}` → 204 (rows deleted) |

```jsonc
// HeartbeatIn (all optional)
{ "cpu_percent": 22.5, "cpu_count": 20, "memory_percent": 81, "memory_total_bytes": 16936394752, "memory_used_bytes": 13600000000,
  "gpus": [ { "name": "NVIDIA GeForce RTX 3050", "utilization_percent": 12, "memory_used_bytes": 1259339776, "memory_total_bytes": 8589934592 } ],
  "disk": { "path": "F:\\...\\recordings", "total_bytes": 214748364800, "free_bytes": 177000000000, "used_percent": 17.6 },
  "recordings_bytes": 234988324, "net_rx_mbps": 1.78, "net_tx_mbps": 0.3,
  "mediamtx_running": true, "paths_configured": 2, "paths_ready": 1, "pending_uploads": 0 }
```

## 3. Media node (`:7100/api/v1`, all GET, CORS `*`)
| Path | Returns |
|---|---|
| `/status` | `{node_name, node_id, api_url, central_url, central_online, last_central_contact, mediamtx_running, mediamtx_version, recordings_dir, disk{}, assigned_cameras, ready_paths[], pending_uploads, local_segments}` |
| `/assignments` | cached assignment dicts (same shape as the central internal assignments → cameras) |
| `/mediamtx/paths` | MediaMTX `/v3/paths/list` items |
| `/segments?camera_id=&limit=50` | `[{id, camera_id, profile, generation, rel_path, start_time, end_time, duration_ms, size_bytes, codec, part_count, uploaded}]` |
| `/logs?source=agent\|mediamtx&lines=200` | `{source, lines:[…]}` |
| `/media/{segment_id}/init.mp4` | ftyp+moov bytes |
| `/media/{segment_id}/part/{n}.m4s` | moof+mdat byte slice, tfdt rebased; `Cache-Control: public, max-age=86400, immutable` |
| `/media/{segment_id}/file.mp4` | whole chunk download, named `cam{id}_{profile}_{YYYYmmddTHHMMSSZ}.mp4` |

## 4. MediaMTX (node-local; client-facing ports)
- RTSP `rtsp://<node>:8554/cam-<id>/<profile>`.
- LL-HLS `http://<node>:8888/cam-<id>/<profile>/index.m3u8`.
- WebRTC page `http://<node>:8889/cam-<id>/<profile>`; WHEP `POST …/whep` with `application/sdp`.
- Control API (localhost only): see 04 §3.
