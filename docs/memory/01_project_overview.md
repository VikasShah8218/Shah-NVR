# 01: Project overview and history

## 1. Goal
The user (Vikas Shah, GitHub `VikasShah8218`, works at ESSI and also builds "HID Trinetra" and ANPR/FRS
projects) is building their **own NVR / VMS** (Network Video Recorder / Video Management System):

- **Main server ("Central Manager")**: manages the APIs, monitoring and everything else; it is the "head" of the system.
- **Secondary servers ("Media Nodes")**: record, store and stream video.
- **HLS** is the preferred delivery format, with wide support for cameras and players (VLC, browsers).
- Clients come later. A **React web client** was built first for testing; the user will move to a **Python desktop app** once the UI is final.
- Target in the original spec (`Initial_archetecture.txt`): **1,000 cameras, 1080p @ 30 fps, H.264/H.265, extensible to 10,000+**, Python backend.

## 2. The original spec (Initial_archetecture.txt), summarized
"Distributed Video Management System (DVMS), Technical Architecture & System Design Specification v1.0":
- Control plane (FastAPI, PostgreSQL HA, event bus) and media plane (media nodes running MediaMTX, with FFmpeg/GStreamer as fallback).
- **Key principle: the control plane never carries video.**
- One upstream connection per camera, shared between the recorder and live viewers. Stream copy, no decoding.
- Main stream plus substream. 60-second segments. A recording catalog in PostgreSQL. Capacity-aware scheduler.
- Lease and generation ownership with fencing. Failover. Hybrid storage. Retention.
- Prometheus/Grafana monitoring. Monorepo layout. A 6-phase roadmap.
- The spec chose RTSP to a Python desktop client. **That was changed to HLS/WebRTC-first** at the user's request.

## 3. Conversation history (chronological)
1. **Architecture review** led to `IMPLEMENTATION_PLAN.md`:
   - Plan: HLS-first, fMP4, byte-range HLS VOD, continuity-first fencing, ONVIF onboarding, an outbox for the event bus, advisory-lock leader election, and an nginx cache for fan-out.
2. **Q&A** (the user asked for short answers):
   - Confirmed the 3 flows: live (camera → MediaMTX → many clients), store (camera → MediaMTX → chunks → PostgreSQL index), and playback (PostgreSQL → storage → HLS).
   - Browsers can't play RTSP, so they get HLS/WebRTC.
   - MediaMTX can't serve recordings over RTSP, so recordings use HLS.
   - Compression options: smart codecs, H.265, motion retention, keyframe thinning, GPU re-encode.
   - Explained why a Tyco export was smaller: it re-encodes.
   - Frigate uses go2rtc plus FFmpeg, not MediaMTX. **MediaMTX was chosen over go2rtc.**
3. **Step-by-step pipelines**:
   - Recording pipeline and playback pipeline were documented step by step (now in 02_architecture.md).
   - Correction made: there is **no separate FFmpeg for recording** (MediaMTX records itself), and **the node does not access the database** (the central manager does).
4. **Build v1** (no auth, Postman and VLC only):
   - Built `central_manager` and `media_node`.
   - Tested end to end locally: camera simulator, SQLite, 2 nodes, failover in about 43 s, crash recovery, retention.
   - Fixed the frame loss at chunk joins (tfdt rebasing), the orphan MediaMTX, and missing tzdata.
5. **Git**: the repo was created at https://github.com/VikasShah8218/Shah-NVR.git, and an initial commit was made on top of the GitHub LICENSE commit.
6. **Real-server test** on `shah-ho-1`:
   - PostgreSQL (`nvr` database) and an AXIS M1125 camera.
   - ONVIF refused the login, so the camera was identified through VAPIX (`/axis-cgi/param.cgi`).
   - Found the **GOP and part alignment bug** (parts of about 30 s) and fixed it with a 1.5× forced cut.
   - Deployed through a git bundle over SSH (paramiko).
7. **The user asked**: how to register a camera, and how the RTSP link was found (both answered briefly).
8. **React UI** (plan approved in plan mode):
   - User choices: Dusk slate theme, Tailwind with shadcn/ui, WebRTC with HLS fallback, and backend additions (CORS, node logs, delete node, a nodes resources page with CPU/GPU/RAM/storage and a **per-node storage quota**).
   - Built and tested with Playwright and the headless Chrome already installed, both locally and against the real server and camera over Tailscale.
   - Deployed the backend changes plus an Aerich migration to the server.
9. **The user rewrote git history** to drop the Co-Authored-By trailers and pushed to GitHub (`afd25cb`).
10. **The user asked for this memory dump** (2026-10-13).

## 4. Components and status (as of 2026-10-13)
| Component | Status |
|---|---|
| central_manager | Working. PostgreSQL with Aerich (2 migrations). CORS, quota, metrics, delete node. |
| media_node | Working. MediaMTX v1.21.2, fMP4 recording, indexer, uploader, retention, quota, logs, GPU metrics. |
| nvr_client | Working. 9 routes and all features. Tested headless against the server. |
| Auth / TLS | Not started (explicitly out of scope for now). |
| ONVIF discovery, transcoding, events/motion, export ranges | Not started (see roadmap). |
| Multi-instance central (leader election) | Not done. Run a single central manager. |

## 5. Glossary
- **Chunk / segment**: one recorded fMP4 file (default 60 s) written by MediaMTX. It is a `LocalSegment` on the node and a `RecordingSegment` in central.
- **Fragment**: one `moof+mdat` pair inside a chunk (MediaMTX `recordPartDuration`, 1 s).
- **Part**: a group of fragments (target about 4 s, forced at 6 s) that the playback API serves as one HLS media segment.
- **Profile**: a camera stream such as `main` or `sub`. The MediaMTX path name is `cam-<camera_id>/<profile>`.
- **Generation**: an ownership counter, bumped every time a camera moves node.
- **Lease**: an ownership expiry (30 s), renewed by every heartbeat.
- **Node states**: READY, ACTIVE, DRAINING, CORDONED, UNREACHABLE, OFFLINE.
- **Stream statuses**: UNKNOWN, UNASSIGNED, ASSIGNED, CONNECTING, IDLE, STREAMING, RECORDING, NOT_RECORDING, DISABLED.
