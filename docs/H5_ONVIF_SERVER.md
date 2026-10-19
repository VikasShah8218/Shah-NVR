# H5 Implementation Plan: Shah-NVR as an ONVIF Device

Status: implementation started; Device/Media live slice implemented locally  
Scope: `central_manager`, `media_node`, and `nvr_client`  
Excluded: `nvr_desktop`, H4 events, official ONVIF certification, TLS and the
final external identity-provider integration

Current implementation includes Central configuration and camera exposure,
node-local credentials, HTTP/RTSP Digest and WS-UsernameToken authentication,
WS-Discovery, initial Device/Media SOAP operations, an authenticated no-transcode
live RTSP proxy, node status reporting, and the web management tab. Recording
Search and Profile G replay remain pending and H5 is not yet complete.

## 1. Goal

Each Shah-NVR media node will appear on the LAN as an ONVIF NVR. A third-party
VMS should be able to:

1. Discover the node through WS-Discovery.
2. Log in with one temporary node-local username and password.
3. Read device information and enumerate the cameras/streams exposed by that
   node.
4. Open live RTSP streams without receiving the original camera credentials.
5. enumerate and search recordings stored on that node.
6. Request an ONVIF replay URI and play a requested recording range over RTSP.

The first release is an interoperable implementation, not a claim of official
ONVIF Profile G conformance. A product may claim conformance only after the
appropriate ONVIF test tool and membership process are completed.

## 2. Architecture

```text
Third-party VMS
   |
   |-- UDP 3702 WS-Discovery
   |
   |-- SOAP + HTTP Digest / WS-UsernameToken
   |      http://NODE:7100/onvif/device_service
   |      http://NODE:7100/onvif/media_service
   |      http://NODE:7100/onvif/recording_service
   |      http://NODE:7100/onvif/search_service
   |      http://NODE:7100/onvif/replay_service
   |
   `-- authenticated RTSP
          rtsp://NODE:8555/live/cam-17/main
          rtsp://NODE:8555/replay/<recording-token>
                    |
                    | live: packet proxy, no transcoding
                    | replay: range-aware recorded-media reader
                    v
             MediaMTX :8554 + local fMP4 recordings

Central Manager
   |-- desired ONVIF-server configuration
   |-- camera exposure flags
   `-- node status and health

nvr_client
   `-- configuration/status UI only; it never handles ONVIF credentials
```

### Why a separate RTSP gateway is required

The current MediaMTX RTSP/HLS/WebRTC endpoints are used by Shah-NVR clients
without media authentication. Enabling global MediaMTX authentication now would
break existing WebRTC and HLS URLs.

H5 will therefore add an authenticated ONVIF RTSP gateway on a separate port.
The gateway will:

- authenticate third-party VMS clients;
- proxy live RTP packets from the existing MediaMTX path without decoding or
  transcoding;
- implement the ONVIF replay `Range: clock=...` behaviour for recordings;
- enforce which cameras and profiles are exposed;
- hide camera source URLs and camera passwords.

MediaMTX's HTTP playback endpoint is useful for browser/file playback, but it is
not a replacement for Profile G RTSP replay. H5 must not return an HTTP HLS/MP4
URL from `GetReplayUri` and call that ONVIF replay complete.

## 3. Temporary authentication design

### Simple authentication for this stage

Use exactly one local ONVIF service account per media node. It is configured in
the node environment, not PostgreSQL and not the web browser:

```env
ONVIF_SERVER_USERNAME=shahnvr
ONVIF_SERVER_PASSWORD=replace-with-a-long-random-password
ONVIF_AUTH_MODE=local
ONVIF_RTSP_PORT=8555
```

Rules:

- No built-in default password. The ONVIF server cannot be enabled until both
  values are configured.
- The password is never returned by an API, included in an ONVIF URI, logged or
  sent to Central Manager.
- `nvr_client` shows only `Credentials configured: Yes/No` and the authentication
  mode. Password rotation is performed by changing the node environment and
  restarting the node during this temporary stage.
- Discovery and `GetSystemDateAndTime` remain available without authentication
  so clients can discover the node and correct clock skew. All camera, media,
  recording, search and replay operations require authentication.
- Use constant-time comparisons and generic `NotAuthorized` responses. Log the
  source IP and requested action, but never log supplied passwords or digests.

### SOAP authentication

Support both mechanisms because third-party ONVIF clients vary:

1. **HTTP Digest authentication** with `qop=auth`, a short-lived signed nonce and
   the realm `Shah-NVR`.
2. **WS-Security UsernameToken**, accepting PasswordDigest and PasswordText for
   compatibility. PasswordDigest validation uses
   `Base64(SHA1(nonce + created + password))`.

UsernameToken requests must enforce a bounded clock-skew window, reject stale
timestamps and cache nonce/digest identifiers briefly to prevent replay. SOAP
authentication failures return the proper `ter:NotAuthorized` fault; HTTP
Digest negotiation returns a `401` challenge.

### RTSP authentication

The ONVIF RTSP gateway uses the same username/password and requires RTSP Digest
authentication for both `/live/...` and `/replay/...`. `GetStreamUri` and
`GetReplayUri` return URLs without embedded credentials; the VMS supplies the
credentials it was given for the ONVIF device.

### Later external authentication

Create an authentication-provider interface from the beginning:

```text
verify(username, secret/digest context, protocol, action, resource, client_ip)
```

The initial provider reads the node environment. Later, `ONVIF_AUTH_MODE=http`
can delegate the same decision to the external authentication server without
rewriting SOAP services, the RTSP gateway or ONVIF business logic.

Traditional ONVIF/VMS clients generally authenticate with username/password or
Digest, not a browser OAuth flow. The future external server should therefore
validate ONVIF service accounts and return permissions such as `live:read` and
`recording:read`; it should not require the VMS to understand the Shah-NVR web
application's access token.

This H5 work does not add login protection to Central Manager or `nvr_client`.
Those remain on the project's current trusted-network security model until the
separate application-authentication stage.

## 4. Stable ONVIF identity and tokens

The node needs a persistent UUID stored in its local SQLite key/value state. It
must survive restarts and must not change when the node IP changes.

Use deterministic opaque tokens:

- device UUID: persistent UUID per media node;
- media profile: `profile_cam_<camera-id>_<profile>`;
- video source: `source_cam_<camera-id>`;
- recording: `recording_cam_<camera-id>_<profile>`;
- video track: `track_cam_<camera-id>_<profile>_video`;
- search tokens: random, short-lived and process-local;
- replay session tokens: random, short-lived and scoped to one authenticated
  user/client.

Tokens must never contain camera usernames, passwords, source URLs or filesystem
paths.

## 5. Central Manager work

### Database changes

Add a one-to-one ONVIF server configuration for each media node:

- `enabled`;
- `discovery_name`;
- `manufacturer` default `Shah-NVR`;
- `model` default `Shah-NVR Media Node`;
- optional location text;
- timestamps.

Add `expose_via_onvif` to cameras, defaulting to `true`. A camera is exposed by
a node only when it is enabled, assigned to that node and this flag is enabled.
Credentials are deliberately absent from these tables.

Create an Aerich migration and verify upgrade from the current migration head.

### Public API

- `GET /api/v1/nodes/{node_id}/onvif-server`
- `PATCH /api/v1/nodes/{node_id}/onvif-server`
- `PATCH /api/v1/cameras/{camera_id}/onvif-exposure`

The node configuration response includes desired configuration plus reported
runtime state:

- enabled/disabled;
- online/offline/error;
- credentials configured boolean;
- advertised XAddr;
- live/replay RTSP address;
- exposed camera/profile counts;
- last error and last heartbeat.

### Node synchronization

- Include desired ONVIF-server configuration and exposure flags in the node's
  existing heartbeat/assignment flow.
- The node caches the last valid configuration so discovery and live streams can
  continue during a temporary Central Manager outage.
- Do not send source camera credentials to ONVIF clients. Existing assignment
  delivery to the trusted node remains unchanged.

## 6. Media Node work

### Module layout

Add a server-side package separate from the existing ONVIF camera client:

```text
media_node/app/onvif_server/
  auth.py
  discovery.py
  faults.py
  namespaces.py
  registry.py
  soap.py
  device_service.py
  media_service.py
  recording_service.py
  search_service.py
  replay_service.py
  sessions.py
```

Keeping `app/onvif/` as the camera-facing ONVIF client and
`app/onvif_server/` as the NVR-facing ONVIF device prevents the two roles from
being mixed.

### WS-Discovery

- Join multicast group `239.255.255.250:3702` on usable LAN interfaces.
- Respond to ONVIF `Probe` and `Resolve` with the persistent endpoint UUID,
  Device/NVT types, configured scopes and the current public XAddr.
- Send Hello/Bye when the service starts/stops or is enabled/disabled.
- Increment/persist metadata version when the discovery name, location or
  exposed service metadata changes.
- Never advertise loopback, VPN or link-local addresses when a usable LAN address
  exists. Re-advertise after the node's public address changes.

### SOAP foundation

- Serve SOAP 1.2 envelopes on the existing node HTTP port.
- Resolve actions using WS-Addressing `Action`, with SOAPAction compatibility.
- Use explicit namespace handling, schema-shaped responses and ONVIF fault codes.
- Apply request-size limits, XML entity/DTD protection, timeouts and bounded
  session registries.
- Unknown actions return `ter:ActionNotSupported`; invalid tokens return
  `ter:InvalidToken`; malformed values return `ter:InvalidArgVal`.

### Device service

Implement at minimum:

- `GetDeviceInformation`
- `GetServices`
- `GetCapabilities`
- `GetServiceCapabilities`
- `GetSystemDateAndTime`
- `GetScopes`
- `GetHostname`
- `GetNetworkInterfaces`

This service describes Shah-NVR, not the original physical camera. Device write
operations such as reboot, network changes, factory reset and user management
are not exposed in the first H5 release and must return an accurate unsupported
fault.

### Media and Media2 services

Expose one ONVIF media profile for each allowed Shah-NVR camera stream. At
minimum implement the operations commonly required before `GetStreamUri`:

- `GetProfiles` / `GetProfile`
- `GetVideoSources`
- `GetVideoSourceConfigurations`
- `GetVideoEncoderConfigurations`
- `GetVideoEncoderConfigurationOptions` as read-only advertised data
- `GetStreamUri`
- `GetSnapshotUri` only when a safe Shah-NVR snapshot endpoint exists

The URI must point to the authenticated H5 gateway, for example:

```text
rtsp://192.168.1.115:8555/live/cam-17/main
```

Encoder-setting calls remain unsupported in H5. Third-party VMS software must
not be allowed to change a physical camera through the virtual NVR accidentally.

Add a cached stream descriptor containing codec, resolution, frame rate and
audio presence. Populate it from known ONVIF/H2 state and MediaMTX runtime data,
and refresh it when a stream configuration changes. Do not invent values when
they are unknown.

### Local recording registry

Use the node's SQLite `local_segments` table as the authority for recordings
physically available from that node. Add a small persistent export registry for
camera names/profile metadata so historical recordings remain discoverable
after a camera moves to another node.

Only report files that still exist on usable storage. Retention deletion and
volume removal must disappear from ONVIF search results without waiting for
Central Manager.

### Recording and search services

Implement the read-only subset needed for Profile G interoperability:

- recording enumeration/information for each recorded camera profile;
- `GetRecordingSummary`;
- `FindRecordings`;
- `GetRecordingSearchResults` with pagination;
- `KeepAliveSearch`;
- `EndSearch`;
- media attributes needed by tested clients.

Search sessions are bounded, user-scoped, expire after inactivity and are lost
on node restart. Search by recording token and UTC time range first. Event search
is deferred because H4 is intentionally skipped.

Recording/job creation or modification is not supported: Shah-NVR remains the
owner of its recording policy.

### ONVIF RTSP live/replay gateway

Implement a small cross-platform gateway managed as a child process by the media
node, similar to MediaMTX. A Go helper based on a maintained RTSP library is the
preferred implementation because it can be built as one Windows/Linux binary
and keep RTP packets out of Python.

Live mode:

- authenticate the RTSP client;
- authorize the requested exposed profile;
- subscribe to `rtsp://127.0.0.1:8554/cam-<id>/<profile>`;
- relay RTP/RTCP without decoding, encoding or changing timestamps;
- share an upstream reader when safe, while keeping client RTSP sessions
  independent.

Replay mode:

- accept ONVIF RTSP `Range: clock=<UTC-start>-<UTC-end>` and supported Scale;
- resolve matching local fMP4 segments and gaps;
- demux and packetize H.264/H.265 (and later audio) without transcoding;
- preserve wall-clock progression and signal discontinuities correctly;
- support pause, resume, teardown and end-of-range;
- stop all readers/processes when the RTSP client disconnects;
- enforce maximum concurrent replay sessions and per-session duration.

Before the full gateway is built, complete a spike proving `DESCRIBE`, `SETUP`,
`PLAY` with absolute clock range, packet delivery and `TEARDOWN` in ONVIF Device
Manager or the selected third-party VMS. This is the largest H5 risk and should
be proven before building all search UI.

### Node status and lifecycle

- Start/stop discovery and the gateway from desired configuration.
- Report SOAP/discovery/gateway state in `/api/v1/status` and heartbeats.
- Validate port availability and credentials before reporting online.
- Cleanly send Discovery Bye and terminate replay sessions during shutdown.
- Continue serving cached assignments and local recordings if Central Manager is
  temporarily offline.

## 7. Web client work

Add an **ONVIF server** tab to the media-node detail page rather than browser-local
Settings. It configures a specific node.

The page shows:

- enable/disable switch;
- discovery name and optional location;
- SOAP XAddr and ONVIF RTSP port;
- authentication mode and credentials-configured status;
- online/error state and last error;
- exposed cameras and profiles;
- copyable example connection details;
- a warning that password rotation currently happens in the node `.env`;
- camera exposure toggles.

Do not add a password field in this phase. The unauthenticated Central API and
browser must never become a route for reading or replacing the ONVIF secret.

## 8. Delivery phases

### Phase 0: protocol and replay spike

- Capture expected request sequences from ONVIF Device Manager and one target
  third-party VMS.
- Prove SOAP parsing/faults and both authentication modes.
- Prove WS-Discovery on Windows and Ubuntu.
- Prove the separate RTSP gateway can authenticate and proxy one live stream.
- Prove absolute-time RTSP replay for one H.264 recording.

Exit: the VMS discovers Shah-NVR, authenticates, plays one live profile and plays
a requested recorded range. Do not continue to broad implementation if replay
cannot satisfy the client's RTSP behaviour.

### Phase 1: Central configuration

- Add migrations, models, APIs, heartbeat configuration and tests.
- Add camera exposure flag.
- No credentials stored centrally.

### Phase 2: node ONVIF foundation

- Add identity, authentication provider, SOAP framework and WS-Discovery.
- Implement Device service and status reporting.

### Phase 3: live media

- Implement Media/Media2 read operations and stable profile registry.
- Integrate the authenticated gateway with existing MediaMTX paths.
- Validate H.264 and H.265 advertisements without transcoding.

### Phase 4: recording search

- Add the persistent local export registry and read-only recording/search
  services.
- Validate search sessions, pagination, gaps, retention deletion and moved
  cameras.

### Phase 5: replay

- Complete range-aware RTSP replay, concurrency limits and cleanup.
- Test H.264 first, then H.265. Add audio only when H6 defines Shah-NVR audio
  recording behaviour.

### Phase 6: web management UI

- Add the per-node ONVIF server tab, exposure controls, errors and connection
  instructions.

### Phase 7: hardening and acceptance

- Run unit, integration, malformed-XML, authentication replay and load tests.
- Validate on Windows and Ubuntu nodes.
- Test discovery/live/search/replay with ONVIF Device Manager and at least one
  production target VMS.
- Update deployment documentation and firewall rules.

## 9. Testing requirements

### Automated

- Golden XML tests for every supported SOAP request/response and fault.
- WS-Discovery Probe/Resolve, multiple NICs and IP-change tests.
- HTTP Digest and UsernameToken valid/invalid/stale/replayed credential tests.
- Authorization tests proving hidden cameras and unassigned profiles cannot be
  opened by guessing tokens or URLs.
- Search session TTL, ownership, pagination and maximum-session tests.
- Recording deletion/storage-offline races.
- RTSP authentication, live proxy, clock-range replay, pause/resume/teardown,
  client disconnect and maximum-concurrency tests.
- Regression tests proving existing WebRTC, HLS, native RTSP, recording and HLS
  playback remain unchanged.

### Physical acceptance

1. Discover both a Windows and Ubuntu Shah-NVR node from another PC.
2. Confirm unauthenticated media/search requests fail.
3. Add the node once with the temporary username/password.
4. Enumerate every exposed main/sub profile with correct names and codecs.
5. Play simultaneous live streams for at least 30 minutes.
6. Search a known UTC interval and verify gaps and retention boundaries.
7. Replay across two adjacent recording chunks and seek to a second time.
8. Confirm camera credentials, internal MediaMTX paths and filesystem paths never
   appear in responses or logs.
9. Disable exposure and verify both enumeration and direct RTSP access are denied.
10. Restart Central Manager, the media node and the gateway independently and
    verify recovery/cleanup.

## 10. Deployment changes

- Open UDP 3702 on the camera/VMS LAN for WS-Discovery multicast.
- Keep node HTTP port 7100 reachable for ONVIF SOAP.
- Open the new authenticated ONVIF RTSP port 8555.
- Keep MediaMTX control API and internal replay/control endpoints bound to
  loopback.
- Add Windows and Linux gateway binaries through the same platform-selection
  approach used for MediaMTX; do not commit secrets into generated config files.
- Add environment validation and clear startup errors when H5 is enabled without
  credentials or with a port conflict.

## 11. Explicitly deferred

- `nvr_desktop` management UI.
- H4 events and `FindEvents`.
- H6 audio and two-way audio.
- ONVIF user-management operations and multiple roles/users.
- TLS/RTSPS, certificates and password management through the UI.
- Recording job creation/control by third-party VMS software.
- PTZ proxying through the virtual NVR.
- Cross-node aggregated replay through one ONVIF endpoint.
- Official Profile G conformance claim.
- Integration with the final external authentication/authorization server.

## 12. Definition of done

H5 is complete for this scope only when a supported third-party VMS can discover
a node, authenticate once, enumerate permitted streams, view live RTSP, search
local Shah-NVR recordings and replay an absolute time range over RTSP. Existing
Shah-NVR web live/playback flows must continue working without requiring the H5
credentials.

## 13. Recommended implementation order

Start with Phase 0, specifically the replay gateway spike. Device discovery and
SOAP XML are substantial but predictable; ONVIF-compatible RTSP replay is the
architectural risk. Once the target VMS accepts live and replay from the spike,
the remaining services can be implemented against that proven contract.
