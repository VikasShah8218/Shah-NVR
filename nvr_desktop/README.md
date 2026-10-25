# Shah-NVR Desktop

Native Windows client for Shah-NVR: **Python + PySide6 (Qt Quick / QML) + libmpv**.
It has the same pages, design and operations as the web client (`nvr_client/`). Video is
decoded on the GPU and drawn by libmpv; **video frames never pass through Python**.

| Page | What you can do |
|---|---|
| Dashboard | KPIs, alerts, streams by status, node cards |
| Live View | 1 / 2×2 / 3×3 / 4×4 grid, click or drag cameras onto tiles, RTSP or LL-HLS, snapshot, fullscreen (F11) |
| Playback | Day timeline (24h / 6h / 1h / 10m, drag to pan, click to play), wall-clock player, ±10 s / ±1 min, 0.5–8×, chunk list, MP4 download |
| Cameras | Add / edit (streams, brand URL examples), enable / disable, delete; detail tabs Overview / Device / Video / Recordings / Assignment |
| Discover | ONVIF network discovery or manual address, multi-camera credential checks, snapshot preview, main/sub selection and onboarding |
| Media Nodes | CPU / GPU / RAM / storage / quota per node, limits, drain / cordon / activate / delete; detail charts, MediaMTX paths, chunks, logs |
| Assignments | Which node records each camera, lease countdown, move, history, run scheduler |
| Settings | Central URL (test / save), refresh interval, live protocol, substreams in grids, hardware decoding |

## Setup

1. **Python environment** (the project uses the `nvr` virtualenv):
   ```
   workon nvr
   pip install -r requirements.txt
   ```
2. **libmpv**. It is not a pip package; it's one DLL, kept out of git.
   - Download `mpv-dev-x86_64-*.7z` from <https://github.com/zhongfly/mpv-winbuild/releases>.
     The tested build is `2026-09-29-b4b5d69a44`.
   - Extract only `libmpv-2.dll` into `nvr_desktop/bin/`. Windows' own `tar` can open the
     archive (`C:\Windows\System32\tar.exe -xf mpv-dev-….7z libmpv-2.dll`); `py7zr` cannot,
     because the archive uses BCJ2.
3. Optional: copy `.env.example` to `.env` to change the first-run central URL.

## Run

```
cd nvr_desktop
py main.py
```

The app talks only to the **central manager** API (default `http://localhost:8000`; change it in
Settings). Video comes straight from the media nodes' MediaMTX. Live uses RTSP
(`rtsp://<node>:8554/...`) with LL-HLS as the fallback. Recordings play as HLS VOD playlists from
the central manager.

Shortcuts:
- **Alt+←**: back.
- **F5**: refresh.
- **F11**: Live View fullscreen.
- **Esc**: leave fullscreen.
- Double-click a tile: open its main stream.
- Double-click the playback video: fullscreen.

## Tests

```
cd nvr_desktop
python -m pytest
```

The tests cover formatting, status tones, dashboard alerts, node resource maths, timelines,
camera forms, live URL selection, API contracts and ONVIF workflows (mocked HTTP, no camera writes).
With libmpv installed, a separate offscreen desktop process also loads the real QML pages with
ONVIF and manual cameras, checks names/enabled state and live metadata updates, opens the Device
tab, H2 Video editor and onboarding sheet, and fails on QML warnings. It uses isolated preferences.

### ONVIF H2 video settings

Open **Cameras → camera → Video**, then choose the NVR stream (main/sub). This requires
the H2-enabled central manager and media node. No new desktop dependencies or migrations are needed.

- Map the stream to its ONVIF profile explicitly; saving a mapping does not change its RTSP URL.
- Edit codec, resolution, frame rate, bitrate, GOP, quality and exposed rate-control/profile fields.
  Multiple advertised option blocks remain separate; a proposal must fit one complete block.
- Storage saver / Best quality / Low-bandwidth substream are editable proposals. Storage estimates
  are decimal GB/day for continuous video at the configured bitrate, not guaranteed VBR usage.
- Review runs a read-only server preflight. Only the subsequent confirmation writes to the camera.
  Shared encoders require acknowledgment. All device streams may briefly stop and recordings may gap.
- History supports restoring saved before-values through another preflight and confirmation.
  Recovery reports fresh stream status and recording evidence, not proof of decoder compatibility.
- Bulk applies only edited fields to the same stream name on up to 20 selected cameras. Each target
  is checked; unsupported/shared targets are skipped. Confirmed writes run sequentially and stop
  after an unverified result. Navigation/server changes cancel unsent work, not a write already sent.
- Writes are never automatically retried. For a pending/unknown outcome, wait at least two minutes
  and use **Resolve / fresh readback** on the affected camera before another write.

Only central history/recovery is polled while this tab is open; camera settings are read on entry,
explicit reload, preflight or readback. The isolated encoder store does not modify camera-list roles
or the live/playback video engine. Automated tests use mocked APIs; physical-camera acceptance
should verify apply/readback and live/recording recovery against the deployed H2 server.

ONVIF H1 operations go through central to a media node, never directly from the desktop to a
camera. Device details are read on opening the Device tab or explicit refresh, not polled.
Wrong credentials are not retried automatically. Time sync and NTP are explicit actions;
reboot requires confirmation and interrupts recording temporarily.

Camera list roles must never be named `model`, `modelData` or `index`: these shadow Qt's
delegate context. The API's hardware `model` stays in camera dictionaries and is exposed
as `deviceModel` in the list model.

## Code map

```
main.py                  start-up: libmpv, render mode (GPU/CPU), fonts, stores -> QML singletons, ui/Main.qml
settings/settings.py     first-run defaults (.env)
app/core/                shared plumbing, no page knowledge
  api/                   CentralApi / NodeApi (httpx) + pydantic models = the API contract
  tasks.py               run_task(): the only threading helper (QThreadPool -> signals on the GUI thread)
  store.py               BaseStore: loading / error / fetch() / act() (actions with success/error toasts)
  poller.py, list_model.py, preferences.py (QSettings), format.py, status.py, toasts.py, router.py, icons.py
app/features/<page>/     one folder per page: store.py (state + @Slot actions for QML) + pure logic modules
app/video/               the video engine (see below)
  player.py              MpvPlayer: one libmpv player + all playback logic (state, reconnect, seek...)
  gl_surface.py          MpvSurface in GPU mode: OpenGL drawing (QQuickFramebufferObject)
  sw_surface.py          MpvSurface in CPU mode: libswscale into memory, Qt software renderer
  render_context.py      safe ctypes wrappers of libmpv's render API (GL and SW)
  render_mode.py         Auto / CPU / GPU selection at startup
  gpu_preference.py      Windows per-app graphics card choice (two-GPU PCs)
  profiles.py            mpv options per stream type (live / playback) and render mode
ui/                      QML: layout and bindings only, no business logic
  theme/Theme.qml        Dusk slate tokens (same hex values as nvr_client/src/index.css)
  components/            Button, Card, Table, Select, Sheet, Dialog, Timeline, ... (shadcn look-alikes)
  pages/<page>/          one folder per page
  video/VideoView.qml    MpvPlayer + MpvSurface + connecting / error / info overlays
assets/                  Geist fonts (OFL), Lucide icons (ISC)
tests/                   pytest
```

Each logic module notes which web file it ports (for example "port of nodeUtils.ts"), so the two
clients can be compared side by side.

## Render modes: GPU and CPU

Settings → **Video rendering**: Auto (default) / CPU / GPU. The mode is chosen once at startup, so a
change needs a restart. `RENDER_MODE=cpu|gpu` in `.env` overrides Settings.

- **GPU**: mpv draws with OpenGL (hardware decoding optional, Settings → Hardware decoding).
- **CPU**: like a web browser. Each frame is decoded on the processor, then converted and scaled to
  the tile's pixel size in one libswscale pass (about 1.6 ms for a 1080p frame). Qt's software
  renderer repaints only the tiles that changed. No graphics card is needed at all.
- **Auto** uses GPU when a real OpenGL driver is present and CPU otherwise (no GPU, or only
  Windows' CPU-emulated OpenGL).

Why CPU mode exists: without a GPU, Qt falls back to a CPU-emulated OpenGL, and mpv's GPU pipeline
then runs on the CPU at full resolution: about 74% CPU and 1–2 fps for 16 tiles. CPU mode drew the
same 16 tiles at about 8–11% CPU in testing.

## Video engine: rules that must not be broken

These rules come from crashes found during development (the docstrings of `player.py`,
`gl_surface.py` and `sw_surface.py` explain each one):

1. **The `basic` render loop** (both modes) and, in GPU mode, the OpenGL scene graph are set in
   `main.py` before the first window. The basic loop keeps all rendering on the GUI thread, so
   Python never runs on Qt's render thread.
2. **Qt owns the FBO.** Never override `createFramebufferObject` in Python; that caused a double
   free.
3. **Our own render-context wrapper** (`render_context.py`). python-mpv's `MpvRenderContext`
   frees its parameter buffers too early, which corrupts the heap on Windows.
4. **Threads only queue.** libmpv callbacks append to a lock-protected queue and emit one
   argument-less signal. The item drains the queue on the GUI thread. The bridge is closed before
   it is deleted.
5. **Players are lazy and terminated exactly once.** A player is created on the first `play()`,
   so empty tiles cost nothing. Its render context is freed before the player is destroyed.
6. **No mpv Lua scripts** (`load_*` options in `profiles.py`). They aren't needed, and each one
   costs a Lua VM and a thread per tile.
7. **No property named `state` on a QQuickItem.** It shadows QML's own `state`, so the player
   uses `playState`.
8. **Render calls never wait.** `BLOCK_FOR_TARGET_TIME=0` in both render contexts. libmpv's default
   blocks each render until the frame's display time (a whole frame interval), which made CPU
   rendering look 25 times slower than it is.
9. **Never call `self.window()` from Python in a surface.** PySide ties the returned window wrapper
   to the item, and the whole app window was deleted together with a removed tile. CPU mode gets the
   pixel ratio from the screen under the tile instead.
10. **No letterbox bars from mpv in CPU mode.** mpv clears bars to `0,0,0,0`, which Qt's RGBX format
    shows as transparent (white). The surface renders at the picture's own aspect ratio
    (`keepaspect=no`) and centres it on the background.

Playback wall clock: the media node rebases recorded timestamps to time since
2020-01-01 UTC, and mpv runs with `rebase-start-time=no`. So `time-pos` *is* the recording time:
`wall clock = 2020-01-01 UTC + time-pos` (`MpvPlayer.wallClockMs()`).

## Troubleshooting

- **Big grids are heavy on a laptop with two GPUs**: Settings → **Graphics card** → High performance, then restart.
  Windows otherwise runs the app on the integrated GPU, whose video decoder saturates at 16 × 1080p (measured: 18 fps
  at 30% CPU on the AMD iGPU vs 30 fps at 6% CPU on the RTX 3050). Settings shows the GPU in use.
- **"libmpv-2.dll not found"**: see Setup step 2. `MPV_DLL_DIR` in `.env` can point elsewhere.
- **Video is black and the info label says "CPU decode"** (GPU mode): the GPU decoder was refused. Pick another one
  in Settings → Hardware decoding (`d3d11va-copy` works on any DirectX 11 GPU).
- **Live tile keeps "Retrying…"**: check that the node's RTSP port (8554) is reachable from this
  PC, or switch the grid to LL-HLS.
- Logs go to the console. `LOG_LEVEL=DEBUG` also shows mpv's own warnings.
