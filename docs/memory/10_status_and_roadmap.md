# 10: Status, known limits, roadmap

## 1. Git state (2026-10-13)
| Commit (GitHub `main`) | Content |
|---|---|
| `3115b02` | Initial commit (LICENSE, created by GitHub) |
| `d29131c` | central_manager + media_node backend, docs, simulator, Postman |
| `85838cb` | 1.5× forced part cut (GOP misalignment fix) |
| `2528baa` | Node metrics (CPU/GPU/RAM/net/recordings), storage quota, logs API, CORS, delete node |
| `db76fe3` | nvr_client React UI |
| `afd25cb` | Aerich migrations committed + timeline local-time ticks |
| *(next)* | This memory dump: `CLAUDE.md`, `docs/memory/*`, gitignore for `*.local.md` |

The server repo is at the pre-rewrite hash `188b919` (same tree as `afd25cb`). Sync it with `git fetch && git reset --hard origin/main`.

## 2. What is done and verified
- [x] Recording: real AXIS M1125 at 1080p30 and the simulator. 60 s fMP4 chunks, indexing, PostgreSQL catalog.
- [x] Live: RTSP (VLC), LL-HLS, WebRTC (browser, remotely), substream on demand.
- [x] Playback: HLS VOD across chunks and nodes, exact wall clock, gaps and discontinuities, chunk download.
- [x] Scheduler, leases, failover (about 43 s), self-fencing, crash recovery of truncated chunks.
- [x] Retention, disk-pressure cleanup, per-node storage quota.
- [x] Node metrics including NVIDIA GPU; node logs API; CORS; delete node; capacity editing.
- [x] React UI: Dashboard, Live, Playback, Cameras (+detail), Nodes (+detail), Assignments, Settings, in the Dusk slate theme.
- [x] Deployed to `shah-ho-1` and tested with headless Chrome against it.

## 3. Known limitations / tech debt
- **No authentication or TLS.** Camera passwords are stored in plain text in PostgreSQL and delivered over plain HTTP to nodes.
- **A single central instance only** (no leader election); the scheduler is guarded by an in-process lock.
- `recording_segments` is not partitioned (about 1.44 M rows/day at 1,000 cameras); add daily partitions before scaling.
- Services on the server are started by script and aren't Windows services, so they don't start on boot.
- There's no export for a time range (only per-chunk MP4 download), no compressed export, and no thumbnails or snapshots on the server.
- There's no ONVIF discovery, PTZ, audio transcoding, or MJPEG/H.265→H.264 transcoding.
- There are no events, motion or alerts besides UI-derived alerts; no Prometheus/Grafana yet (MediaMTX metrics are enabled on 127.0.0.1:9998).
- GPU metrics are NVIDIA-only. Network rates are whole-host.
- The Postman collection lacks the newer endpoints (quota, logs, delete node).
- Parts may start mid-GOP: a seek can show up to about 1 s of missing picture.
- Overlapping segments from failover are kept until retention (they aren't marked OVERLAP; the playlist dedupes by time).

## 4. Roadmap (suggested order)
1. **Ops:** install both services as Windows services (NSSM or WinSW) with auto-restart and log rotation. Sync the server repo with GitHub.
2. **Exports:**
   - `POST /api/v1/exports {camera, profile, start, end, mode: original|compressed}`.
   - The node concatenates parts with FFmpeg `-c copy` (original) or re-encodes with `libx265 -crf 28` / `hevc_nvenc` (compressed; the RTX 3050 is available).
   - Track jobs in a table and add download links.
3. **ONVIF onboarding:** a node-side WS-Discovery and `GetProfiles`/`GetStreamUri` job (the user already has `tests/onvif_explorer.py`). Fall back to brand URL templates (Axis, Hikvision, Dahua).
4. **Auth:**
   - Users and roles in central, JWT access with refresh.
   - Media tokens: MediaMTX `authMethod: jwt` with `authJWTJWKS` from central; the node media endpoints validate the token.
   - Encrypt camera passwords (AES-GCM with a master key in env). Restrict CORS.
5. **Scale:**
   - Daily partitions on `recording_segments`; batch ingest.
   - PostgreSQL advisory-lock leader election so central can run as several instances.
   - Redis/outbox events; Prometheus and Grafana.
6. **Video features:** motion or event retention, keyframe thinning of old footage (`-bsf:v noise=drop=not(key)`), thumbnails, and an I-frame playlist for fast scrubbing.
7. **Desktop app: BUILT (2026-10-14), see `11_desktop_nvr_desktop.md`.** Every page is done and verified on the local stack, and 37 tests pass. Remaining: Nuitka packaging and a real-server check with the Axis camera. Original decision (2026-10-13, `docs/DESKTOP_APP_PLAN.md`): Python + PySide6 + QML for the app and UI, libmpv (python-mpv, render API in a QQuickFramebufferObject, OpenGL scene graph) for video; frames never pass through Python. Same design and operations as nvr_client; live over RTSP (Auto RTSP→LL-HLS), playback over the existing HLS VOD with `rebase-start-time=no` for the wall clock. Phase 0 = video spike (16 tiles, hwdec, wall clock). Earlier notes: reuse the same APIs. Live through RTSP/WebRTC (PyAV or GStreamer); playback through the same HLS playlists. The React UI's UX is the reference.
