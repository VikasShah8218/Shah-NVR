# Desktop Feature Parity Backlog

Last audited: 2026-10-20
Compared: current `nvr_client` and `nvr_desktop` working trees

## Summary

There are currently **five feature packages implemented in the web client but
not in the desktop client: H3 ONVIF PTZ controls, H5 Virtual ONVIF NVR controls,
H6 one-way audio, L3 edge-storage backfill, and per-node public client endpoints**.

| Feature | Web client | Desktop client | Status |
|---|---|---|---|
| H1 ONVIF discovery and device management | Implemented | Implemented | In parity |
| H2 ONVIF video encoder control | Implemented | Implemented | In parity |
| H3 ONVIF PTZ control, initial slice | Implemented | Not implemented | **Desktop pending** |
| H5 Virtual ONVIF NVR administration | Implemented | Not implemented | **Desktop pending** |
| H6 audio detection, live listening and recorded listening | Implemented | Not implemented | **Desktop pending** |
| L3 ONVIF Profile G edge-storage backfill | Implemented | Not implemented | **Desktop pending** |
| Per-node public client endpoints | Implemented | Not implemented | **Desktop pending** |

H4 events, H6 two-way talk, full Profile G recorded RTSP replay, Profile T and
the lower-priority ONVIF roadmap items are not counted here. They have not yet
been implemented as completed web-client features, so they are product-roadmap
work rather than desktop parity gaps.

## Pending feature: L3 edge-storage backfill

Central Manager and Media Node now probe a camera's ONVIF Profile G storage,
map a replayable recording, recover bounded NVR gaps, mark imported segments as
`CAMERA_SD`, and serve them through the existing playback pipeline. The web
camera-detail page provides storage testing, manual/automatic policy, manual
range requests, job progress, and timeline provenance.

Desktop parity requires:

- typed backfill configuration, probe result and job models;
- central API methods for probe, configuration, job creation and job listing;
- a camera-detail Backfill tab with Profile G test results and replayable
  recording selection;
- off/manual/automatic policy controls and recorded-profile selection;
- local-time manual range entry with the same 15-minute and five-minute safety
  constraints;
- job state, progress, imported duration/bytes and actionable failure display;
- `CAMERA_SD` provenance styling and explanation in the playback timeline; and
- tests covering unsupported/empty camera storage, configuration, job states,
  time conversion, and unchanged playback behavior.

The desktop must call Central Manager only. It must not receive camera
credentials or open Profile G replay sessions directly.

## Pending feature: H6 one-way audio

The node and central manager detect ONVIF-advertised and MediaMTX-observed audio,
retain codec/sample-rate/channel metadata, index recorded audio tracks and expose
a browser-compatible recorded AAC sidecar. The web client provides muted-by-default
live and recorded listening with volume controls.

Desktop parity requires:

- typed audio fields from the central camera/live/timeline APIs;
- an audio capability/codec display on camera details and ONVIF profile selection;
- audio bitrate in the desktop encoder/storage estimate when the camera advertises it;
- removal of the desktop player's unconditional `audio=no` policy only for streams
  where the operator explicitly unmutes;
- muted-by-default live and playback speaker/volume controls;
- one audible live tile at a time, reliable mute on tile close/camera change/app
  backgrounding, and no automatic unmute after reconnect;
- recorded audio through native mpv using the existing recording playlist, with
  A/V synchronization across seeks and discontinuities; and
- tests for video-only cameras, G.711/AAC recordings, mute lifecycle and existing
  H1/H2/live-view metadata regressions.

Two-way talk remains separate product work and is not part of this parity item.

There must be no desktop **Record audio** switch. MediaMTX records every compatible
audio track supplied by the selected camera stream; desktop only displays capability
and provides muted-by-default listening controls.

## Pending feature: H5 Virtual ONVIF NVR administration

### What already exists outside desktop

Each media node can advertise itself through WS-Discovery as a Virtual ONVIF NVR,
expose assigned camera profiles, authenticate SOAP/RTSP clients, and provide the
implemented Device, Media, Recording and Search services. The web node-detail page
contains an **ONVIF server** tab for the desired configuration and reported runtime
state. Credentials stay exclusively in the media node environment.

### Missing desktop work

#### 1. API contracts and client methods

- Add typed models for `OnvifServerOut` and `OnvifServerUpdate`, including enabled,
  discovery name, location, runtime status, credentials-configured state, SOAP XAddr,
  authenticated RTSP address, exposed camera/profile counts and last error.
- Add central API methods for:
  - `GET /api/v1/nodes/{node_id}/onvif-server`
  - `PATCH /api/v1/nodes/{node_id}/onvif-server`
- Add `expose_via_onvif` to the desktop camera and camera-update models without
  disturbing existing H1/H2 camera metadata.
- Preserve central validation errors and node runtime errors as visible operator
  messages; do not report desired state as proof that the service is online.

#### 2. Store and lifecycle

- Add an isolated node ONVIF-server store, or extend `NodeDetailStore` with a clearly
  separated state object and requests.
- Poll runtime state while the ONVIF-server tab is visible and stop polling when the
  page closes or changes node.
- Support enable/disable and identity updates independently so editing name/location
  does not silently change service state.
- Refresh the assigned-camera exposure list after assignment, camera enablement or
  `expose_via_onvif` changes.
- Never request, cache, display or transmit `ONVIF_SERVER_PASSWORD`; the desktop may
  show only whether node-local credentials are configured.

#### 3. Node-detail UI

- Add an **ONVIF server** tab matching the web feature.
- Show desired enabled state separately from runtime status (`disabled`, `pending`,
  `online` or `error`).
- Provide discovery-name and optional-location fields with the central length limits.
- Display SOAP XAddr, authenticated RTSP address, authentication readiness, exposed
  camera/profile counts and the latest runtime error.
- Warn that `ONVIF_SERVER_USERNAME` and `ONVIF_SERVER_PASSWORD` must be configured in
  the media-node environment before enabling the service.
- List enabled cameras assigned to that node and provide an individual
  `expose_via_onvif` switch; disabled or unassigned cameras must not appear exposed.

#### 4. Tests and completion criteria

- Test API parsing and serialization for all nullable runtime fields.
- Test enable/disable, identity updates, error handling, node changes and polling
  cancellation.
- Test per-camera exposure toggles and refresh after camera assignment changes.
- Add QML smoke coverage for offline, pending, online, missing-credentials and error
  states, plus preservation of existing node tabs.
- Desktop H5 administration is complete when it can safely manage the same desired
  state and exposure list as web without ever handling the node-local password.

## Pending feature: per-node public client endpoints

Central Manager retains each node's private registration address while storing an
optional public API URL, media hostname, RTSP/HLS/WebRTC ports and HTTPS preference.
The web node-detail Connectivity tab controls whether a public mapping is available.
Each browser independently chooses Auto, LAN only or Public only; Auto probes private
Node APIs and falls back to the public mapping.

### What already exists outside desktop

Central stores the private registration endpoints separately from the optional public
mapping. The web client stores **Auto / LAN only / Public only** in browser-local
settings. Auto probes each private Node API for 1.5 seconds, caches the result for 60
seconds and falls back to public. Live and playback requests pass `access=lan|public`
so Central generates matching RTSP/HLS/WebRTC and recording-segment URLs.

### Missing desktop work

#### 1. API models and administration

- Extend the desktop node model with `public_enabled`, `public_api_url`,
  `public_media_host`, `public_rtsp_port`, `public_hls_port`, `public_webrtc_port` and
  `public_media_tls`.
- Extend the node-update request with the same fields and preserve nullable ports.
- Validate that the API URL starts with `http://` or `https://`, the media host contains
  no scheme/path, and every supplied port is between 1 and 65535.
- Add a node-detail **Connectivity** tab that edits the public mapping. Its switch must
  mean **Public mapping available**; it must never act as a global route choice.
- Show the private registration endpoints separately and explain that central-to-node
  heartbeats, assignments and uploads continue over them.
- Include the WebRTC UDP 8189 forwarding and HTTPS/mixed-content warnings even though
  desktop itself normally uses native RTSP.

#### 2. Per-desktop route preference

- Add **Auto (LAN → public)**, **LAN only** and **Public only** to desktop Settings.
- Persist the selection in the desktop's local settings file, not Central Manager, so
  changing one workstation cannot change any other desktop or browser.
- Default new and upgraded installations to Auto.
- Public-only must fall back to LAN for a node without a complete enabled public
  mapping; it must show that fallback rather than construct an invalid URL.

#### 3. Auto route resolver

- Probe `GET {node.api_url}/api/v1/status` with a 1.5-second bound.
- Cache each node's decision for 60 seconds and key/invalidate it by node id, private
  API URL, public-enabled state and public API URL.
- Probe nodes independently: one unreachable LAN node must not force unrelated live
  cameras or node pages onto public routing.
- Cancel or ignore stale probes after changing central URL, preference, node or page.
- Display the route currently selected for this desktop (`LAN` or `Public`) on the node
  detail page.

#### 4. Apply the selected route everywhere

- Add `access=lan|public` to desktop live-URL requests and use the returned RTSP/HLS
  links without reconstructing them locally.
- Pass the selected access to video and audio playback playlist requests.
- For a playback range containing segments from multiple nodes, use LAN only when
  every required node is LAN-reachable; otherwise request a public playlist. Central
  will fall back to LAN for any node without a public mapping.
- Resolve direct node status, camera-assignment, MediaMTX-path, chunk and log calls
  through the selected Node API URL.
- Resolve recording downloads through the same per-node route.
- Keep native RTSP as the normal desktop live transport; WebRTC remains an intentional
  web/desktop difference.

#### 5. Tests and completion criteria

- Unit-test explicit LAN, explicit public, missing-public fallback and independent
  Auto decisions for multiple nodes.
- Test the 1.5-second timeout, 60-second cache, cache invalidation and stale-probe
  cancellation.
- Test live URLs, audio/video playlists spanning one and multiple nodes, downloads and
  every direct node page request in all three modes.
- Add QML tests proving the Connectivity switch is availability—not global usage—and
  Settings changes remain local to one desktop installation.
- Regress node monitoring, playback, downloads, Live View, PTZ and ONVIF-server tabs.
- Desktop parity is complete only when local and internet workstations can run at the
  same time without changing one another's route.

## Pending feature: H3 ONVIF PTZ controls

### What already exists outside desktop

The central manager and media node expose the PTZ session and command APIs. The
web client integrates them in Live View through:

- `nvr_client/src/api/ptz.ts`
- `nvr_client/src/features/live/PtzPanel.tsx`
- `nvr_client/src/features/live/ptzController.ts`
- `nvr_client/src/features/live/LivePage.tsx`
- `nvr_client/tests/ptz.test.ts`

The server-side camera-specific fallback is also already implemented. Desktop
must call the central PTZ APIs; it must not communicate directly with the camera
or duplicate the media-node fallback logic.

### Missing desktop work

#### 1. API contracts and client methods

- Add typed desktop models for the PTZ open response, capabilities, status,
  presets, warnings and command result.
- Add central API methods for:
  - `POST /api/v1/cameras/{camera_id}/streams/{profile}/ptz`
  - `POST /api/v1/cameras/{camera_id}/streams/{profile}/ptz/command`
- Preserve structured server error codes such as stale commands, expired
  sessions, changed assignments and unavailable PTZ services.
- Use bounded request timeouts and do not retry movement commands automatically.

#### 2. PTZ controller and store

- Add a desktop PTZ store/controller registered with QML.
- Open a session for the selected camera and stream profile.
- Maintain a strictly increasing command sequence for each session.
- Support hold-to-move pan left/right, tilt up/down and zoom in/out.
- Repeat only one bounded movement pulse at a time; do not queue parallel moves.
- Send Stop when a held control is released, cancelled or loses focus.
- Send Stop when the PTZ panel/dialog closes, the page is hidden, the camera is
  changed or the application exits.
- Surface movement and Stop failures to the operator. A failed Stop must disable
  further movement until the controls are reloaded.
- Provide the existing web speed range of `0.05` to `0.50`.
- Support manual reload after session expiry, service failure or process restart.

#### 3. Live View UI

- Add a PTZ control toggle to each occupied Live View tile.
- Target the profile currently displayed by that tile (`main` or `sub`).
- Add PTZ controls beneath the expanded main-stream view.
- Show loading state, camera/server warnings, errors and last reported movement
  status without covering essential video controls.
- Enable or disable pan/tilt, zoom, presets and home controls from the advertised
  capabilities instead of assuming every PTZ camera supports every action.
- Keep normal camera names, status badges, menus and video playback unchanged.

#### 4. Presets and home position

- List camera-native presets.
- Recall a selected preset.
- Save the current position as a new named preset.
- Delete a preset only after explicit confirmation.
- Show Go Home only when advertised.
- Show Set Home only when the camera explicitly advertises that it is supported,
  and require confirmation before replacing the camera's home position.

#### 5. Safety requirements

- Match the web controller's release ordering: Stop receives a higher sequence
  even when the preceding movement request is still in flight.
- Never automatically retry authentication failures, movement requests or camera
  writes.
- Prevent simultaneous button presses from creating competing movement loops.
- Treat session reload as mandatory after a node/central restart or a material
  camera assignment/mapping change.
- Display all server warnings, including camera-side timeout limitations.
- Keep credentials server-side; no camera username or password may enter QML.

#### 6. Tests required

- API serialization and structured-error tests.
- Controller tests for press/hold/release, cancellation, focus loss, panel close
  and application shutdown.
- Test that Stop overtakes an in-flight movement command with a higher sequence.
- Test that parallel presses cannot queue movement.
- Test that move failure still attempts Stop and that Stop failure blocks further
  movement until reload.
- Store tests for capabilities, warnings, expiry/reload, presets and home gating.
- QML smoke tests for tile and expanded-view controls without regressions to
  camera labels, metadata or video playback.
- Run the complete desktop test suite, then perform physical acceptance against
  the available PTZ camera for pan, tilt, zoom, Stop, presets and home where
  supported.

### Completion criteria

Desktop H3 parity is complete only when:

1. A user can safely control supported pan, tilt and zoom from both a Live View
   tile and the expanded main-stream view.
2. Releasing or closing a control reliably sends Stop, and failures remain
   visible rather than being reported as success.
3. Camera-native presets and advertised home actions work with confirmations.
4. Existing Live View, camera metadata, H1 and H2 behaviour remain unchanged.
5. Automated tests pass and physical camera acceptance is completed.

## Intentional client differences (not parity gaps)

- Web Live View uses WebRTC with LL-HLS fallback. Desktop uses native RTSP through
  libmpv with LL-HLS fallback. Native RTSP is the intended desktop transport and
  does not require a WebRTC port merely for feature parity.
- Desktop exposes hardware-decoder selection because it uses libmpv; the browser
  delegates decoding choices to the browser and operating system.
- Desktop snapshot and recording-download destinations use native filesystem
  dialogs/paths, while the web client uses browser downloads.

## Maintenance rule

Whenever a user-facing feature is added to `nvr_client`, update this file in the
same change with one of these decisions:

- **In parity:** desktop is implemented and tested in the same delivery.
- **Desktop pending:** list the exact missing API, store, UI and test work here.
- **Intentional difference:** document why the desktop uses an equivalent native
  implementation instead of copying the browser implementation.

Remove an item from the pending count only after its desktop implementation and
tests are complete.
