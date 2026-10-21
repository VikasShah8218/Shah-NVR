# H6 Audio Integration Plan

Status: **One-way audio implemented for backend/web testing**
Date: 2026-10-20  
Initial scope: `central_manager`, `media_node`, and `nvr_client`  
Deferred: `nvr_desktop` and two-way talk/backchannel

## 1. Objective

Make Shah-NVR able to:

1. detect whether each camera stream actually provides audio;
2. identify the audio codec and useful properties;
3. automatically retain audio in recordings when the camera supplies it;
4. listen to audio in live view, muted by default;
5. listen to synchronized audio during recorded playback; and
6. continue working normally with video-only cameras.

This is the first H6 slice. Microphone capture, push-to-talk, ONVIF/RTSP
backchannel and camera speakers are a separate H6 slice after one-way audio is
accepted.

## 2. Current behaviour and gaps

The repository already has part of the media pipeline needed for audio:

- ONVIF probing reports only `has_audio`; it does not retain codec, sample rate,
  channels, bitrate or the audio encoder token.
- MediaMTX pulls every track in the selected RTSP profile. When a camera sends
  audio, MediaMTX already exposes and records it. Real node logs have shown G.711
  alongside H.264/H.265.
- MediaMTX runtime path data contains the observed track codec and properties,
  but Shah-NVR does not persist or expose them as structured audio state.
- The fMP4 indexer recognizes AAC, Opus, G.711 A-law, G.711 mu-law and LPCM, but
  it stores an aggregate codec string and drops most structured audio metadata.
- WebRTC negotiation already requests an audio receiver. The web player then
  deliberately forces the video element to remain muted.
- Recorded playback also forces mute and assumes the browser can decode every
  track in the fMP4/HLS output. G.711 is not reliably playable through browser
  HLS/MSE.
- MediaMTX already records the camera's supported audio track with video. H6
  keeps this native behaviour and does not add a separate recording policy.

## 3. Scope and product rules

### Included

- Audio capability detection during ONVIF probe and during actual streaming.
- Structured audio state per camera stream.
- Audio codec, sample rate, channel count and bitrate where available.
- Live mute/unmute and volume control in the web client.
- Recorded mute/unmute and volume control in the web client.
- Browser-compatible recorded playback for the codecs found on the real camera
  fleet, including G.711.
- Migrations, APIs, tests, metrics and operator-visible failure states.

### Deferred

- Desktop client integration.
- Two-way audio and push-to-talk.
- Changing a camera's audio encoder configuration through ONVIF.
- A Shah-NVR **Record audio off** switch. Audio can instead be disabled in the
  camera configuration when the camera supports it.
- Mixing audio from multiple live tiles.
- Audio analytics, transcription and sound-event detection.

## 4. Source-of-truth model

Audio support must not be decided from a single ONVIF boolean. Cameras often
advertise profiles incorrectly or expose a silent/unreachable audio track.

Shah-NVR will keep three observations:

1. **Advertised** — ONVIF says the selected profile contains an audio encoder.
2. **Observed live** — MediaMTX has received an audio track from that RTSP path.
   This is authoritative for live listening.
3. **Recorded** — the indexed recording segment contains an audio track. This is
   authoritative for playback.

The API/UI state will be one of:

- `unknown`: not probed and not observed;
- `none`: no audio was advertised or observed;
- `available`: a supported audio track is currently observed;
- `advertised_not_observed`: ONVIF advertises audio but the RTSP path has not
  produced it;
- `unsupported`: audio exists but Shah-NVR cannot currently play its codec in
  the selected client/transport; or
- `offline`: the last known metadata is retained, but the path is unavailable.

Runtime observation must override stale ONVIF metadata without destroying the
advertised values needed for diagnostics.

## 5. Data and API changes

### Central manager

Add explicit per-stream audio fields to API responses:

```json
{
  "audio_state": "available",
  "audio_advertised": true,
  "audio_observed": true,
  "audio_codec": "g711u",
  "audio_codec_raw": "G711",
  "audio_sample_rate": 8000,
  "audio_channels": 1,
  "audio_bitrate_kbps": 64,
  "audio_last_observed_at": "..."
}
```

The stored model will include the last-known observation.
The normalized API codec values will initially be `aac`, `opus`, `g711a`,
`g711u`, `g722`, `lpcm`, `unknown` and `none`. The raw vendor/runtime name is
kept for debugging.

Required API work:

- include audio state in camera, stream, live and recording-segment responses;
- accept structured observed-track updates from the owning node;
- keep older nodes/segments compatible while rolling out the migration.

## 6. Media-node implementation

### 6.1 ONVIF advertised capability

Extend Media1 and Media2 profile parsing to capture:

- audio encoder configuration token;
- encoding/codec;
- bitrate;
- sample rate;
- channel count; and
- profile association.

Use the configuration embedded in `GetProfiles` when complete, then query the
audio encoder configuration APIs only when required. A camera fault or partial
response must degrade to `unknown`, not fail the whole video probe.

### 6.2 Runtime observation

Extend the existing MediaMTX path-status polling to normalize `tracks2` audio
tracks. Report changes to Central only when the state or properties change, and
rate-limit repeated offline/unsupported reports.

The runtime detector must distinguish G.711 A-law from mu-law using MediaMTX's
codec properties and must not infer audio availability merely from the ONVIF
profile.

### 6.3 Recording behaviour

No new recording worker is required. MediaMTX continues recording every
supported track supplied by the selected camera RTSP profile. If a camera must
not record audio, the operator disables audio in that camera/profile itself.

### 6.4 Recording index and upload

Extend fMP4 indexing so every track retains:

- handler type (`video`/`audio`);
- normalized and raw codec;
- timescale/sample rate;
- channel count where present;
- decoder configuration signature; and
- first decode time used for A/V timestamp rebasing.

Upload structured audio metadata with each segment. Legacy records without the
new fields remain playable and are reported as `unknown` until lazily reindexed
or newly recorded.

## 7. Live audio in `nvr_client`

WebRTC remains the primary live transport. The existing WHEP session already
asks for audio; the player work is to control it safely:

- add a mute/unmute button and volume control to occupied tiles and expanded
  view;
- start every stream muted to satisfy browser autoplay rules;
- unmute only from an explicit user action;
- permit only one audible live player at a time; unmuting one mutes the previous
  player;
- remember volume locally, but do not automatically restore an unmuted state;
- hide/disable controls for `none`, show a useful pending state for `unknown` or
  `advertised_not_observed`, and show the codec for diagnostics;
- stop audio immediately when a tile closes, changes camera, loses assignment or
  the page is hidden; and
- preserve mute state across a transport reconnect without unexpectedly
  enabling sound.

For LL-HLS fallback, direct audio is used only when the browser supports the
recorded codec. G.711 live listening will use WebRTC. If WebRTC is unavailable,
the UI must say that audio is unavailable on the selected fallback instead of
silently pretending that the camera has no audio.

## 8. Recorded audio playback

Recorded playback must use the segment's actual indexed tracks, not the
camera's current capability. The player will start muted and expose the same
volume semantics as live view.

Video continues through the current zero-copy byte-range HLS pipeline. A
separate audio-only HLS playlist selects the matching recording slices. The
node converts only their first audio track to browser-compatible AAC on demand;
video is never decoded, copied or rewritten. A small process semaphore and a
hard timeout prevent playback requests from exhausting the node, while HTTP
cache headers allow the browser to reuse converted slices.

Seeking across segments with different audio layouts/codecs must either select
the compatibility path or deliberately start a new playback discontinuity. No
player may silently drift audio away from video.

## 9. Web UI changes

### Camera creation and editing

- Show `Audio: codec / sample rate / channels` beside each probed ONVIF profile.
- Surface “advertised but not received” and unsupported-codec warnings.

### Camera detail

- Show advertised and observed state, selected codec/properties and last
  observation time.
- Add audio bitrate to storage estimates when known.

### Live and playback

- Muted-by-default speaker button with accessible labels and keyboard support.
- Volume slider in expanded view and playback controls.
- A clear error for unsupported transport/codec, separate from video failure.
- Never expose camera credentials to the browser.

## 10. Testing strategy

### Automated unit and contract tests

- Media1 and Media2 audio parsing with complete, missing and malformed vendor
  responses.
- MediaMTX codec normalization for AAC, Opus, both G.711 variants, G.722, LPCM,
  unknown and no-audio paths.
- fMP4 indexing of video-only and video+audio fixtures.
- A/V timestamp rebasing and decoder-signature changes.
- Central migration, serialization, assignment and stream-update policy tests.
- Backward compatibility with an old node and legacy segments.
- UI tests for autoplay mute, one-audible-player enforcement, reconnect, volume,
  camera switch and audio-only errors.
- Playback compatibility-job concurrency and resource-limit tests.

### Integration tests

For each supported camera/codec combination:

1. probe the selected ONVIF profile and compare it with MediaMTX observed tracks;
2. create a new segment and verify MediaMTX stored synchronized video and audio;
3. listen live through WebRTC;
4. play, seek and pause recorded audio through the browser;
5. verify G.711 playback uses the compatibility path and remains synchronized;
6. test a video-only camera with no regressions; and
7. repeat the node portion on Windows and Ubuntu.

Target real cameras should include at least one G.711 camera, one alternate
codec if available, and one video-only profile.

## 11. Observability and safety

- Never log camera credentials, RTSP URLs containing credentials or audio data.
- Log normalized state changes and playback compatibility-job results.
- Add node counters for audio-capable paths, compatibility jobs and failures.
- Bound process count, CPU, temporary storage and retry rate.
- Existing video recording and live viewing must remain available when audio
  probing or playback conversion fails.

## 12. Implementation sequence

1. **Experiment gate:** validate detection and G.711-to-AAC recorded playback
   against real files/cameras on Windows and Ubuntu.
2. **Contracts and migration:** central models/schemas, assignment fields and
   generated web API types.
3. **Detection:** ONVIF metadata, MediaMTX runtime observation and UI status.
4. **Structured recording metadata:** indexer, upload and legacy handling.
5. **Live listening:** web controls and single-audible-player coordination.
6. **Recorded listening:** direct playback plus compatibility rendition.
7. **Regression and real-camera acceptance:** full backend/web suites, Ubuntu
   and Windows node tests, storage/CPU measurements and documentation.
8. **Desktop backlog update:** record the exact parity work, but do not implement
   desktop in this slice.

## 13. Completion criteria

This H6 one-way-audio slice is complete only when:

1. Shah-NVR distinguishes advertised audio from an actually received track.
2. The UI displays the observed codec and available properties.
3. New segments automatically contain audio whenever the camera supplies it.
4. A user can explicitly unmute one live camera and hear synchronized audio.
5. A user can hear, seek and pause synchronized recorded audio, including a
   real G.711 recording in a supported browser.
6. Video-only cameras and old recordings keep working.
7. Windows and Ubuntu media nodes pass the integration checks.
8. Automated tests pass and resource usage stays within measured limits.

## 14. Approved implementation decisions

1. MediaMTX always records audio when the selected camera stream supplies it.
2. Shah-NVR does not provide a separate Record Audio Off setting.
3. Two-way talk remains outside this first H6 delivery.
4. Desktop remains deferred until backend and web acceptance.

