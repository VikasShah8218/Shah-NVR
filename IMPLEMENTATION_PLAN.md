# Shah-NVR — Backend Implementation Plan

| Item | Value |
|---|---|
| Document | Backend implementation plan (Head Server + Media Nodes) |
| Based on | `Initial_archetecture.txt` (DVMS Technical Architecture v1.0) |
| Version | 1.0 — 2026-10-11 |
| Scope | Backend only. Client applications are explicitly out of scope for this phase. |
| Primary delivery protocol | HLS (LL-HLS for live, HLS VOD for playback) |
| Design target | 1,000 cameras @ 1080p30 H.264/H.265, extensible to 10,000+ |

---

## Table of contents

1. [Review of the initial architecture](#1-review-of-the-initial-architecture)
2. [Key decision: HLS-first delivery and wide compatibility](#2-key-decision-hls-first-delivery-and-wide-compatibility)
3. [System overview](#3-system-overview)
4. [Head Server (Control Plane) architecture](#4-head-server-control-plane-architecture)
5. [Media Node (Recorder–Streamer) architecture](#5-media-node-recorderstreamer-architecture)
6. [Head ↔ Node contracts](#6-head--node-contracts)
7. [Ownership, leases and failover policy](#7-ownership-leases-and-failover-policy)
8. [Security model](#8-security-model)
9. [Observability](#9-observability)
10. [Repository structure](#10-repository-structure)
11. [Development environment and testing strategy](#11-development-environment-and-testing-strategy)
12. [Implementation roadmap](#12-implementation-roadmap)
13. [Risks and mitigations](#13-risks-and-mitigations)
14. [Open questions](#14-open-questions)
15. [Decision log](#15-decision-log)

---

## 1. Review of the initial architecture

### 1.1 What is already right (keep as-is)

| Principle | Why it matters |
|---|---|
| Control plane never carries video | The Head scales on metadata, not bandwidth. This is the single most important decision in the document. |
| No server-side decoding (stream copy) | Lets one node handle ~100+ cameras on modest CPU. |
| One upstream connection per camera profile, fan-out on the node | Cameras typically allow only 2–6 RTSP sessions. |
| PostgreSQL as the source of truth for desired state | Agents reconcile against it; events are only notifications. |
| Segment-based recording + central recording catalog | Playback works even after a camera moves between nodes. |
| Lease + generation number per camera assignment | Correct foundation for safe failover. |
| Modular monolith first, not 13 microservices | Correct for a small team. |
| MediaMTX as the media engine, FFmpeg for edge cases | Mature, supports RTSP/RTMP/SRT/WebRTC/HLS/recording/playback/JWT/metrics. |

### 1.2 What needs to change or be added

| # | Area | Issue in the initial document | Change in this plan |
|---|---|---|---|
| R1 | Client protocol | The document picks **RTSP/RTP to a Python desktop client** as the primary path. You now want **HLS** and wide compatibility. | HLS (LL-HLS) becomes the default live path, HLS VOD the default playback path. WebRTC and RTSP stay available as secondary outputs (same MediaMTX instance, almost no extra cost). See §2. |
| R2 | H.265 in HLS | Not addressed. H.265 over HLS **requires fMP4 segments** (not MPEG-TS), and browser support for HEVC is uneven (Safari: yes; Chrome/Edge: hardware-dependent; Firefox: limited). | Use fMP4 everywhere. Record the mainstream as-is; serve the **H.264 substream** as the "universal" profile; add an **optional transcode worker** (H.265→H.264) per camera when no H.264 profile exists. |
| R3 | Playback format | The document says "return media in a supported streaming format" but does not define how. | Concrete design: MediaMTX records **fragmented MP4**; the node indexes fragment byte offsets; the Head stitches an **HLS VOD playlist** using `EXT-X-MAP` + `EXT-X-BYTERANGE`, spanning nodes and gaps. No remuxing, no duplicate storage. See §5.6. |
| R4 | Fencing policy | "Reject stale generation catalog writes" would **discard real video** recorded during a network partition. For an NVR, a recording gap is worse than a duplicate. | Policy: **continuity first**. Stale-generation segments are accepted and tagged `OVERLAP`, never discarded. See §7. |
| R5 | Camera onboarding | No ONVIF discovery or stream probing — needed for "wide camera support". | Add an onboarding module: WS-Discovery + ONVIF `GetProfiles`/`GetStreamUri`, run **by a node inside the camera network**, plus `ffprobe` codec probing. |
| R6 | Camera credentials | "Encrypted secret storage" mentioned but the delivery path to the node is undefined. | Envelope-encrypted in PostgreSQL; delivered to the node only inside its assignment over mTLS; never returned to users. |
| R7 | Audio | The FFmpeg example drops audio (`-an`). Many cameras send G.711 (PCMA/PCMU), which HLS cannot carry. | Record audio as received; for HLS, either omit audio or transcode G.711→AAC (cheap, audio only) per camera policy. |
| R8 | Event bus | "Event Bus" left abstract. | Transactional **outbox table in PostgreSQL → Redis Streams**. Redis is a notification channel only, never authoritative. |
| R9 | Scheduler leadership | "Single-active leader" left abstract. | PostgreSQL **advisory lock** for leader election — no extra infrastructure. |
| R10 | Live fan-out | Relays are planned as custom gateways. | HLS is plain HTTP, so fan-out can use a **caching reverse proxy** (nginx) in front of nodes before writing any custom gateway code. |
| R11 | Load testing | Recommended but no simulator defined. | A camera simulator (MediaMTX + FFmpeg looping real H.264/H.265 files) is part of Phase 0. |

---

## 2. Key decision: HLS-first delivery and wide compatibility

### 2.1 Output protocols per node

Every media node exposes the same camera paths over several protocols. MediaMTX creates each muxer **on demand** (only when someone watches), so unused protocols cost nothing.

| Protocol | Use | Latency (typical) | Status |
|---|---|---|---|
| **LL-HLS (fMP4)** | Default live view: browsers, mobile, smart TVs, any HLS player | ~1–3 s | **Primary** |
| **HLS VOD (fMP4, byte-range)** | Recorded playback / timeline scrubbing | n/a | **Primary** |
| WebRTC (WHEP) | PTZ control, two-way audio, sub-second needs | < 0.5 s | Secondary |
| RTSP / RTSPS | Desktop clients, 3rd-party VMS, video walls | < 1 s | Secondary |
| MP4 download | Evidence export | n/a | Secondary |

> LL-HLS latency depends on segment/part durations and the camera GOP. A 1-second GOP (keyframe interval = FPS) is strongly recommended on cameras. Measure this in Phase 1.

### 2.2 Codec compatibility matrix

| Source codec | Record | LL-HLS live | Notes |
|---|---|---|---|
| H.264 | Stream copy | Stream copy | Universal. Preferred for the substream. |
| H.265 | Stream copy | Stream copy (fMP4 only) | Plays on Safari/iOS and on Chrome/Edge with hardware HEVC. Offer an H.264 profile as fallback. |
| MJPEG | Transcode to H.264 | Transcode | Older / cheap cameras. Needs a transcode worker. |
| AAC audio | Copy | Copy | |
| G.711 / G.726 audio | Copy | Drop or transcode → AAC | Audio transcode is very cheap. |

**Rule:** the server never decodes video unless a camera *has no HLS-compatible profile*. Transcoding is an explicit, per-camera, capacity-counted feature — never the default.

### 2.3 Camera ingestion compatibility

| Method | Phase |
|---|---|
| RTSP pull (TCP, with UDP fallback) | Phase 1 |
| ONVIF Profile S/T discovery + stream URI resolution | Phase 6 |
| RTMP / SRT push (cameras or encoders that push) | Phase 6 |
| Vendor adapters (e.g. Hikvision ISAPI, Dahua HTTP API) for events/PTZ | Later |

---

## 3. System overview

Naming used in this plan: **Head Server** = "Main server" (control plane). **Media Node** = "Slave server" (recorder–streamer).

```
                         ┌──────────────────────────────────────┐
   Users / Admin  ──────►│            HEAD SERVER               │
   (HTTPS, JWT)          │  FastAPI modular monolith            │
                         │  ├─ Auth / RBAC / Audit              │
                         │  ├─ Sites / Cameras / Credentials    │
                         │  ├─ Node Registry / Health           │
                         │  ├─ Scheduler + Failover (leader)    │
                         │  ├─ Stream Discovery (live URLs)     │
                         │  ├─ Recording Catalog / Playback     │
                         │  └─ Events (WebSocket)               │
                         │  PostgreSQL (truth) · Redis (events) │
                         └───────────────┬──────────────────────┘
                     control only (mTLS) │  register · heartbeat · assignments
                                         │  segment index · status
          ┌──────────────────────────────┼──────────────────────────────┐
          ▼                              ▼                              ▼
 ┌──────────────────┐          ┌──────────────────┐          ┌──────────────────┐
 │  MEDIA NODE A    │          │  MEDIA NODE B    │          │  MEDIA NODE C    │
 │  Python Agent    │          │  Python Agent    │          │  Python Agent    │
 │  MediaMTX        │          │  MediaMTX        │          │  MediaMTX        │
 │  nginx (files)   │          │  nginx (files)   │          │  nginx (files)   │
 │  Local disks     │          │  Local disks     │          │  Local disks     │
 └────────▲─────────┘          └────────▲─────────┘          └────────▲─────────┘
          │ RTSP pull                   │                             │
     Cameras (site A)              Cameras (site B)              Cameras (site C)

 Video path:  Camera ──► Node ──► (LL-HLS / HLS VOD / WebRTC / RTSP) ──► Viewer
              The Head only returns URLs + short-lived tokens. Video never passes through it.
```

---

## 4. Head Server (Control Plane) architecture

### 4.1 Technology stack

| Concern | Choice |
|---|---|
| Language / runtime | Python 3.12, `uv` for dependency management |
| API framework | FastAPI + Uvicorn (Gunicorn worker manager in production) |
| Validation / settings | Pydantic v2, `pydantic-settings` |
| Database | PostgreSQL 16 (native declarative partitioning for segments) |
| ORM / migrations | SQLAlchemy 2.0 (async) + asyncpg, Alembic |
| Events / cache | Redis 7 (Streams for events, pub/sub for WebSocket fan-out, rate limiting) |
| Auth | Argon2 password hashing (`argon2-cffi`), JWT (EdDSA or RS256) via `PyJWT`, JWKS endpoint |
| Secrets | `cryptography` (AES-GCM envelope encryption), master key from env/KMS/Vault |
| Background work | Separate worker process (same codebase) running async loops; no Celery needed initially |
| Logging / metrics / tracing | `structlog` (JSON), `prometheus-client`, OpenTelemetry |
| Quality | `ruff`, `mypy`, `pytest`, `pytest-asyncio`, `testcontainers` |

### 4.2 Process layout

The Head is **one codebase, two process types**:

| Process | Replicas | Responsibilities |
|---|---|---|
| `head-api` | N (stateless, behind load balancer) | Public API, internal node API, WebSocket events, JWKS |
| `head-worker` | N, **one active leader** via `pg_try_advisory_lock` | Scheduler, failover coordinator, lease expiry, retention planner, outbox relay, catalog maintenance (partitions) |

Leader election: each worker tries a session-level advisory lock; the holder runs leader-only loops; the others stay hot standby and retry every few seconds. If the leader dies, its DB session closes and the lock is released automatically.

### 4.3 Internal modules

```
head/app/
├── core/            config, logging, db session, security primitives, errors
├── auth/            login, refresh, password policy, JWT issuing, JWKS
├── users/           users, roles, permissions, camera/site grants
├── sites/           sites, network zones, node↔site reachability
├── cameras/         camera registry, stream profiles, credentials (encrypted)
├── onboarding/      ONVIF discovery jobs, stream probing results
├── nodes/           registration, heartbeats, capabilities, state machine
├── scheduler/       placement algorithm, rebalancing, drain handling
├── assignments/     desired state, generations, leases, history
├── streaming/       live discovery, media token issuing (MediaMTX JWT)
├── recordings/      segment ingest, gaps, timeline, catalog queries
├── playback/        HLS VOD playlist stitching, export jobs
├── retention/       policies, holds, deletion planning
├── events/          outbox, Redis Streams publisher, WebSocket gateway
├── audit/           audit log writer and query
└── health/          cluster health aggregation
```

Each module owns its tables, schemas (`schemas.py`), service layer (`service.py`), and router (`router.py`). Modules talk through service functions, not each other's tables — so any of them can be split into its own service later.

### 4.4 Data model

Core tables (all IDs are UUIDs, all timestamps `TIMESTAMPTZ` in UTC):

| Table | Key columns | Notes |
|---|---|---|
| `sites` | id, name, timezone | Physical / network locations |
| `media_nodes` | id, name, site_id, state, api_url, media_base_url, capacity_cameras, capacity_ingress_mbps, last_heartbeat_at, version | State machine from the original doc |
| `node_site_reachability` | node_id, site_id, priority | Which nodes can reach which camera networks |
| `cameras` | id, site_id, name, vendor, model, host, onvif_port, enabled, recording_enabled, retention_policy_id, state | `state` = UNASSIGNED / CONNECTING / STREAMING / RECORDING / STALLED / … |
| `camera_credentials` | camera_id, username, secret_ciphertext, key_version | Never exposed via public API |
| `camera_streams` | id, camera_id, profile (`main`/`sub`/…), source_url_template, codec, width, height, fps, bitrate_kbps, audio_codec, record, transcode_profile | Populated by probing |
| `camera_assignments` | camera_id (PK), node_id, generation, lease_expires_at, desired_state, updated_at | One active owner per camera |
| `assignment_history` | camera_id, node_id, generation, started_at, ended_at, reason | Audit of ownership |
| `recording_segments` | id, camera_id, profile, node_id, generation, start_time, end_time, duration_ms, size_bytes, codec, storage_uri, status, has_audio, checksum | **Partitioned by `start_time` (daily)**; index `(camera_id, profile, start_time)` |
| `recording_gaps` | camera_id, profile, start_time, end_time, reason | Explicitly recorded missing intervals |
| `retention_policies` | id, name, max_days, min_days, high_watermark_pct | |
| `retention_holds` | camera_id, start_time, end_time, reason, created_by | Evidence holds block deletion |
| `users`, `roles`, `role_permissions`, `user_roles`, `role_scopes` | | RBAC with site/camera scoping |
| `refresh_tokens` | id, user_id, family_id, expires_at, revoked_at | Rotation with reuse detection |
| `node_enrollment_tokens` | id, token_hash, expires_at, used_at | One-time node bootstrap |
| `onboarding_jobs` | id, node_id, type, input, result, state | ONVIF discovery / probe jobs executed by nodes |
| `outbox_events` | id, type, payload, created_at, published_at | Transactional outbox |
| `audit_events` | id, actor, action, target, ip, at, details | Append-only |

Segment ingest uses an **idempotent upsert** keyed on a deterministic segment ID (UUIDv5 of `node_id + relative file path`), so repeated notifications never duplicate rows.

Volume check: 1,000 cameras × 60-s segments ≈ 1.44 M rows/day ≈ 43 M rows/30 days — fine with daily partitions, batch inserts, and dropping whole partitions on retention.

### 4.5 Public API (v1)

All under `/api/v1`, JSON, bearer JWT, OpenAPI generated by FastAPI.

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/login` · `/auth/refresh` · `/auth/logout` | Session management |
| GET | `/auth/me` | Current user + permissions |
| CRUD | `/users`, `/roles` | Administration |
| CRUD | `/sites` | Sites |
| CRUD | `/cameras` | Camera registry (credentials are write-only) |
| POST | `/cameras/{id}/probe` | Probe streams/codecs via an eligible node |
| POST | `/sites/{id}/discover` | ONVIF discovery job on a node in that site |
| GET | `/cameras/{id}/live?profile=main\|sub&protocol=hls\|webrtc\|rtsp` | Returns stream URL(s) + short-lived media token |
| GET | `/cameras/{id}/timeline?start&end` | Segments + gaps (for a scrubber) |
| POST | `/playback/sessions` | Creates a playback session → returns HLS VOD playlist URL |
| GET | `/playback/sessions/{id}/index.m3u8` | Stitched VOD playlist (see §5.6) |
| POST | `/exports` · GET `/exports/{id}` | MP4 export jobs |
| GET | `/nodes` · POST `/nodes/{id}/drain` · `/nodes/{id}/cordon` · `/nodes/{id}/uncordon` | Node administration |
| PUT | `/cameras/{id}/assignment` | Manual pin / override |
| GET | `/cluster/health` | Aggregated health |
| WS | `/events` | Live events (owner changed, camera offline, storage alerts) |
| CRUD | `/retention-policies`, `/retention-holds` | Storage lifecycle |
| GET | `/audit` | Audit log query |
| GET | `/.well-known/jwks.json` | Public keys (nodes / MediaMTX validate media tokens with it) |

Example live response:

```json
{
  "camera_id": "9b0c…",
  "profile": "sub",
  "node_id": "node-a",
  "generation": 27,
  "codec": "h264",
  "urls": {
    "hls":    "https://node-a.nvr.local:8888/cam-9b0c/sub/index.m3u8",
    "webrtc": "https://node-a.nvr.local:8889/cam-9b0c/sub/whep",
    "rtsp":   "rtsps://node-a.nvr.local:8322/cam-9b0c/sub"
  },
  "token": "<JWT, 5-minute TTL, read-only, this path only>",
  "expires_at": "2026-10-11T10:05:00Z"
}
```

### 4.6 Scheduler

Runs on the leader worker as a **reconcile loop** (every ~5 s, plus wake-up on events).

1. **Collect** cameras whose desired state is `RECORDING` and have no valid owner, plus cameras on nodes being drained.
2. **Hard filters** — node must be: `READY`/`ACTIVE`, not cordoned/draining/fenced; able to reach the camera's site; below camera, ingress, and disk-write limits; have free disk above the retention requirement; support the camera's transcode profile if one is needed.
3. **Score** remaining nodes: `w1·free_camera_slots + w2·free_ingress + w3·free_disk + w4·locality_priority − w5·recent_failures`.
4. **Persist** the assignment in one transaction (`generation = generation + 1`, new lease) and write an outbox event.
5. **Rebalance** (optional, rate-limited): move at most K cameras per cycle, only when imbalance exceeds a threshold — never during an active incident.

Capacity numbers per node come from benchmarking (Phase 7), not guesses. Start with a configured `capacity_cameras` limit.

### 4.7 Background loops (leader-only unless noted)

| Loop | Interval | Job |
|---|---|---|
| Scheduler | 5 s | Placement + rebalancing |
| Node liveness | 5 s | READY/ACTIVE → UNREACHABLE after missed heartbeats |
| Failover | 5 s | Reassign cameras whose lease expired on unreachable nodes (§7) |
| Outbox relay (all workers, `SKIP LOCKED`) | 1 s | Publish outbox rows to Redis Streams |
| Partition manager | hourly | Create future daily partitions of `recording_segments` |
| Retention planner | 10 min | Compute deletion plans per node (respecting holds) |
| Gap detector | 1 min | Insert `recording_gaps` where expected segments are missing |

---

## 5. Media Node (Recorder–Streamer) architecture

### 5.1 Components on each node

```
MEDIA NODE (Linux host)
├── media-agent      Python 3.12 asyncio service — the brain of the node
├── mediamtx         Media engine: RTSP ingest, recording (fMP4), LL-HLS / WebRTC / RTSP out,
│                    playback server, JWT auth, Prometheus metrics
├── nginx            Serves recorded files with HTTP byte ranges (HLS VOD), auth via agent
├── transcoder(s)    Optional FFmpeg workers (H.265→H.264, MJPEG→H.264, G.711→AAC)
└── node-exporter    Host metrics (CPU, RAM, disks, NIC)
```

### 5.2 Media Agent modules

```
media-agent/app/
├── config/          node identity, paths, head URL, certificates
├── enrollment/      first-boot enrollment (one-time token → mTLS client cert)
├── head_client/     typed HTTP client for the Head internal API (retries, backoff)
├── heartbeat/       periodic heartbeat with metrics + lease renewal
├── reconciler/      desired assignments (from Head) vs actual MediaMTX paths
├── mediamtx/        MediaMTX Control API client (paths add/patch/delete/list)
├── camera_health/   per-camera stream health: bitrate, fps, stalls, reconnects
├── recording/       segment-complete handler, fMP4 indexer, local journal
├── uploader/        durable batch upload of segment metadata to the Head
├── playback/        local HLS VOD playlist fragments from the fMP4 index
├── storage/         disk monitor, retention executor, watermark protection
├── recovery/        startup scan: files vs journal vs Head catalog
├── transcode/       supervises FFmpeg worker processes when required
├── onboarding/      ONVIF WS-Discovery, GetProfiles/GetStreamUri, ffprobe jobs
├── local_state/     SQLite: assignments cache, segment journal, upload queue
└── api/             local HTTP API: /health, /metrics, /auth (for nginx), /playback
```

### 5.3 Assignment reconcile loop

The agent is **level-triggered**, not event-triggered: it always converges actual state to desired state.

```
every 5 s, or when Head pushes "assignments changed":
  desired = GET /internal/v1/nodes/{id}/assignments  (ETag; fall back to SQLite cache if Head is down)
  actual  = MediaMTX GET /v3/config/paths/list
  for camera in desired − actual: add path (source=rtsp://…, record=yes)        → report CONNECTING
  for camera in actual − desired: remove path (stop ingest; files stay on disk)
  for camera in both with changed config: patch path
  report per-camera status in batch
```

MediaMTX path configuration per camera profile (set via its Control API):

```yaml
# path name: cam-<camera_id>/<profile>
source: rtsp://user:pass@10.20.1.15:554/Streaming/Channels/101
rtspTransport: tcp
sourceOnDemand: no            # always pulled, because we always record
record: yes
recordFormat: fmp4
recordPartDuration: 1s
recordSegmentDuration: 60s
recordPath: /data/recordings/%path/%Y-%m-%d/%H-%M-%S-%f
recordDeleteAfter: 0s         # retention is owned by the agent, not MediaMTX
runOnRecordSegmentComplete: /usr/local/bin/nvr-hook segment-complete
```

Global MediaMTX settings: `authMethod: jwt` with `authJWTJWKS` pointing to the Head's JWKS endpoint, Control API bound to localhost only, metrics enabled, `hlsVariant: lowLatency`, `hlsAlwaysRemux: no` (HLS muxer only exists while someone watches).

### 5.4 Recording pipeline

```
MediaMTX writes fMP4 segment (60 s, 1 s fragments)
        │
        ▼  runOnRecordSegmentComplete hook  ──►  agent (localhost)
        │      + periodic directory scan as a safety net
        ▼
Indexer: walk MP4 boxes (no decoding)
   - init section length (ftyp+moov)
   - each moof+mdat: byte offset, size, decode time (tfdt), keyframe flag
   - group fragments into ~4–6 s HLS segments starting on keyframes
   - write sidecar <file>.idx (compact JSON / msgpack)
        │
        ▼
Local journal (SQLite): state = AVAILABLE_LOCAL, upload pending
        │
        ▼
Uploader: batches of up to 500 segments every 2–5 s → POST /internal/v1/recordings/segments
        │
        ▼
Head upsert (idempotent) → catalog row AVAILABLE → outbox event RECORDING_SEGMENT_FINALIZED
```

Disk layout:

```
/data/recordings/
  cam-<camera_id>/
    main/2026-10-11/10-00-00-000000.mp4
    main/2026-10-11/10-00-00-000000.mp4.idx
    sub/2026-10-11/…
/data/agent/state.db          (SQLite: journal, upload queue, assignment cache)
```

Use dedicated data disks (XFS or ext4, `noatime`), separate from the OS disk.

### 5.5 Live streaming (LL-HLS)

- The Head returns `https://<node>:8888/cam-<id>/<profile>/index.m3u8` and a short-lived JWT.
- MediaMTX validates the JWT against the Head's JWKS (claim limits the token to `read` on that one path).
- The HLS muxer starts on first request and stops when idle; the upstream camera connection is shared with the recorder.
- **Fan-out:** for many viewers of the same camera, put an nginx caching proxy (on the node or on a relay host) in front of the HLS port. Segments and parts are immutable and cache well. A custom media gateway is only needed later for isolated networks.

> **Phase 1 spike:** confirm how the media token travels through the player for every request (query parameter vs `Authorization` header via hls.js `xhrSetup` vs cookie). Tokens in URLs must be short-lived and must never be logged.

### 5.6 Recorded playback (HLS VOD) — no remux, no copy

Because recordings are fragmented MP4, an HLS VOD playlist can point **directly into the recorded files** using byte ranges.

1. Client calls `POST /api/v1/playback/sessions {camera, profile, start, end}`.
2. Head queries `recording_segments` for the overlapping range (query from the original doc) and groups contiguous runs by node.
3. For each run, Head calls the owning node: `GET /playback/v1/fragments?segment_ids=…` — the node returns playlist lines built from its `.idx` sidecars.
4. Head stitches one playlist, inserting `#EXT-X-DISCONTINUITY` at file/node boundaries and `#EXT-X-GAP` (or a discontinuity) where `recording_gaps` exist.
5. Segment URLs point to nginx on each node, which serves byte ranges and validates the session token via `auth_request` to the agent.

Example fragment:

```
#EXTM3U
#EXT-X-VERSION:7
#EXT-X-TARGETDURATION:6
#EXT-X-PLAYLIST-TYPE:VOD
#EXT-X-INDEPENDENT-SEGMENTS
#EXT-X-MAP:URI="https://node-a:8443/rec/cam-9b0c/main/2026-10-11/10-00-00-000000.mp4",BYTERANGE="1184@0"
#EXT-X-PROGRAM-DATE-TIME:2026-10-11T10:00:00.000Z
#EXTINF:5.000,
#EXT-X-BYTERANGE:2541033@1184
https://node-a:8443/rec/cam-9b0c/main/2026-10-11/10-00-00-000000.mp4
#EXTINF:5.000,
#EXT-X-BYTERANGE:2498120@2542217
https://node-a:8443/rec/cam-9b0c/main/2026-10-11/10-00-00-000000.mp4
…
#EXT-X-DISCONTINUITY
#EXT-X-MAP:URI="https://node-b:8443/rec/…",BYTERANGE="1190@0"
…
#EXT-X-ENDLIST
```

Benefits: a single playlist spans multiple nodes and camera moves; seeking is exact to a keyframe; `EXT-X-PROGRAM-DATE-TIME` gives wall-clock alignment; zero extra CPU or storage.

**Export:** MediaMTX's built-in playback server (`/get?path=…&start=…&duration=…&format=mp4`) produces a downloadable MP4 for a time range, behind an export token.

### 5.7 Storage management and retention

| Mechanism | Rule |
|---|---|
| Age-based retention | Delete segments older than the camera's policy `max_days`, unless held. |
| Watermark protection | Above `high_watermark` (e.g. 90 %), delete oldest non-held segments until below `low_watermark` (e.g. 85 %); alert, because policy is not being met. |
| Holds | Segments overlapping a `retention_hold` are never deleted. |
| Ordering | Mark `DELETING` in the Head → delete file + `.idx` → mark `DELETED`. Head drops whole daily partitions once all their rows are deleted. |
| Capacity forecast | Node reports bytes/day per camera; the Head alerts when projected retention < policy. |

Optional (Phase 5+): a replication worker uploads finalized segments to S3-compatible storage (e.g. MinIO); the catalog stores both locations; playback prefers the local copy.

### 5.8 Crash recovery

On agent startup, before reporting READY:

1. Load the SQLite journal and cached assignments.
2. Scan recording directories for files not in the journal (e.g. power loss after write, before hook).
3. Index each file; a truncated final fragment is cut off at the last complete `moof+mdat`, and the real `end_time` is used.
4. Mark unrecoverable files `CORRUPT`; record a gap.
5. Upload pending metadata; ask the Head for its view of this node's segments and reconcile differences.
6. Re-apply assignments to MediaMTX (it may have restarted too).

### 5.9 Transcoding (optional, per camera)

Only used when a camera has no HLS-compatible profile (MJPEG, H.265-only with an H.264 requirement, G.711-only audio needed in HLS).

- The agent runs an FFmpeg worker that reads the local MediaMTX path (`rtsp://127.0.0.1:8554/cam-x/main`) and publishes `cam-x/h264` back to MediaMTX — so the camera still has a single upstream connection.
- Hardware acceleration (NVENC / Quick Sync / VAAPI) is detected at enrollment and reported as a node capability.
- Each transcode consumes scheduler capacity (weighted cost), so the scheduler places transcode-heavy cameras on capable nodes.

### 5.10 Node state machine

As defined in the original document: `REGISTERING → READY → ACTIVE ⇄ DEGRADED → DRAINING → OFFLINE`, plus `UNREACHABLE` (Head's view) and `FENCED`. The agent reports `DEGRADED` when a disk is above the watermark, the write rate falls behind, or MediaMTX restarts repeatedly.

---

## 6. Head ↔ Node contracts

All internal endpoints are under `/internal/v1`, require **mTLS** (node client certificate issued at enrollment), and are never exposed publicly.

| Method | Path | Direction | Purpose |
|---|---|---|---|
| POST | `/nodes/enroll` | Node → Head | One-time token + CSR → signed client certificate, node ID |
| POST | `/nodes/{id}/register` | Node → Head | Startup: version, capabilities (HW accel, disks, NICs), reachable subnets |
| POST | `/nodes/{id}/heartbeat` | Node → Head | Every 5 s: resource metrics, camera counts; **response renews leases** and returns `assignments_version` |
| GET | `/nodes/{id}/assignments` | Node → Head | Desired assignments (ETag / `If-None-Match`, supports long-poll) incl. decrypted camera source URLs |
| POST | `/cameras/status` | Node → Head | Batched per-camera state changes and stream stats |
| POST | `/recordings/segments` | Node → Head | Batched, idempotent segment registration (includes `generation`) |
| POST | `/recordings/gaps` | Node → Head | Gaps the node detected (stall, reconnect) |
| GET | `/nodes/{id}/jobs` · POST `/jobs/{id}/result` | Node ↔ Head | Onboarding/probe jobs, deletion plans |
| GET | `/playback/v1/fragments` | Head → Node | VOD playlist lines from `.idx` sidecars |

All shared request/response models live in `shared/contracts` (Pydantic) and are imported by both services, so contract drift breaks the build, not production.

Heartbeat example:

```json
{
  "node_id": "node-a",
  "state": "ACTIVE",
  "agent_version": "0.4.0",
  "mediamtx_version": "x.y.z",
  "cameras": {"assigned": 86, "streaming": 85, "recording": 84},
  "cpu_pct": 22.5, "mem_pct": 34.1,
  "ingress_mbps": 341.0, "egress_mbps": 96.0,
  "disk": [{"mount": "/data", "free_bytes": 14800000000000, "write_mbps": 43.0, "used_pct": 71.2}],
  "upload_backlog": 12
}
```

---

## 7. Ownership, leases and failover policy

Guiding rule for an NVR: **a gap in recording is worse than a short duplicate recording.**

| Parameter | Starting value |
|---|---|
| Heartbeat interval | 5 s |
| Lease TTL (renewed by each heartbeat) | 30 s |
| Node marked UNREACHABLE | 15 s without heartbeat |
| Reassignment allowed | After lease expiry + 10 s grace |

Flow:

1. Node X stops heartbeating → Head marks it `UNREACHABLE` at 15 s.
2. At lease expiry + grace (~40 s), the leader reassigns each camera to Node Y with `generation + 1`, records `assignment_history`, emits `CAMERA_OWNER_CHANGED`.
3. Node Y pulls the camera and starts recording.
4. **If Node X was only partitioned** (still alive, still reaching cameras): it keeps recording from its local cached assignments — continuity is preserved.
5. When Node X reconnects, its heartbeat response shows higher generations for those cameras → it removes those paths from MediaMTX (self-fences) within one reconcile cycle.
6. Segments that Node X recorded under the old generation are **accepted** and stored with status `OVERLAP` (kept, searchable, retained under policy, preferred only where Node Y has a gap). Nothing recorded is thrown away.
7. A node with **expired leases that cannot reach the Head** keeps recording (continue-on-partition). It is not allowed to *add* cameras it was not already assigned.

Strict single-owner mode (no duplicate pulls at all) can be added later as a per-site option for cameras with only one RTSP session; it trades continuity for strictness.

Drain (maintenance): `POST /nodes/{id}/drain` → scheduler moves cameras one by one (make-before-break: Node Y confirms `RECORDING` before Node X releases) → node becomes `OFFLINE`-ready.

---

## 8. Security model

| Area | Implementation |
|---|---|
| User authentication | Username/password (Argon2id), access JWT 15 min, rotating refresh tokens with reuse detection; OIDC/LDAP later |
| Authorization | RBAC (`viewer`, `operator`, `admin`, …) scoped to sites/cameras; permissions: `live`, `playback`, `export`, `ptz`, `admin` |
| Media tokens | JWT signed by the Head, ≤ 5 min TTL, scoped to `read` on one MediaMTX path / one playback session; validated by MediaMTX (JWKS) and the agent (nginx `auth_request`) |
| Node identity | One-time enrollment token → mTLS client certificate from an internal CA; revocable |
| Camera credentials | AES-GCM envelope encryption in PostgreSQL; plaintext only in Head memory and in the node's assignment payload; never in logs or public APIs |
| Transport | TLS on all public endpoints (HLS, WebRTC, API); RTSPS where clients support it |
| Network | Camera VLAN reachable only from media nodes; MediaMTX Control API on localhost only; internal API not routable from user networks |
| Audit | Login, live view start, playback, export, config changes, assignment overrides |
| Hygiene | Rate limiting on auth; tokens stripped from access logs; dependency scanning in CI |

---

## 9. Observability

| Signal | Source | Tool |
|---|---|---|
| Host metrics | node-exporter | Prometheus + Grafana |
| Media metrics (paths, bytes, readers, HLS muxers) | MediaMTX `/metrics` | Prometheus |
| Agent metrics (segments finalized, upload backlog, reconnects, index time, disk watermark) | agent `/metrics` | Prometheus |
| Head metrics (request latency, scheduler cycles, assignments, catalog lag) | `prometheus-client` | Prometheus |
| Logs | structlog JSON | Loki (or OpenSearch) |
| Traces | OpenTelemetry | Tempo / Jaeger (optional) |
| Alerts | Alertmanager | Camera not recording > 2 min, node unreachable, disk > 90 %, upload backlog growing, retention forecast short |

The key distinction from the original document stays: **"streaming" ≠ "recording healthy"**. A camera is only `RECORDING` when segments for it are being finalized on schedule.

---

## 10. Repository structure

Monorepo, independently deployable services:

```
Shah-NVR/
├── services/
│   ├── head/                       # Head Server (FastAPI)
│   │   ├── app/                    # modules from §4.3
│   │   ├── migrations/             # Alembic
│   │   ├── tests/
│   │   ├── pyproject.toml
│   │   └── Dockerfile
│   └── media-agent/                # Media Node agent
│       ├── app/                    # modules from §5.2
│       ├── hook/                   # nvr-hook CLI called by MediaMTX
│       ├── tests/
│       ├── pyproject.toml
│       └── Dockerfile
├── shared/
│   └── nvr_shared/
│       ├── contracts/              # Pydantic models for Head↔Node API
│       ├── events/                 # event type definitions
│       ├── mp4/                    # fMP4 box walker + fragment indexer
│       └── security/               # JWT helpers, token claims
├── infra/
│   ├── compose/                    # docker-compose for dev + multi-node test
│   ├── mediamtx/                   # base mediamtx.yml
│   ├── nginx/                      # node file server + HLS cache configs
│   ├── monitoring/                 # Prometheus, Grafana dashboards, alert rules
│   └── deploy/                     # Ansible / systemd units (later)
├── tools/
│   ├── camera-sim/                 # RTSP camera simulator (MediaMTX + FFmpeg)
│   └── loadtest/                   # HLS viewer load generator, failover chaos scripts
├── docs/
│   ├── adr/                        # Architecture Decision Records
│   └── api/
├── Initial_archetecture.txt
└── IMPLEMENTATION_PLAN.md
```

---

## 11. Development environment and testing strategy

### 11.1 Local stack (Docker Compose)

| Container | Purpose |
|---|---|
| `postgres`, `redis` | Head dependencies |
| `head-api`, `head-worker` | Head Server |
| `node-a`, `node-b` (agent + mediamtx + nginx each) | Two media nodes for failover testing |
| `camera-sim` | MediaMTX publishing N looping RTSP cameras from real H.264 / H.265 sample files via `ffmpeg -re -stream_loop -1 -c copy` |
| `prometheus`, `grafana` | Observability |

Development works on Windows via Docker Desktop (WSL2). **Production media nodes should run Linux** (disk I/O, filesystem behavior, hardware transcoding).

### 11.2 Test layers

| Layer | What |
|---|---|
| Unit | Scheduler scoring, lease logic, fMP4 indexer, playlist builder, token claims |
| Integration | Head + real PostgreSQL (testcontainers); agent + real MediaMTX + simulator |
| Contract | Shared Pydantic models; schema snapshot tests |
| End-to-end | Compose stack: add camera → assigned → recording → live HLS plays → VOD playlist plays across a node change |
| Chaos | Kill node, kill MediaMTX, partition network, fill disk, power-cut simulation (`kill -9` mid-write) |
| Load | 100 → 250 → 500 → 1,000 simulated cameras; HLS viewer load generator |
| Real hardware | Matrix of real cameras from several vendors (e.g. Hikvision, Dahua, Axis, Uniview, Reolink) — codec, GOP, RTSP quirks, ONVIF |

Validate HLS output with Apple's `mediastreamvalidator` and with hls.js and Safari.

---

## 12. Implementation roadmap

Each phase ends with a demo-able result and explicit acceptance criteria. Duration estimates should be made after Phase 1 spikes.

### Phase 0 — Foundations
- Monorepo, `uv` workspaces, ruff/mypy/pytest, CI pipeline.
- Docker Compose with PostgreSQL, Redis, MediaMTX, camera simulator.
- Shared contracts package skeleton; ADR template; first ADRs (HLS-first, fMP4, continuity-first fencing).

**Acceptance:** `docker compose up` brings up the stack; simulator streams play with `ffplay`; CI runs green.

### Phase 1 — Single node: record + live HLS (technical spikes included)
- Static MediaMTX config recording simulated cameras as 60-s fMP4.
- fMP4 indexer + `.idx` sidecar; local SQLite journal.
- LL-HLS live view from MediaMTX, H.264 and H.265.
- **Spikes:** LL-HLS latency vs GOP; H.265 HLS playback in Safari/Chrome/Edge; media-token transport through hls.js and native Safari; hand-built VOD byte-range playlist plays correctly.

**Acceptance:** 24-hour continuous recording of 20 simulated cameras with no gaps; live HLS ≤ 3 s latency at 1-s GOP; a hand-built VOD playlist plays and seeks.

### Phase 2 — Head core + agent control loop
- Head: auth, users/RBAC, sites, cameras, encrypted credentials, node enrollment/registration/heartbeat, manual assignments, JWKS, live discovery API.
- Agent: enrollment, heartbeat, reconcile loop driving MediaMTX Control API, camera status reporting.
- MediaMTX JWT auth against Head JWKS.

**Acceptance:** add a camera through the API → assign it → node starts recording → `GET /cameras/{id}/live` returns a URL that plays only with a valid token.

### Phase 3 — Recording catalog + HLS VOD playback
- Segment batch ingest (idempotent), partitioned `recording_segments`, gap detection.
- Timeline API; playback sessions; node fragment endpoint; Head playlist stitching; nginx byte-range serving with `auth_request`.
- MP4 export via MediaMTX playback server.

**Acceptance:** play back any 30-min window with exact seeking; gaps show correctly; catalog stays consistent after agent restarts.

### Phase 4 — Multi-node scheduling and failover
- Capacity-aware scheduler with site reachability; leader election via advisory lock.
- Leases, generations, failover, `OVERLAP` handling, self-fencing on reconnect.
- Drain/cordon with make-before-break.
- WebSocket events (`CAMERA_OWNER_CHANGED`, etc.) via outbox → Redis Streams.

**Acceptance:** kill a node → its cameras record on another node within ~60 s; partition test produces no lost video and clean self-fencing; one VOD playlist plays across the node change.

### Phase 5 — Storage lifecycle and recovery
- Retention policies, holds, watermark protection, deletion plans, partition dropping.
- Crash recovery scan; corrupt-file handling.
- Optional: S3/MinIO replication worker.

**Acceptance:** disk-full simulation never stops recording of healthy cameras and never corrupts the catalog; `kill -9` during writes loses at most the last ~1 s fragment.

### Phase 6 — Wide camera compatibility
- ONVIF discovery and profile/stream URI resolution executed by nodes.
- `ffprobe`-based stream probing stored in `camera_streams`.
- Transcode worker profiles (H.265→H.264, MJPEG→H.264, G.711→AAC) with hardware acceleration detection.
- RTMP/SRT push ingest.

**Acceptance:** cameras from at least 4 vendors onboard via discovery and play in HLS on Chrome, Safari, and Firefox (using transcode where needed).

### Phase 7 — Scale, observability, hardening
- Grafana dashboards + alert rules; structured logs; tracing.
- Load tests to 1,000 simulated cameras across nodes; set real per-node capacity limits.
- Head HA (2+ API instances, PostgreSQL primary/standby with Patroni, backups + PITR).
- HLS caching proxy for viewer fan-out; security review; runbooks.

**Acceptance:** sustained 1,000-camera run (72 h) with recording completeness ≥ 99.9 %; documented recovery times for node, disk, DB, and network failures.

---

## 13. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| H.265 not playable in some browsers | Live/playback fails for some users | H.264 substream as universal profile; optional transcode; codec info in the live API so clients choose |
| Long camera GOPs (e.g. 4–10 s, "smart codecs") | High LL-HLS latency; coarse seeking | Onboarding checks GOP and warns; recommend 1-s GOP; disable vendor "smart" codecs (H.264+/H.265+) where they break players |
| Camera clock drift / bad timestamps | Wrong timeline | Use node wall-clock (NTP) for segment times; keep media timestamps separately |
| MediaMTX behavior/version changes | Breakage on upgrade | Pin the version; integration tests against the pinned version; upgrade deliberately |
| Recording hook missed | Segments not catalogued | Periodic directory scan + startup recovery reconcile |
| Node disk failure | Loss of history on that node | RAID/ZFS on nodes; optional S3 replication for critical cameras |
| Token leakage in HLS URLs | Unauthorized viewing | ≤ 5 min TTL, path-scoped, stripped from logs |
| Catalog growth | Slow queries | Daily partitions, batched inserts, partition dropping on retention |
| Python agent performance | Slow indexing at scale | Indexer reads only box headers (no media decode); measured in Phase 1; can be moved to a native helper if needed |

---

## 14. Open questions

These do not block Phases 0–2 but shape later phases:

1. **Future clients:** web browser, mobile, desktop — which first? (Affects how much WebRTC/RTSP matter.)
2. **Deployment:** single site, or multiple remote sites over WAN? (Affects reachability, relays, replication.)
3. **Retention target:** how many days, and is central/off-node replication required for evidence?
4. **Audio:** must audio be recorded and played back?
5. **Camera inventory:** which brands/models are in scope? Any MJPEG or H.265-only cameras?
6. **Hardware:** node specs (NIC speed, disk count/RAID, GPU availability)?
7. **Identity:** stand-alone users, or integration with LDAP/Active Directory/OIDC?
8. **Events/analytics:** motion events, ONVIF events, or AI analytics later? (Would add an event-ingest pipeline.)

---

## 15. Decision log

| # | Decision | Status |
|---|---|---|
| D1 | Head = FastAPI modular monolith (API + leader worker) on PostgreSQL | Accepted |
| D2 | Media engine = MediaMTX, Python agent drives it via Control API | Accepted |
| D3 | Live delivery = LL-HLS (fMP4) primary; WebRTC/RTSP secondary | Accepted |
| D4 | Recording format = fragmented MP4, 60-s segments, 1-s fragments | Accepted (validate in Phase 1) |
| D5 | Playback = HLS VOD with byte ranges into recorded files, stitched by the Head | Accepted (validate in Phase 1 spike) |
| D6 | Failover = leases + generations, continuity-first, stale segments kept as `OVERLAP` | Accepted |
| D7 | Events = PostgreSQL outbox → Redis Streams; PostgreSQL remains authoritative | Accepted |
| D8 | Leader election = PostgreSQL advisory lock | Accepted |
| D9 | Media auth = Head-signed short-lived JWT validated by MediaMTX (JWKS) and nginx/agent | Accepted |
| D10 | Transcoding = opt-in per camera, capacity-counted, never default | Accepted |
| D11 | Clients = out of scope for this phase; backend APIs are client-agnostic | Accepted |
