# Production Readiness Roadmap

Last updated: 2026-10-20

Status: pending

This roadmap defines the recommended work after the current ONVIF, recording,
playback, audio and edge-storage backfill milestones. Reliability and security
take priority over adding another large feature.

## P0: Reliability and soak testing

- Run 9–20 cameras continuously for at least seven days.
- Exercise Central Manager, Media Node, MediaMTX and PostgreSQL restarts.
- Test camera loss, network interruption, node loss, database interruption,
  full storage, quota changes and unexpected host shutdown.
- Confirm recordings resume without duplicates, corrupt segments or silent gaps.
- Add an import grace period so newly recovered historical backfill is not
  immediately selected by full-storage overwrite cleanup.
- Verify database backup/restore and recording-index recovery after an
  unexpected shutdown.
- Add automated regression tests for every defect found during the soak test.

Completion requires a documented seven-day run with no unexplained recording
loss, stuck jobs or unrecoverable service failure.

## P1: Security and access control

- Integrate the planned external authentication service.
- Add administrator, operator and viewer roles with explicit permissions.
- Protect public Central Manager and Media Node APIs.
- Encrypt stored camera credentials with managed key rotation.
- Add HTTPS/TLS for browser and API traffic.
- Protect WebRTC, HLS, snapshots, exports and recording files from unauthorized
  direct access.
- Add secure sessions, login throttling and auditable security events.
- Ensure logs, diagnostics and API errors never expose credentials or tokens.

Completion requires authorization tests proving that every role can access only
its intended cameras and operations.

## P2: Professional deployment and upgrades

- Run Central Manager, Media Node and the web client as managed services, using
  `systemd` on Ubuntu with graceful shutdown and automatic restart.
- Introduce versioned releases and Git tags; do not deploy uncommitted source
  files directly to production.
- Document one upgrade path: database backup, code release, migration, service
  restart, health verification and rollback.
- Add automated PostgreSQL and configuration backups with a tested restore
  procedure.
- Validate required binaries, ports, directories, permissions and environment
  settings before service startup.
- Provide separate development, staging and production configurations.

Completion requires a clean installation and an upgrade/rollback exercise on a
fresh Ubuntu host.

## P3: Monitoring and diagnostics

- Record camera online/offline history and recording-gap incidents.
- Alert on camera loss, recording loss, MediaMTX failure, node failure, low
  storage and repeated upload/backfill failures.
- Expose node CPU, memory, disk, bandwidth, camera count and stream health.
- Add structured logs with correlation identifiers for camera and job actions.
- Provide a downloadable support bundle with sanitized logs, versions and
  non-secret configuration.
- Add Prometheus-compatible metrics when external monitoring is introduced.

Completion requires operators to identify which camera, node and subsystem
caused a failure without accessing the source code or database manually.

## P4: H4 ONVIF events

After the production foundation is stable:

- ingest ONVIF motion, tamper, video-loss and digital-input events;
- store normalized events with camera timestamps and node receipt timestamps;
- show searchable event history and markers on recorded playback;
- support event notifications and later event-triggered export/recording rules;
- handle pull-point renewal, disconnects, duplicates and camera clock drift.

## P5: Finish existing feature families

- Complete physical H3 PTZ acceptance and remaining PTZ controls.
- Complete H5 Profile G recorded RTSP replay and protocol hardening.
- Add desktop parity for H3, H5, H6 one-way audio, L3 backfill and per-node
  public routing, following `DESKTOP_FEATURE_PARITY.md`.
- Implement two-way audio only after authentication and permission controls are
  available.
- Pursue Profile T and formal ONVIF conformance after the implemented services
  are stable and accurately advertised.

## Recommended execution order

1. P0 reliability and soak testing.
2. P1 security and access control.
3. P2 deployment and upgrade engineering.
4. P3 monitoring and diagnostics.
5. P4 H4 events.
6. P5 feature completion and desktop parity.

The immediate next milestone is **P0 reliability and soak testing**. Shah-NVR
should not begin another large feature until its existing recording, playback,
audio and backfill paths have passed sustained failure-oriented testing.
