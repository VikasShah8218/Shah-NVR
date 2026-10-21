# Shah-NVR

### A distributed, ONVIF-native video platform built to scale from one site to thousands of cameras

Shah-NVR is a modern network video recorder and video-management platform for
organizations that need to operate cameras across rooms, buildings, campuses,
branches, and remote sites without sending every video stream through one large
server.

It combines a lightweight central control plane with horizontally scalable media
nodes. Cameras are recorded close to where they are installed, while operators
manage the complete estate through one web or native desktop application.

> **The central idea:** centralize coordination and metadata, distribute the
> bandwidth-heavy video work.

Shah-NVR is under active development. Its distributed recording, playback,
ONVIF, PTZ, audio, storage, failover, and edge-storage recovery foundations are
implemented. Production security hardening, formal scale certification, and
long-duration soak testing remain planned milestones.

---

## Why Shah-NVR

Traditional NVRs usually couple camera ingestion, recording, storage, playback,
and administration to one appliance. That creates a predictable ceiling: when
the appliance reaches its network, disk, CPU, or channel limit, the deployment
must be replaced or split into separate systems.

Shah-NVR uses a different model:

- **One management plane** for cameras, media nodes, assignments, health,
  retention, configuration, and recording metadata.
- **Many media planes** that connect directly to cameras, record locally, and
  serve live or recorded media directly to clients.
- **No mandatory transcoding path.** Compatible camera video is recorded and
  served without re-encoding.
- **No central video bottleneck.** The central server builds control responses
  and playback manifests; it does not proxy normal camera traffic.
- **Incremental growth.** Add storage or media nodes as camera count and
  retention requirements increase.
- **Vendor interoperability.** ONVIF discovery, device operations, video
  configuration, PTZ, audio awareness, virtual-NVR exposure, and Profile G
  recovery are part of the platform design.

This makes Shah-NVR suitable for multi-site surveillance, factories, schools,
offices, retail estates, warehouses, residential campuses, and integrators that
need a flexible alternative to fixed-channel proprietary appliances.

---

## Product capabilities

### Unified camera operations

- ONVIF WS-Discovery and manual camera onboarding.
- Main/substream profile selection with snapshot preview.
- Camera identity, firmware, network, time, NTP, and reachability information.
- H.264/H.265 encoder management for supported cameras: resolution, frame rate,
  bitrate, GOP, quality, rate control, and codec profile.
- Safe review-before-apply workflow, shared-encoder warnings, operation history,
  readback, recovery, restore, and controlled bulk changes.
- ONVIF PTZ with pan, tilt, zoom, speed, presets, and supported home actions.

### Live monitoring

- WebRTC and low-latency HLS for browser clients.
- Native RTSP with LL-HLS fallback in the desktop client.
- Main/substream-aware grids to reduce decode and bandwidth cost.
- Live audio when an audio track is available.
- Snapshot, fullscreen, stream health, codec, and connection information.
- LAN/public route selection per client without changing other users.

### Continuous recording and playback

- MediaMTX-managed RTSP ingestion and fragmented MP4 recording.
- Configurable recording volumes, fill order, quotas, and disk-pressure cleanup.
- Central recording timeline with gaps, coverage, size, and segment provenance.
- HLS VOD playback across chunks and across different media nodes.
- Recorded audio with synchronized native or browser-compatible playback paths.
- Direct MP4 segment downloads.
- Retention by camera plus local emergency overwrite protection.

### Resilience and recovery

- Node heartbeats, ownership leases, health states, and automatic reassignment.
- Media nodes continue recording cached assignments during a temporary central
  outage.
- Durable local SQLite queues preserve recording metadata until Central Manager
  is reachable again.
- Startup scanning recovers completed recording files after interruption.
- ONVIF Profile G edge-storage backfill can recover bounded recording gaps from
  a compatible camera's SD card.
- Backfilled footage enters the normal retention and playback pipeline and is
  visibly identified as camera-SD media.

### External interoperability

- A media node can present itself as a virtual ONVIF network video device.
- WS-Discovery, Device, Media, Recording, and Search service slices are
  implemented.
- External systems can enumerate exposed camera profiles and request protected
  live RTSP streams without learning the original camera credentials.
- HTTP Digest and WS-Security PasswordDigest are supported for the implemented
  virtual ONVIF service.
- Full Profile G recorded RTSP replay and formal ONVIF conformance certification
  remain roadmap work.

### Operator applications

| Application | Technology | Best fit |
|---|---|---|
| **Web client** | React, TypeScript, Vite, TanStack Query, Tailwind CSS | Any modern browser, remote access, administration |
| **Desktop client** | Python, PySide6/QML, libmpv | Windows control rooms, native RTSP, GPU/CPU video rendering |
| **Open APIs** | FastAPI and generated OpenAPI contracts | Integrations, automation, monitoring, future mobile clients |

The web and desktop clients cover the same current operator feature set. Their
media engines intentionally differ: browsers favor WebRTC/HLS, while desktop
uses native RTSP/libmpv for low latency and broad codec support.

---

## Architecture

Shah-NVR is divided into a **control plane**, a **distributed media plane**, and
multiple **operator clients**.

```mermaid
flowchart LR
    subgraph Cameras[Camera networks]
        C1[ONVIF / RTSP cameras]
        C2[PTZ and audio cameras]
        SD[Camera SD storage]
    end

    subgraph Edge[Distributed media plane]
        N1[Media Node A<br/>MediaMTX + local storage]
        N2[Media Node B<br/>MediaMTX + local storage]
        NN[Media Node N<br/>MediaMTX + local storage]
    end

    subgraph VPS[Central control plane / VPS]
        CM[Central Manager API<br/>scheduler + catalog + orchestration]
        PG[(PostgreSQL<br/>configuration + metadata)]
        WEB[Web client distribution]
    end

    subgraph Clients[Operator and external clients]
        B[Web browsers]
        D[Desktop clients]
        V[External VMS / ONVIF client]
    end

    C1 -->|RTSP media| N1
    C2 -->|RTSP media| N2
    SD -->|ONVIF Profile G replay| N2

    N1 <-->|register, heartbeat,<br/>assignments, metadata| CM
    N2 <-->|register, heartbeat,<br/>assignments, metadata| CM
    NN <-->|register, heartbeat,<br/>assignments, metadata| CM
    CM <--> PG
    CM --> WEB

    B -->|management API| CM
    D -->|management API| CM
    CM -->|live URLs + playback manifests| B
    CM -->|live URLs + playback manifests| D
    N1 -->|WebRTC / HLS / RTSP / files| B
    N2 -->|WebRTC / HLS / RTSP / files| D
    V <-->|ONVIF + protected RTSP| N1
```

### Central Manager: the control plane

`central_manager/` is the authoritative coordinator. It is intentionally kept
out of the video data path.

It owns:

- camera, stream, node, volume, and retention configuration;
- PostgreSQL-backed recording and backfill metadata;
- camera-to-node scheduling and assignment generations;
- health evaluation, leases, failover, drain, cordon, and manual moves;
- ONVIF request orchestration from a client to the assigned node;
- live-stream URL generation for LAN or public access;
- cross-node playback timeline queries and HLS VOD manifest generation;
- retention decisions and deletion work;
- encoder-operation history and recovery state;
- Profile G backfill policy and durable jobs; and
- the public API consumed by web and desktop applications.

It stores metadata—not continuous video payloads. This keeps central CPU and
bandwidth growth much slower than camera growth.

### Media Node: the media and device plane

`media_node/` runs close to the cameras and performs the bandwidth-intensive
work:

- registers with Central Manager and sends health/metrics heartbeats;
- receives and caches camera assignments;
- communicates with cameras over ONVIF;
- manages MediaMTX paths through its API;
- pulls RTSP streams and records fragmented MP4 files;
- serves RTSP, WebRTC, LL-HLS, recording parts, and downloads;
- indexes completed recordings without decoding the video;
- queues metadata locally and uploads it idempotently to Central Manager;
- enforces storage-volume, quota, retention, and disk-protection rules;
- performs PTZ and encoder operations on the owning node;
- imports compatible camera-SD footage for backfill; and
- optionally exposes assigned cameras as a virtual ONVIF NVR.

Each media node has its own local SQLite state. It never connects directly to
the central PostgreSQL database.

### MediaMTX: the stream router

MediaMTX is the high-performance media engine inside every node. Shah-NVR uses
it to pull camera RTSP sources, fan streams out to viewers, expose browser/native
protocols, and write recordings.

A camera is not re-opened through a separate FFmpeg process for every viewer.
The node configures a path, MediaMTX owns the upstream session, and multiple
readers consume the same available stream. FFmpeg is reserved for workflows
that actually require it, such as compatible recorded-audio output or bounded
Profile G backfill ingestion.

### PostgreSQL: durable global metadata

PostgreSQL contains camera and node configuration, assignments, recording
segment indexes, retention state, operation journals, and backfill jobs. Large
video files remain on node storage. This avoids turning the database or VPS disk
into a video warehouse.

---

## What the VPS holds

In a recommended deployment, the VPS or central server hosts the product's
coordination layer:

| VPS responsibility | Purpose |
|---|---|
| **Central Manager API** | One management endpoint for every client and node |
| **PostgreSQL** | Durable configuration, assignments, recording catalog, and job state |
| **Scheduler and health loops** | Places cameras, detects node loss, and coordinates failover |
| **Playback manifest service** | Finds recording segments and creates cross-node HLS playlists |
| **Web application** | Serves the browser UI, normally behind a reverse proxy |
| **Operational entry point** | Future TLS, authentication, authorization, auditing, and monitoring boundary |

The VPS does **not** normally ingest, record, transcode, or relay all camera
video. After receiving authorized URLs or a playback manifest, clients fetch
media from the responsible node. This is the key reason the central service can
coordinate a large estate without requiring bandwidth equal to every camera
combined.

For internet deployments, node media endpoints can be published through a VPN,
protected reverse proxy, or configured public mapping. Every web or desktop
client independently chooses Auto, LAN, or Public routing; that preference does
not alter another operator's connection.

---

## How the architecture reaches 1,000+ cameras

Shah-NVR approaches 1,000 cameras as a **cluster-sizing problem**, not as a claim
that one server should process 1,000 streams.

### 1. Scale the media plane horizontally

Every node advertises a camera capacity and storage resources. Central Manager
places cameras only on healthy, schedulable nodes. A deployment can therefore
grow from one node to ten, twenty, or more nodes without splitting the operator
experience.

An illustrative layout for 1,000 cameras is ten media nodes at approximately
100 cameras per node. The exact safe density must be benchmarked for the chosen
camera bitrates, codecs, audio tracks, disks, NICs, live-view load, and hardware.
The default configuration's `CAPACITY_CAMERAS=100` is a scheduling limit, not a
performance guarantee.

### 2. Keep video off the central control plane

At large camera counts, video bandwidth dominates everything else. Shah-NVR
keeps camera ingress, recording writes, live fan-out, and recording delivery on
media nodes. The central server handles small heartbeats, metadata batches, API
requests, and text playlists.

### 3. Reuse one upstream stream

MediaMTX maintains the node's camera path and fans it out to recording and live
readers. A new viewer does not require another full camera ingest pipeline in
Central Manager.

### 4. Avoid mandatory transcoding

Compatible camera streams are recorded and served without re-encoding. This
preserves image quality and prevents the CPU/GPU cost from increasing with every
recorded channel. Operators can use camera-side main/substream configuration to
balance recording quality against live-grid efficiency.

### 5. Store video beside the node that received it

Recording files go directly to configured local or attached volumes. Only their
index and ownership are uploaded centrally. Capacity expands by adding disks,
volumes, or nodes rather than enlarging a single VPS disk.

### 6. Batch and recover metadata asynchronously

Finished segments enter a durable local queue. If Central Manager is temporarily
unavailable, recording continues and metadata is uploaded after connectivity
returns. Deterministic identifiers make registration idempotent.

### 7. Generate cross-node playback without copying video

Central Manager builds a playlist whose entries reference the nodes holding the
selected segments. The media nodes serve byte ranges from the original fMP4
files and normalize fragment timestamps. Playback can therefore cross files and
nodes without first assembling a second copy on the VPS.

### Capacity planning example

Video economics still apply. Before deployment, size network and storage from
the actual measured bitrate:

`daily storage ≈ cameras × average Mbps × 10.8 GB`

| Estate | Average stream bitrate | Aggregate camera ingress | Approx. video storage/day |
|---:|---:|---:|---:|
| 100 cameras | 2 Mbps | 200 Mbps | 2.16 TB |
| 100 cameras | 4 Mbps | 400 Mbps | 4.32 TB |
| 1,000 cameras | 2 Mbps | 2 Gbps | 21.6 TB |
| 1,000 cameras | 4 Mbps | 4 Gbps | 43.2 TB |

These are decimal, video-only planning figures. Audio, container overhead,
variable bitrate, RAID/filesystem overhead, replication, retention, live egress,
and safety headroom must be added. Production certification requires per-node
load tests and a full-cluster soak test with the intended hardware.

---

## Recording lifecycle

```mermaid
sequenceDiagram
    participant C as Camera
    participant M as Media Node / MediaMTX
    participant L as Node SQLite queue
    participant X as Central Manager
    participant P as PostgreSQL

    X->>M: Assignment + generation
    M->>C: Open assigned RTSP stream
    C-->>M: Video/audio packets
    M->>M: Write fragmented MP4 chunk
    M->>M: Index completed fragments and keyframes
    M->>L: Queue deterministic segment metadata
    L->>X: Upload metadata batch
    X->>P: Upsert recording catalog
    X-->>L: Acknowledge accepted segments
```

By default, MediaMTX produces one-minute recording chunks with one-second fMP4
fragments. The node scans only completed media, calculates byte locations, and
serves playback parts without decoding the video.

## Playback lifecycle

```mermaid
sequenceDiagram
    participant U as Web/Desktop client
    participant X as Central Manager
    participant P as PostgreSQL
    participant A as Media Node A
    participant B as Media Node B

    U->>X: Request camera, profile, and UTC range
    X->>P: Query ordered recording segments
    P-->>X: Node ownership + byte-part metadata
    X-->>U: HLS VOD playlist referencing A and B
    U->>A: Fetch init/fragment byte ranges
    U->>B: Fetch later init/fragment byte ranges
    A-->>U: Original media bytes
    B-->>U: Original media bytes
```

The central server coordinates the timeline while media delivery remains
distributed.

## Failover model

- Nodes report health and capacity through heartbeats.
- Central Manager marks a node unreachable after missed heartbeats.
- Ownership leases and a grace interval prevent two nodes from intentionally
  recording the same assignment during normal reassignment.
- The scheduler moves cameras to another eligible node with an incremented
  assignment generation.
- A recovered node reconciles its cache with current ownership and stops paths
  it no longer owns.
- A central outage does not immediately stop node recording; cached assignments
  and local upload queues preserve continuity.
- Cameras with supported SD storage can fill selected historical gaps through
  Profile G backfill.

Current defaults use a 15-second heartbeat timeout, 30-second lease, and
10-second failover grace. They are configurable and should be tuned and tested
for each production network.

---

## ONVIF strategy

The media node—not the public VPS—is the ONVIF client for physical cameras. This
is important because discovery multicast and most camera management traffic are
local-network operations.

| Capability | Current implementation |
|---|---|
| Discovery and onboarding | WS-Discovery, identity, profiles, snapshots, main/sub selection |
| Device management | Information, services, clock, time sync, NTP, reboot |
| Video configuration | Media2 preferred with Media1 fallback; safe encoder workflow |
| PTZ | Sessions, continuous movement, Stop, presets, supported home actions |
| Audio | Advertised/observed capability, codec metadata, recording and listening |
| Profile G client | Recording search, replay URI, bounded SD-card backfill |
| Virtual ONVIF NVR | Discovery, Device/Media/Recording/Search slices, authenticated live RTSP |

Camera credentials are used only by the services that need to reach the camera;
they are not exposed in generated live URLs or passed into UI components.

---

## Repository map

```text
Shah-NVR/
├── central_manager/   FastAPI control plane, PostgreSQL models and migrations
├── media_node/        Edge recording agent, MediaMTX control, ONVIF and storage
├── nvr_client/        React/TypeScript browser application
├── nvr_desktop/       PySide6/QML/libmpv Windows application
├── docs/              Architecture decisions, roadmaps and protocol plans
└── tools/             Development and camera-simulation utilities
```

### Technology stack

| Layer | Technologies |
|---|---|
| Central API | Python, FastAPI, Uvicorn, Pydantic |
| Central persistence | PostgreSQL, Tortoise ORM, Aerich migrations |
| Media node | Python, FastAPI, asyncio, local SQLite |
| Media engine | MediaMTX, RTSP, WebRTC, LL-HLS, fragmented MP4 |
| Camera integration | ONVIF SOAP, WS-Discovery, HTTP Digest, WS-Security |
| Web client | React, TypeScript, Vite, TanStack Query, hls.js |
| Desktop client | PySide6, Qt Quick/QML, libmpv |
| Supporting media work | FFmpeg where remuxing or compatible audio output is required |

---

## Deployment topology

### Development or single-site pilot

All services can run on one Windows or Ubuntu machine, with the desktop client
remaining Windows-focused.

```text
One host
├── Central Manager
├── PostgreSQL
├── Media Node + MediaMTX
└── Web client
```

### Recommended distributed deployment

```text
VPS / central server
├── reverse proxy (recommended for production)
├── web client
├── Central Manager
└── PostgreSQL

Site A
├── Media Node A1 + recording storage
└── Media Node A2 + recording storage

Site B
└── Media Node B1 + recording storage
```

Media nodes require IP reachability to their cameras and to Central Manager.
Operators require access to Central Manager and to the selected media-node
protocol endpoints. A VPN or zero-trust private network is the preferred model
until the planned authentication and authorization layer is integrated.

### Operating-system support

- Central Manager: Windows and Linux.
- Media Node: Windows and Linux when `MEDIAMTX_BIN` points to the matching native
  MediaMTX binary and FFmpeg is available where required.
- Web client: any supported modern browser.
- Desktop client: currently Windows-focused.

---

## Quick start for development

### Prerequisites

- Python 3.12+
- PostgreSQL
- Node.js for the web client
- A platform-matching MediaMTX binary
- FFmpeg on `PATH` for workflows that require it
- libmpv for the Windows desktop client

### 1. Configure Central Manager

```bash
cd central_manager
cp .env.example .env
pip install -r requirements.txt
```

Set the PostgreSQL connection values in `central_manager/.env`, then initialize
a new database once:

```bash
aerich init-db
```

For an existing installation, never recreate the schema. Back up PostgreSQL and
run:

```bash
aerich upgrade
```

Start Central Manager:

```bash
python main.py
```

The API and interactive documentation are available at
`http://localhost:8000/docs` by default.

### 2. Configure a media node

```bash
cd media_node
cp .env.example .env
pip install -r requirements.txt
```

Important settings:

- `NODE_NAME`: stable identity for the node.
- `CENTRAL_URL`: Central Manager address.
- `PUBLIC_HOST`: address reachable by clients on the local network, or `auto`.
- `MEDIAMTX_BIN`: Windows `.exe` or Linux MediaMTX binary.
- `RECORDINGS_DIR`: default recording location.
- `CAPACITY_CAMERAS`: scheduler limit for this node.
- MediaMTX RTSP, HLS, WebRTC, API, and UDP ports.

Start the node:

```bash
python main.py
```

The node starts MediaMTX, creates its local state, registers with Central
Manager, advertises its usable address, and begins heartbeat/reconcile loops.

### 3. Run the web client

```bash
cd nvr_client
npm install
npm run dev
```

### 4. Run the Windows desktop client

Install the desktop dependencies and place `libmpv-2.dll` in
`nvr_desktop/bin/`, then:

```powershell
cd nvr_desktop
py main.py
```

Detailed desktop setup is available in
[nvr_desktop/README.md](nvr_desktop/README.md).

---

## Operational visibility

The clients expose:

- central online state and cluster health;
- node CPU, RAM, GPU where available, disk, volume, and network metrics;
- MediaMTX process/version and active path state;
- camera stream state, bytes received, last status, and last recording;
- assignment ownership, generation, lease, and history;
- pending metadata uploads and locally indexed chunks;
- agent and MediaMTX logs;
- recording coverage and gaps;
- backfill capability, progress, provenance, and failure details; and
- ONVIF service, clock, encoder, PTZ, and audio state.

The production roadmap adds structured incident history, alert delivery,
Prometheus-compatible metrics, sanitized support bundles, and deeper auditing.

---

## Security and production-readiness status

Shah-NVR currently assumes a trusted network. The external authentication
service, role-based authorization, full API/media protection, managed TLS, and
camera-credential encryption are not yet integrated.

Until that work is complete:

- do not expose Central Manager or media-node APIs directly to the public
  internet;
- use a VPN or protected reverse proxy;
- restrict CORS and firewall rules;
- isolate camera networks where possible;
- protect PostgreSQL and recording volumes;
- replace example credentials and secrets; and
- treat the platform as pilot/lab software, not a security-certified appliance.

Before a commercial production release, the project plans to complete:

1. sustained failure-oriented soak testing;
2. authentication, RBAC, encrypted credentials, and TLS;
3. managed Ubuntu services, release packaging, backup, restore, and rollback;
4. alerting, auditability, structured diagnostics, and external metrics;
5. PostgreSQL recording-table partitioning and large-estate query validation;
6. measured per-node and full-cluster performance certification; and
7. formal ONVIF conformance work.

See [Production Readiness Roadmap](docs/PRODUCTION_READINESS_ROADMAP.md) for the
engineering plan and [Desktop Feature Parity](docs/DESKTOP_FEATURE_PARITY.md)
for client coverage.

---

## Commercial vision

Shah-NVR's architecture creates a foundation for more than recording cameras.
The same distributed platform can support:

- centrally managed multi-tenant and multi-site deployments;
- event and motion search;
- health and SLA reporting for integrators;
- secure remote access without replacing on-site recording;
- storage tiers and cloud archive policies;
- AI metadata and analytics beside the media node;
- license models based on cameras, nodes, sites, retention, or analytics; and
- integration into existing VMS environments through ONVIF and APIs.

The product's core advantage is architectural: **the control plane can grow as
software while media capacity grows as infrastructure**. Customers can begin
with one node and expand incrementally, preserving one management experience and
one recording catalog as their estate grows.

---

## Current engineering principles

1. Central Manager coordinates video but does not become its bottleneck.
2. Media nodes own camera-network communication and recording I/O.
3. Camera writes are explicit, reviewed, and never blindly retried.
4. Credentials must never appear in generated media URLs or UI state.
5. Recording metadata operations are durable and idempotent.
6. A temporary control-plane outage must not immediately stop recording.
7. Normal playback should avoid transcoding and duplicate video copies.
8. Capability differences between camera vendors must remain visible, not be
   hidden behind unsafe assumptions.
9. Scaling claims must be validated against measured bitrate, disk, network,
   viewer, and failure workloads.
10. Reliability and security take priority over the next large feature.

---

## License

See [LICENSE](LICENSE).
