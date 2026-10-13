# 11. Desktop client `nvr_desktop` (Python + PySide6 QML + libmpv)

Status (2026-10-14): **built and verified against the local stack.** All pages have the same design, UX and operations as
`nvr_client`. 37 pytest tests pass. Not committed yet (commit only when the user asks). The plan it follows:
`docs/DESKTOP_APP_PLAN.md`. Setup, run steps and the code map: `nvr_desktop/README.md`.

## Stack and versions
- Python 3.13 (`nvr` venv): PySide6 6.12.0, python-mpv 1.0.8, httpx 0.28.1, pydantic 2.14, pydantic-settings 2.15.
  Dev: pytest 9.1.1, respx 0.23.1.
- libmpv: `nvr_desktop/bin/libmpv-2.dll` (git-ignored), zhongfly/mpv-winbuild `2026-09-29-b4b5d69a44`. Extract the
  archive with Windows `tar -xf`; py7zr cannot handle BCJ2.
- Qt Quick: Controls style **Basic**, fully re-skinned by `ui/theme/Theme.qml` (same hex tokens as `nvr_client/src/index.css`).
  Geist fonts and Lucide SVG icons are bundled; icons come through the `image://icon/<name>/<rrggbb>` provider.

## Architecture in one screen
- `main.py`:
  1. Calls `prepare_libmpv`.
  2. Sets **`QSG_RENDER_LOOP=basic`** and **`QSGRendererInterface.OpenGL`**.
  3. Sets `LC_NUMERIC=C`, which mpv needs.
  4. Loads fonts, builds the stores and registers them as QML singletons (`import App`).
  5. Loads `ui/Main.qml`, then restores and saves the window state.
- Singletons:
  - Plumbing: Prefs, Toasts, Router, Fmt, Status, Utils.
  - Page stores: Cluster, Cameras, Nodes, Dashboard, CameraDetail, NodeDetail, Assignments, Live, Playback, SettingsPage.
- **Stores** (`app/features/<page>/store.py`, base `app/core/store.py`) own all state and actions:
  - `fetch()` runs background reads with in-flight dedupe and drives `loading`/`error`.
  - `act()` runs actions and shows success/error toasts, using the server's `detail` text.
  - `run_task()` (QThreadPool) is the only threading helper.
  - Pollers mirror the web's TanStack intervals.
- **QML** holds layout and bindings only. Pure logic is ported from the web files and unit-tested:
  - `format.py`, `status.py`
  - `alerts.py` (buildAlerts), `resources.py` (nodeUtils)
  - `timeline.py` (mergeRanges/tickStep, local-time ticks)
  - `forms.py` (camera validation + stream diff)
  - `live/sources.py` (URL per protocol)
- Router: `Router.go(page, id, params)`. Pages are `ui/pages/<page>/*.qml`, loaded by a Loader in `Main.qml`. Playback
  accepts `params {camera, profile, t}`, used by camera detail → Recordings and the cameras row menu.

## Differences from the web client (deliberate)
- Live protocols are **Auto (RTSP → LL-HLS) / RTSP / LL-HLS**. mpv has no WHEP/WebRTC; RTSP is lower latency anyway.
- Playback is the same HLS VOD playlist. The wall clock is `2020-01-01 UTC + time-pos` (mpv `rebase-start-time=no`),
  verified frame-exact against the timestamp burned into the camera image.
- Extra setting: **Hardware decoding** (auto-safe / nvdec / d3d11va-copy / nvdec-copy / CPU). The tile info label shows
  the active decoder (`1280×720 · RTSP · d3d11va-copy` on the dev PC).
- Snapshots are taken by mpv (`screenshot-to-file`) into `Pictures/Shah-NVR`. Chunk downloads go to `Downloads`, with a
  progress toast.
- Fullscreen ("immersive"): F11 on Live View or the Playback fullscreen button hides the sidebar and top bar; Esc leaves.
- Settings and the Live grid are stored in QSettings (`ShahNVR/Desktop`), not localStorage. The window position, size
  and maximized state are remembered.

## Video engine (`app/video/`): what was learned, keep it
Each item below cost real debugging time. The details are in the docstring of `mpv_item.py`.
1. **OpenGL scene graph and the `basic` render loop.** With the threaded loop, Python ran on Qt's render thread and
   `grabWindow` deadlocked on the GIL.
2. **Qt owns the FBO.** Overriding `createFramebufferObject` in Python caused a double free.
3. **`render_context.py` replaces python-mpv's `MpvRenderContext`:**
   - python-mpv built the parameter array from temporaries, so libmpv read freed memory (heap corruption 0xC0000374).
   - It uses its own `ctypes.CDLL` handle, because python-mpv's errcheck wrappers share the function objects.
4. **Threads only queue.** libmpv callbacks append to a lock-protected deque in `_MpvBridge` and emit one
   *argument-less* `wake` signal. The GUI thread drains the queue.
   - The bridge is a child of the item, so it is deleted on the GUI thread.
   - It is `close()`d first, in the item's `destroyed` handler.
   - The earlier design emitted signals with Python payloads from mpv threads and crashed when many tiles were created or
     destroyed together.
5. **Lazy players.** The `mpv.MPV` is created on the first `play()`, so empty grid tiles cost nothing.
   - The render context is freed in `_Renderer.__del__`.
   - The player is terminated exactly once: by the renderer if the item is already gone, otherwise by the item's
     destroyed handler.
   - A renderer replaced while the item lives posts `render-lost`; the next one posts `render-ready`.
6. **No mpv Lua scripts** (`load_*` = no in `profiles.py`). Each one spawned a Lua VM and a thread per player. LuaJIT's
   first-chance SEH exceptions (code `0xe24c4a02`) also made faulthandler dump stacks concurrently, which muddied
   crash analysis.
7. **Never name a QQuickItem property `state`.** It is shadowed by QML's `state`; the item uses `playState`.
8. **QML layout:**
   - Never size Grid children from the Grid's own width inside a Layout. It caused an infinite polish loop (100% CPU
     hang): size from a plain wrapper Item.
   - An integer Repeater model **resets all delegates** when the number changes. Live uses `model: 16` with
     `visible: index < layout`, so tiles never reconnect when the layout changes or a camera is placed.
9. A `QQuickItem` subclass imported inside a function named `app` rebinds the `app` package name. In `main.py` the
   QGuiApplication is called `qt_app`.

Stress-verified: 40 cycles of 9 tiles torn down while connecting, and 20 cycles of 16 tiles, with no crash. The full UI
sequence (layouts 4 → 9 → 1 → 16, navigate away and back) is clean.

## Dev harness (not in the repo)
Claude used a scratchpad script `shoot.py OUTDIR "page,page=id,page+objName.method(arg),page+@Store.slot(a;b)" waitms`.
It builds the real app, visits pages, calls QML functions or store slots, saves screenshots and prints QML warnings.
Pages expose hooks for it: `CameraDetailPage.showTab(name)` (objectName `cameraDetail`); CamerasPage's form has the
objectName `cameraForm`.
The local test stack:
- Central on SQLite (`DATABASE_URL=sqlite://…`).
- A media node with `SEGMENT_SECONDS=20`.
- `tools/camera_simulator.py --count 2`, which serves rtsp://127.0.0.1:8654/sim-1 and sim-2.

## Not done yet / next
- Packaging (Nuitka standalone with libmpv bundled), plus a check on a clean PC.
- Real-server check: the Axis camera on `shah-ho-1`, 16 tiles over the network, delay versus the web client.
- Optional: keyboard shortcuts for the playback controls (space, arrows); a per-tile audio toggle (audio is off by default).
