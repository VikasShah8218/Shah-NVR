# Shah-NVR Desktop

Native Windows client for Shah-NVR: **Python + PySide6 (Qt Quick / QML) + libmpv**.
It has the same pages, design and operations as the web client (`nvr_client/`). Video is
decoded on the GPU and drawn by libmpv; **video frames never pass through Python**.

| Page | What you can do |
|---|---|
| Dashboard | KPIs, alerts, streams by status, node cards |
| Live View | 1 / 2×2 / 3×3 / 4×4 grid, click or drag cameras onto tiles, RTSP or LL-HLS, snapshot, fullscreen (F11) |
| Playback | Day timeline (24h / 6h / 1h / 10m, drag to pan, click to play), wall-clock player, ±10 s / ±1 min, 0.5–8×, chunk list, MP4 download |
| Cameras | Add / edit (streams, brand URL examples), enable / disable, delete; detail tabs Overview / Recordings / Assignment |
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

The tests cover all logic outside QML: formatting, status tones, dashboard alerts, node
resource maths, timeline maths, camera form validation and stream diff, live URL selection, and the
API clients (against mocked HTTP with `respx`).

## Code map

```
main.py                  start-up: libmpv, OpenGL scene graph, fonts, stores -> QML singletons, ui/Main.qml
settings/settings.py     first-run defaults (.env)
app/core/                shared plumbing, no page knowledge
  api/                   CentralApi / NodeApi (httpx) + pydantic models = the API contract
  tasks.py               run_task(): the only threading helper (QThreadPool -> signals on the GUI thread)
  store.py               BaseStore: loading / error / fetch() / act() (actions with success/error toasts)
  poller.py, list_model.py, preferences.py (QSettings), format.py, status.py, toasts.py, router.py, icons.py
app/features/<page>/     one folder per page: store.py (state + @Slot actions for QML) + pure logic modules
app/video/               the video engine (see below)
ui/                      QML: layout and bindings only, no business logic
  theme/Theme.qml        Dusk slate tokens (same hex values as nvr_client/src/index.css)
  components/            Button, Card, Table, Select, Sheet, Dialog, Timeline, ... (shadcn look-alikes)
  pages/<page>/          one folder per page
  video/VideoView.qml    MpvVideoItem + connecting / error / info overlays
assets/                  Geist fonts (OFL), Lucide icons (ISC)
tests/                   pytest
```

Each logic module notes which web file it ports (for example "port of nodeUtils.ts"), so the two
clients can be compared side by side.

## Video engine: rules that must not be broken

These rules come from crashes found during development (`app/video/mpv_item.py` explains each one):

1. **The OpenGL scene graph and the `basic` render loop** are set in `main.py` before
   QGuiApplication exists. The mpv render API is OpenGL, and the basic loop keeps all rendering on
   the GUI thread, so Python never runs on Qt's render thread.
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
7. **No property named `state` on a QQuickItem.** It shadows QML's own `state`, so the item uses
   `playState`.

Playback wall clock: the media node rebases recorded timestamps to time since
2020-01-01 UTC, and mpv runs with `rebase-start-time=no`. So `time-pos` *is* the recording time:
`wall clock = 2020-01-01 UTC + time-pos` (`MpvVideoItem.wallClockMs()`).

## Troubleshooting

- **"libmpv-2.dll not found"**: see Setup step 2. `MPV_DLL_DIR` in `.env` can point elsewhere.
- **Video is black and the info label says "CPU"**: the GPU decoder was refused. Pick another one
  in Settings → Hardware decoding (`d3d11va-copy` works on any DirectX 11 GPU).
- **Live tile keeps "Retrying…"**: check that the node's RTSP port (8554) is reachable from this
  PC, or switch the grid to LL-HLS.
- Logs go to the console. `LOG_LEVEL=DEBUG` also shows mpv's own warnings.
