# Desktop Feature Parity

Last audited: 2026-10-21
Compared: current `nvr_client` and `nvr_desktop` working trees

## Summary

The desktop now contains every user-facing feature currently delivered in the
web client. There are **zero known web-to-desktop parity gaps**.

| Feature | Web client | Desktop client | Status |
|---|---|---|---|
| H1 ONVIF discovery and device management | Implemented | Implemented | In parity |
| H2 ONVIF video encoder control | Implemented | Implemented | In parity |
| H3 ONVIF PTZ control, initial slice | Implemented | Implemented | In parity |
| H5 Virtual ONVIF NVR administration | Implemented | Implemented | In parity |
| H6 audio detection, live listening and recorded listening | Implemented | Implemented | In parity |
| L3 ONVIF Profile G edge-storage backfill | Implemented | Implemented | In parity |
| Per-node public client endpoints | Implemented | Implemented | In parity |

H4 events, H6 two-way talk, full Profile G recorded RTSP replay, Profile T, and
the lower-priority ONVIF roadmap items are product-roadmap work. They are not
desktop parity gaps because they are not completed web-client features.

## Implemented desktop parity packages

### H3 PTZ

- Typed session, capability, status, preset, and command-result API contracts.
- A single safe PTZ controller with monotonically increasing sequences,
  hold-to-move, release-to-stop, failure blocking, and explicit reload.
- Live-tile and expanded-view entry points.
- Capability-gated pan/tilt, zoom, presets, Go Home, and confirmed Set Home and
  preset deletion.
- Camera credentials remain exclusively server-side.

Physical pan/tilt/zoom acceptance remains an environment acceptance step when a
supported camera is available; it does not require more desktop feature code.

### H5 Virtual ONVIF NVR administration

- Node-detail **Virtual ONVIF** tab for enabled state, discovery identity,
  location, runtime state, SOAP/RTSP addresses, counts, and runtime errors.
- Per-camera exposure switches for cameras assigned to the selected node.
- Only credential readiness is displayed. Node-local ONVIF passwords are never
  requested, cached, or shown by desktop.
- Runtime state is polled only while its node tab is active.

### H6 one-way audio

- Camera stream pages display advertised/observed state, codec, sample rate,
  channels, and bitrate where available.
- Storage estimates include known audio bitrate.
- Native mpv audio is enabled but muted by default.
- Live View allows only one audible camera at a time and mutes on tile removal,
  clear, page close, or application deactivation.
- Playback uses the audio track embedded in the existing HLS recording playlist,
  with mute and locally persisted volume controls.
- There is intentionally no **Record audio** switch: MediaMTX records compatible
  tracks supplied by the selected stream.

### L3 edge-storage backfill

- Camera-detail **Backfill** tab with Profile G probing, recording selection,
  off/manual/automatic policy, local-time manual requests, and job monitoring.
- Job state, progress, imported duration/bytes, attempts, and failures are shown.
- Playback identifies `CAMERA_SD` chunks in both the timeline and chunk table.
- All camera access and credentials remain behind Central Manager and Media Node.

### Per-node public client endpoints

- Node-detail **Connectivity** tab manages optional public API/media mapping.
- Desktop Settings stores **Auto**, **Always LAN**, or **Prefer public** locally;
  one workstation cannot change another user's route.
- Auto probes each private node API independently with a 1.5-second bound and a
  60-second keyed cache, then falls back to a complete enabled public mapping.
- The selected route is applied to live URLs, playback playlists (including
  multi-node ranges), downloads, status, assignments, MediaMTX paths, chunks,
  and logs.
- Private registration endpoints remain the path for heartbeats, assignments,
  and uploads.

## Intentional client differences

- Web Live View uses WebRTC with LL-HLS fallback. Desktop uses native RTSP through
  libmpv with LL-HLS fallback. Native RTSP is the intended desktop transport.
- Desktop exposes hardware-decoder selection because it uses libmpv; the browser
  delegates decoding to the browser and operating system.
- Desktop snapshot and download destinations use native filesystem paths, while
  the web client uses browser downloads.
- Browser playback may need an AAC sidecar; native mpv consumes synchronized audio
  from the normal recording playlist.

## Verification

- Python source compilation passes.
- The complete desktop suite passes: **115 tests**.
- The suite includes a real offscreen QML page smoke test with libmpv plus focused
  route-resolution, audio metadata, and backfill-time conversion coverage.

## Maintenance rule

Whenever a user-facing feature is added to `nvr_client`, update this file in the
same change as one of:

- **In parity:** desktop is implemented and tested in the same delivery.
- **Desktop pending:** list the exact missing API, store, UI, and test work.
- **Intentional difference:** document the equivalent native desktop behavior.

Remove an item from the pending count only after its desktop implementation and
automated tests are complete.
