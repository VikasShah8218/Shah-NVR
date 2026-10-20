# Desktop Feature Parity Backlog

Last audited: 2026-10-20
Compared: `nvr_client` and `nvr_desktop` at commit `0d15b46`

## Summary

There are currently **three feature packages implemented in the web client but
not in the desktop client: H3 ONVIF PTZ controls, H6 one-way audio, and per-node
public client endpoints**.

| Feature | Web client | Desktop client | Status |
|---|---|---|---|
| H1 ONVIF discovery and device management | Implemented | Implemented | In parity |
| H2 ONVIF video encoder control | Implemented | Implemented | In parity |
| H3 ONVIF PTZ control, initial slice | Implemented | Not implemented | **Desktop pending** |
| H6 audio detection, live listening and recorded listening | Implemented | Not implemented | **Desktop pending** |
| Per-node public client endpoints | Implemented | Not implemented | **Desktop pending** |

H4 events, H5 Shah-NVR as an ONVIF device, H6 two-way talk and the lower
priority ONVIF roadmap items are not counted here. They have not yet been
implemented as web-client features, so they are product-roadmap work rather
than desktop parity gaps.

## Pending feature: H6 one-way audio

The node and central manager detect ONVIF-advertised and MediaMTX-observed audio,
retain codec/sample-rate/channel metadata, index recorded audio tracks and expose
a browser-compatible recorded AAC sidecar. The web client provides muted-by-default
live and recorded listening with volume controls.

Desktop parity requires:

- typed audio fields from the central camera/live/timeline APIs;
- an audio capability/codec display on camera details and ONVIF profile selection;
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

## Pending feature: per-node public client endpoints

Central Manager retains each node's private registration address while storing an
optional public API URL, media hostname, RTSP/HLS/WebRTC ports and HTTPS preference.
The web node-detail Connectivity tab controls whether a public mapping is available.
Each browser independently chooses Auto, LAN only or Public only; Auto probes private
Node APIs and falls back to the public mapping.

Desktop parity requires the same node connectivity form plus a local Auto/LAN/Public
preference. Native RTSP, node API and recording-download calls must use the locally
resolved route, without changing the preference for other users.

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
