# L3 Edge Storage Backfill Implementation Plan

Last updated: 2026-10-20

Status: initial Central Manager, Media Node and web-client implementation is
complete and validated against a real Profile G camera. Desktop parity remains
deferred.

Implemented on 2026-10-20:

- Profile G capability probing, recording enumeration and replay-URI validation;
- manual and opt-in automatic, bounded gap jobs with node leases;
- camera-to-node replay download, fragmented-MP4 validation and idempotent publish;
- `NVR` versus `CAMERA_SD` recording provenance in the database and timeline;
- playback of imported material through the existing HLS endpoints; and
- a web Backfill tab for probing, mapping, policy and job status.

Known interoperability boundary: the verified camera expresses exact replay
ranges as `start`/`stop` query parameters. Cameras requiring RTSP `Range:
clock=` negotiation need an additional transport adapter. Unsupported camera
audio (for example G.711 in standard MP4) is omitted while video is preserved;
AAC/Opus tracks are copied when the container accepts them.

Initial delivery scope: Central Manager, Media Node and `nvr_client`. Desktop
parity should be added only after the web workflow is accepted on real cameras.

## 1. Objective

When Shah-NVR has a recording gap because a media node, network path or NVR
service was unavailable, recover the missing interval from a camera's SD-card
recording through ONVIF Profile G. The recovered media must then behave like an
ordinary Shah-NVR recording:

- stored on a configured media-node recording volume;
- indexed locally and registered with Central Manager;
- playable through the existing HLS playback and audio paths;
- governed by the existing retention and storage-pressure rules; and
- visibly identified as `Camera SD backfill` in the web timeline.

L3 does not mean retrying `pending_uploads`. The existing uploader already
retries node-to-central recording metadata. L3 obtains media that Shah-NVR
never recorded locally.

## 2. Important constraints

- Camera credentials continue to be held by Central Manager and are sent only
  to the assigned media node for an operation, matching the existing H1-H3
  pattern.
- Central Manager never downloads or proxies video bytes. The assigned media
  node talks directly to the camera on its LAN.
- Imported video and audio are remuxed with codec copy. L3 must not transcode
  video merely to backfill it.
- A camera may advertise Profile G but have no SD card, disabled edge recording,
  an empty recording catalog or a broken replay implementation.
- Camera and NVR clocks may differ. All searches and segment timestamps must be
  normalized to UTC using the camera clock offset and verified against replay
  timestamps.
- Backfill must not starve live recording. Concurrency and bandwidth are
  deliberately limited.
- Automatic backfill is opt-in per camera until its Profile G compatibility is
  successfully tested.

## 3. ONVIF workflow to implement

The node-side Profile G client will use the following workflow:

1. Read `GetServices`/`GetCapabilities` and locate Recording Search and Replay
   service addresses.
2. Call `GetRecordingSummary` to confirm that stored material exists.
3. Call `FindRecordings`, then poll `GetRecordingSearchResults` until the search
   is complete. Always call `EndSearch`, including after cancellation or error.
4. Use `GetRecordingInformation` and `GetMediaAttributes` to enumerate tracks,
   time ranges and source metadata.
5. Match the camera's Shah-NVR stream/profile to an ONVIF recording and track.
   Persist the mapping after confirmation. If the result is ambiguous, require
   the user to select it instead of guessing.
6. Call Replay `GetReplayUri` for the selected recording token.
7. Open the returned RTSP URI using TCP and ONVIF replay semantics. The replay
   session must use the requested UTC interval, the `onvif-replay` feature tag
   and the original recording timestamps.
8. Remux the returned tracks into Shah-NVR-compatible fragmented MP4 chunks,
   validate them, index them and publish their metadata to Central Manager.

Profile G requires search/replay behavior rather than one universal file
download URL. Therefore vendor compatibility has to be measured separately for
search, track mapping and replay.

## 4. Architecture and ownership

### Central Manager

Central Manager is the durable control plane. It will:

- store per-camera capability, mapping and policy;
- calculate eligible recording gaps;
- create idempotent backfill jobs;
- lease jobs to the camera's currently assigned node;
- receive progress and final results;
- expose public APIs to the web client; and
- return segment provenance in recording timelines.

### Media Node

The media node is the data plane. It will:

- probe the camera's Profile G services;
- search camera recordings;
- acquire one leased job at a time;
- download/remux the missing interval directly from the camera;
- write through a temporary file and atomically publish valid chunks;
- use the existing fMP4 indexer and metadata uploader; and
- report progress, failures and discovered coverage to Central Manager.

The node should pull/claim work from Central Manager. This avoids depending on
an inbound node API or its public address and continues to work with LAN-only
nodes.

### Web client

`nvr_client` will provide capability testing, configuration, manual job
creation, job monitoring and timeline provenance. It will never contact the
camera directly.

## 5. Data model

### Camera backfill configuration

Add a one-to-one configuration record, or equivalent camera fields, containing:

- `camera_id`;
- `enabled` (default `false`);
- `mode`: `manual` or `automatic`;
- `recording_token` and optional `track_token`;
- Shah-NVR `profile` being recovered, initially `main`;
- capability state: `unknown`, `supported`, `unsupported`, `degraded`;
- search/replay service addresses;
- camera's earliest/latest reported recording timestamps;
- last successful capability test and scan timestamps;
- last error code/message; and
- optional schedule limits such as maximum lookback and permitted hours.

Do not store replay URIs permanently because cameras can make them temporary.

### Backfill job

Create a durable `backfill_jobs` table with:

- UUID primary key;
- camera, profile and requested `[start_time, end_time)`;
- assigned/leased node and assignment generation;
- state: `QUEUED`, `CLAIMED`, `SEARCHING`, `DOWNLOADING`, `INDEXING`,
  `COMPLETED`, `PARTIAL`, `FAILED`, `CANCELLED`;
- priority and attempt count;
- lease owner and lease expiry;
- discovered source intervals;
- bytes and seconds imported;
- progress timestamp;
- stable error code plus safe error message;
- requester (`manual` or `automatic`); and
- creation/start/finish timestamps.

Enforce an idempotency key over camera/profile/time range so scheduler retries
or double-clicks cannot create duplicate active jobs. Overlapping queued jobs
should be merged or rejected with the existing job identifier.

### Recording provenance

Add to both `RecordingSegment` and `LocalSegment`:

- `origin`: `NVR` or `CAMERA_SD`;
- nullable `backfill_job_id`; and
- optional source recording token hash for diagnostics (never credentials or a
  credential-bearing replay URI).

Expose `origin` and `backfill_job_id` in `SegmentIn`, `SegmentOut` and node debug
schemas. Existing rows migrate to `origin=NVR`.

The current playback builder already skips overlapping media by timeline. Add
an explicit preference rule: original NVR segments win over `CAMERA_SD`
segments when both cover the same time. This keeps playback deterministic and
prevents duplicate media after a late normal segment appears.

## 6. Gap detection policy

A gap is eligible only when all of these are true:

- the camera is enabled, assigned and its selected stream has recording enabled;
- L3 is enabled and its capability test passed;
- the interval is older than a safety delay, proposed default 5 minutes;
- the interval is larger than the existing playback gap tolerance;
- it falls inside retention and maximum-backfill-lookback limits;
- the camera reports stored media overlapping it; and
- no active/completed job already covers it.

Exclude future time, the active MediaMTX chunk and planned interruptions where
possible. Split large gaps into bounded jobs, proposed maximum 15 minutes each,
so work is resumable and progress is visible.

Automatic detection should run in a Central Manager background loop, proposed
every 60 seconds. The first release must cap the number of new jobs per cycle.

Manual backfill accepts a user-selected interval but still intersects it with
actual Shah-NVR gaps and camera-reported coverage. It must never overwrite a
healthy recording simply because the user selected a wider range.

## 7. Node import pipeline

### Compatibility spike before production integration

Build a standalone diagnostic under `media_node/tests/` using configuration
constants at the top, consistent with the H5 verifier. Against at least two
Profile G cameras it must print:

- discovered Recording Search and Replay services;
- recording tokens and time ranges;
- track metadata and proposed Shah-NVR mapping;
- replay URI with credentials redacted;
- RTSP DESCRIBE/SETUP/PLAY result for a short historical interval;
- first/last media timestamps, codecs and downloaded duration; and
- whether a codec-copy fragmented MP4 passes the existing indexer.

This spike decides the replay transport implementation. Prefer the installed
FFmpeg process only if it can correctly send the camera's required ONVIF RTSP
range/feature headers and preserve timestamps. If not, add a focused replay
transport adapter rather than silently downloading the wrong interval.

### Production worker

For each claimed job:

1. Reconfirm assignment generation, credentials and L3 mapping.
2. Search the camera and intersect the requested gap with available ranges.
3. Check target volume capacity before downloading.
4. Write only to a node-owned temporary directory on the target volume.
5. Pull with RTSP/TCP and codec copy, including supported audio and metadata
   tracks. Unsupported metadata may be omitted with a recorded warning.
6. Bound subprocess/runtime, output size and inactivity time.
7. Validate container structure, codecs, duration and timestamps.
8. Split or package output into the normal segment duration where practical.
9. Move each valid file atomically into the normal camera/profile/day tree.
10. Index it with the existing fMP4 indexer and create `LocalSegment` directly
    with `origin=CAMERA_SD`; do not rely on the generic scanner to infer origin.
11. Upload segment metadata through the existing idempotent uploader.
12. Recompute remaining coverage and mark the job `COMPLETED` or `PARTIAL`.

Use deterministic filenames/segment UUIDs derived from camera, profile,
recording token and UTC interval. A retry must recognize already imported
chunks and continue rather than download them again.

Files remain invisible to playback until they pass validation and have a
complete `LocalSegment` row. On failure, remove only the verified temporary
file. Never delete existing recordings during job cleanup.

## 8. APIs

### Public Central Manager APIs

Proposed endpoints:

- `GET /api/v1/cameras/{id}/backfill` — configuration, capability and summary;
- `POST /api/v1/cameras/{id}/backfill/probe` — run a safe capability/search
  test through the assigned node;
- `PATCH /api/v1/cameras/{id}/backfill` — enable/mode/mapping/policy;
- `POST /api/v1/cameras/{id}/backfill/jobs` — manually request an interval;
- `GET /api/v1/cameras/{id}/backfill/jobs` — job history and active progress;
- `GET /api/v1/backfill/jobs/{job_id}` — one job;
- `POST /api/v1/backfill/jobs/{job_id}/cancel` — request cancellation; and
- `POST /api/v1/backfill/jobs/{job_id}/retry` — create a safe retry for the
  remaining uncovered range.

Errors should retain the existing `{code, message}` convention. Suggested
codes include `profile_g_unsupported`, `no_edge_storage`, `no_recording_match`,
`replay_unavailable`, `replay_auth_failed`, `replay_timeout`,
`timestamp_mismatch`, `codec_unsupported`, `storage_full`, and
`assignment_changed`.

### Internal node APIs

Prefer polling/lease endpoints:

- `POST /internal/v1/backfill/claim` with node ID and capacity;
- `POST /internal/v1/backfill/{job_id}/heartbeat` to renew the lease and report
  bounded progress;
- `POST /internal/v1/backfill/{job_id}/complete`; and
- `POST /internal/v1/backfill/{job_id}/fail`.

A crashed worker becomes retryable after lease expiry. Central Manager must
reject stale updates from an old lease owner.

## 9. Web UI

### Camera detail: Edge storage section

Show:

- capability badge and last test time;
- SD recording range reported by the camera;
- selected recording/track mapping;
- `Test camera storage` action;
- Off / Manual / Automatic mode;
- maximum lookback and conservative bandwidth/concurrency help text;
- active job progress and last failure; and
- recent jobs with imported duration and size.

Automatic mode remains unavailable until the probe and a short replay sample
both succeed.

### Recording timeline

- Keep normal NVR ranges green.
- Render `CAMERA_SD` recovered coverage with a distinct pattern/color and
  tooltip: `Filled from camera SD storage`.
- Show eligible unresolved gaps with a `Backfill this gap` action.
- Display queued/running state over the affected range.
- After completion, refresh the timeline and allow immediate playback through
  the existing VOD player.

The segment list should show provenance, job ID and import time for support
diagnostics.

## 10. Resource controls and safety

Initial conservative defaults:

- one active backfill job per node;
- one active job per camera;
- 15-minute maximum interval per job;
- 24-hour default maximum lookback, configurable with a hard upper bound;
- 5-minute recent-gap safety delay;
- exponential retry with a small maximum attempt count; and
- pause claims when no recording volume is accepting writes.

If live recording health deteriorates, the worker should pause or cancel the
download and retain only completed, validated chunks. Later versions can expose
a bandwidth limit, but concurrency control is required in the first release.

Credentials, replay URIs and SOAP bodies must not be logged. Cancellation and
service shutdown must terminate child processes and clean their temporary
files.

## 11. Testing strategy

### Unit tests

- SOAP parsers for Profile G search, media attributes and replay URI.
- UTC conversion and camera clock-offset handling.
- recording/track-to-stream mapping, including ambiguous results.
- gap eligibility, tolerance, merging, splitting and idempotency.
- job state transitions, lease expiry and stale worker updates.
- provenance migrations and API serialization.
- playback preference when normal and backfilled segments overlap.
- safe path construction and deterministic segment IDs.

Use saved, sanitized SOAP/SDP fixtures from multiple vendors. Tests must never
contact a real camera by default.

### Integration tests

- Fake Profile G SOAP service plus a replay RTSP fixture.
- Complete successful job producing playable indexed fMP4.
- Partial camera coverage.
- camera returns no recordings;
- wrong credentials and lockout-safe behavior;
- camera/node disconnect during download;
- malformed or timestamp-shifted replay;
- cancellation, node restart and lease recovery;
- central unavailable while local segments are completed;
- disk full and retention interaction; and
- duplicate/overlapping job requests.

### Real-camera acceptance

For every supported model:

1. Enable its SD-card recording.
2. Stop the media node long enough to create a known NVR gap while the camera
   continues recording.
3. Restart the node and run a manual backfill.
4. Confirm the imported interval aligns with wall-clock time.
5. Play before, across and after both boundaries.
6. Verify video and audio where present.
7. Confirm the timeline marker and provenance.
8. Repeat with automatic mode and a node restart during import.

## 12. Delivery phases

### Phase 0 — protocol experiment

- Standalone verifier and real-camera search/replay/remux proof.
- Record sanitized fixtures.
- Decide FFmpeg versus a focused replay transport adapter.

Exit gate: a historical interval can be fetched by exact UTC time and indexed
without transcoding.

### Phase 1 — node Profile G client

- Service discovery, recording search, track mapping and replay adapter.
- Temporary-file safety, remux, validation and direct local indexing.
- Unit and fixture integration tests.

### Phase 2 — central orchestration

- Database migrations for configuration, jobs and segment provenance.
- Capability/configuration APIs, gap calculator, job leases and internal APIs.
- Idempotency, retries, cancellation and assignment-change handling.

### Phase 3 — manual web workflow

- Camera Edge storage panel.
- Probe, mapping and manual backfill actions.
- Job monitoring and timeline provenance.

Exit gate: manually recover a known real gap and play it in `nvr_client`.

### Phase 4 — automatic backfill

- Opt-in scheduler, safety delay, throttling and resumability.
- Operational metrics and dashboard warnings.
- Multi-camera endurance tests.

### Phase 5 — desktop parity

- Add the accepted L3 configuration, job status and timeline markers to
  `nvr_desktop` as a separate parity task.

## 13. Completion criteria

L3 is complete for the initial server/node/web scope when:

1. Shah-NVR detects an eligible gap without treating an active chunk as a gap.
2. A supported Profile G camera is probed and mapped without guessing.
3. Manual and opt-in automatic jobs survive retries and process restarts.
4. Only the missing interval is imported, without video transcoding.
5. Imported video and supported audio play through the existing playback APIs.
6. Normal recordings win safely over overlapping backfilled media.
7. Retention, volume quotas and disk-pressure deletion handle imported chunks.
8. The web timeline clearly distinguishes camera-SD footage.
9. Unsupported/broken cameras fail with a useful state and do not enter a retry
   loop or risk account lockout.
10. Existing live view, recording, playback, H1-H6 and H5 virtual ONVIF behavior
    remain regression-tested.

## 14. Explicitly deferred

- Desktop implementation during the initial web acceptance cycle.
- ONVIF Recording Control operations that configure the camera's SD recording.
- Event-only backfill based on H4 motion metadata.
- Reverse playback.
- Transcoding unsupported camera codecs.
- Import from proprietary vendor APIs when Profile G replay is absent.
- Backfill between Shah-NVR media nodes; L3 is camera edge-storage recovery.

## 15. Recommended first action

Begin only with Phase 0 against the available Profile G cameras. Do not add the
automatic scheduler or production database tables until exact-range replay and
timestamp preservation have been demonstrated. This isolates the largest
compatibility risk before the rest of the system depends on it.
