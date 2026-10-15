# Desktop App Implementation Plan: `nvr_desktop` (Python + PySide6 QML + libmpv)

> Status: **approved 2026-10-13; phases 0–5 built 2026-10-14** (all pages, tests, README). Remaining: phase 6 packaging (Nuitka).
> What was actually built and the lessons learned: `docs/memory/11_desktop_nvr_desktop.md`.

## Context
The React client `nvr_client/` was built to test every backend feature and settle the UX. The user now wants the
**competitive product client as a native desktop app**. Decision (made with the user): **Python + PySide6 + QML for app
and UI, libmpv for video**, with the rule that **video frames never pass through Python**. libmpv does network I/O,
hardware decoding (d3d11va / nvdec, with CPU fallback) and rendering on the GPU. Python only sends commands.

Requirements from the user:
1. **Same design**: Dusk slate theme, same layout, same components.
2. **Same UI/UX**: same pages, flows and interactions.
3. **Same operations**: every feature of `nvr_client`.
4. **Neat, clean codebase** that any developer can read and debug.

On approval, this plan is also saved in the repo as **`docs/DESKTOP_APP_PLAN.md`** and linked from `docs/memory/00_INDEX.md`.

Unavoidable differences from the web client:
- **Live uses RTSP** directly from MediaMTX (lowest latency, no browser limits). mpv can't do WHEP/WebRTC, so the protocol choice becomes **Auto (RTSP → LL-HLS) / RTSP / LL-HLS**.
- Settings are stored with **QSettings**, not localStorage.

No backend changes are needed; the app uses the existing APIs (see `docs/memory/06_api_reference.md`).

---

## 1. Stack
| Concern | Choice |
|---|---|
| Language | Python 3.12+ (same `nvr` venv habits; its own `requirements.txt`) |
| UI | **PySide6 6.8+ LTS, Qt Quick / QML**, Controls "Basic" style fully re-skinned by our Theme |
| Video | **libmpv** (`libmpv-2.dll`, a shinchiro/zhongfly Windows build, in `nvr_desktop/bin/`, git-ignored) + **python-mpv** (ctypes) using the **mpv render API (OpenGL)** inside a custom QML item |
| HTTP | **httpx** (sync) run on a `QThreadPool` worker, so the UI thread never blocks; results come back via Qt signals |
| Data types | **pydantic v2** models mirroring the API schemas (`CameraOut`, `NodeOut`, `TimelineOut`…) |
| Charts | Small custom QML `Canvas` area chart (no QtCharts dependency) |
| Icons and font | **Lucide SVGs** (same icons as the web) and the **Geist** font (OFL), bundled |
| Tests | **pytest** for all pure logic and the API client (with `respx`) |
| Packaging (last phase) | **Nuitka** (standalone, compiled, harder to decompile) |

Qt Quick must use the **OpenGL** scene-graph backend (`QQuickWindow.setGraphicsApi(QSGRendererInterface.OpenGL)`), because the mpv render API is OpenGL-based. The default on Windows is D3D11.

## 2. Folder structure (same spirit as the servers: one folder per feature, small files)
```
nvr_desktop/
├── main.py                       # py main.py → builds QApplication, registers stores, loads ui/Main.qml
├── requirements.txt              # PySide6, python-mpv, httpx, pydantic, pydantic-settings
├── .env.example                  # CENTRAL_URL=http://localhost:8000 (first-run default only)
├── bin/                          # libmpv-2.dll (git-ignored; README explains the download)
├── settings/settings.py          # pydantic BaseSettings: startup defaults (CENTRAL_URL, LOG_LEVEL, MPV_DLL_DIR)
├── app/
│   ├── core/
│   │   ├── api/
│   │   │   ├── models.py         # pydantic models = API contract (one place to update when the API changes)
│   │   │   ├── central.py        # CentralApi: typed methods for every /api/v1 endpoint
│   │   │   ├── node.py           # NodeApi(api_url): status, assignments, mediamtx paths, segments, logs, media URLs
│   │   │   └── errors.py         # ApiError(status, message), FastAPI "detail" parsing (port of client.ts::errorMessage)
│   │   ├── tasks.py              # run_task(fn, on_ok, on_err): QThreadPool + signals; the ONLY threading helper
│   │   ├── poller.py             # Poller(QTimer): calls a refresh fn every N s, pauses when its page is hidden
│   │   ├── store.py              # BaseStore(QObject): loading / error / data properties + notify signals
│   │   ├── preferences.py        # Preferences(QObject) over QSettings (centralUrl, pollSeconds, liveProtocol, gridUsesSubstream, hwdec, live layout)
│   │   ├── format.py             # format_bytes, format_mbps, format_percent, format_duration, time_ago, ratio (port of lib/format.ts)
│   │   ├── status.py             # status → tone mapping (port of StatusBadge.tsx TONE)
│   │   └── toasts.py             # ToastBus(QObject): success/error messages shown by QML Toast
│   ├── video/
│   │   ├── mpv_item.py           # MpvVideoItem(QQuickFramebufferObject) + Renderer: mpv render context, update callback
│   │   ├── profiles.py           # mpv option sets: LIVE_RTSP, LIVE_HLS, PLAYBACK (documented, one place)
│   │   └── loader.py             # finds and loads libmpv-2.dll (os.add_dll_directory), clear error if missing
│   └── features/                 # one folder per page: a store (state + actions exposed to QML) + pure logic
│       ├── dashboard/  store.py, alerts.py         # build_alerts() port of DashboardPage.tsx
│       ├── live/       store.py                    # grid layout + tiles persisted in Preferences
│       ├── playback/   store.py, timeline.py       # merge_ranges(), tick_step(), local-time tick alignment
│       ├── cameras/    store.py, forms.py          # CRUD + stream diff (port of CameraFormSheet/useSyncStreams)
│       ├── nodes/      store.py, resources.py, history.py   # node_resources() port, metrics ring buffer (240 pts)
│       ├── assignments/store.py
│       └── settings/   store.py                    # test connection, save, reset
├── ui/                           # QML only: no business logic, only bindings to stores
│   ├── Main.qml                  # window: Sidebar + Topbar + page StackView (router)
│   ├── theme/Theme.qml           # singleton: Dusk slate tokens (identical hex values to nvr_client/src/index.css)
│   ├── components/               # Button, IconButton, Card, Badge, StatusBadge, StatusDot, UsageBar, UsageMeter,
│   │                             # KpiCard, PageHeader, Field, Input, Select, Switch, ToggleGroup, Tabs, DataTable,
│   │                             # Sheet (side drawer), Dialog, ConfirmDialog, Popover, CalendarPopup, Toast, Tooltip,
│   │                             # EmptyState, ErrorState, Loading, Icon, AreaChart
│   ├── layout/                   # Sidebar.qml (collapsible, remembered), Topbar.qml (central status, nodes, cameras, clock)
│   ├── video/VideoView.qml       # wraps MpvVideoItem: connecting/error overlays, info overlay (WxH · RTSP · ms)
│   └── pages/                    # dashboard/ live/ playback/ cameras/ nodes/ assignments/ settings/ (same as the web)
├── assets/ fonts/Geist-*.ttf, icons/*.svg (lucide)
└── tests/                        # pytest: format, status, alerts, resources, timeline, forms, api (respx)
```
**Readability rules:**
- QML files hold layout and bindings only. All logic lives in Python stores or pure functions, which are unit-tested.
- One store per page. Every store exposes `loading`, `error` and its data, and has methods (`@Slot`) for actions.
- Each pure-logic module is a direct port of a named web file, with a header comment like "port of nodeUtils.ts". The two clients stay comparable.
- Logging uses `logging` with module loggers. Errors are always shown in the UI (ErrorState or toast) and never swallowed.

## 3. Video engine design (the critical part)
- **`MpvVideoItem`** (QQuickFramebufferObject):
  - Creates its own `mpv.MPV(vo="libmpv", ...)` and an `MpvRenderContext(mpv, "opengl", get_proc_address=QOpenGLContext.currentContext().getProcAddress)` in the renderer's `createFramebufferObject`.
  - `render()` calls `ctx.render(opengl_fbo={fbo, w, h})`. mpv's update callback emits a queued signal, which calls `item.update()`.
  - **One mpv instance per tile.** Each runs its own demux and decode threads; ctypes calls release the GIL. Per frame, Python does a single small call.
- QML properties and methods:
  - Properties: `source`, `profile` (live-rtsp | live-hls | playback), `hwdec`, `muted`, `paused`, `speed`, `timePos`, `duration`, `videoWidth/Height`, `state` (idle/connecting/playing/error), `errorText`, `hwdecCurrent`, `latencyMs`.
  - Methods: `play(url)`, `stop()`, `seekAbsolute(sec)`, `seekRelative(sec)`, `screenshot(path)`.
- **mpv profiles** (`video/profiles.py`):
  - **LIVE_RTSP:** `profile=low-latency`, `rtsp-transport=tcp`, `cache=no`, `untimed=yes`, `video-sync=audio`/default, `demuxer-lavf-o=fflags=+nobuffer`, `hwdec=<pref, default auto-safe>`, `vd-lavc-threads` default.
  - **LIVE_HLS:** like the above, with the HLS URL.
  - **PLAYBACK:** normal cache, **`rebase-start-time=no`** (see below), `hr-seek=yes`, `keep-open=yes`.
- **Reconnect:** watch the `idle-active` / `end-file` events and retry with backoff `2 s × 2^n` (max 30 s), resetting on the first frame. This is the same logic as `LivePlayer.tsx`. Auto mode falls back RTSP → LL-HLS after a failure.
- **Wall-clock time for playback:**
  - The node already rewrites every part's timestamps to **absolute time since 2020-01-01** (`media_node/app/recordings/utils.py::rebase_timestamps`).
  - With `rebase-start-time=no`, mpv's `time-pos` is that absolute value, so **wall clock = 2020-01-01 UTC + time-pos**. Seeking to a wall time inside the loaded playlist is `seek(t − epoch, "absolute")`.
  - This is verified in Phase 0. Fallback: the playlist start time plus `time-pos`.
- **Live delay / info overlay:** read `video-params/w,h`, `hwdec-current`, and `demuxer-cache-duration` (approximate delay).
- **Hardware decoding:** the Settings page offers `auto-safe` (default), `nvdec`, `d3d11va-copy` or `no` (CPU). The overlay shows `hwdec-current`, so you can see which decoder is in use.
- **Grid rules (same as the web):** the `sub` profile in multi-tile layouts when available (Preferences toggle) and `main` for single or full-screen. Tiles hidden by navigation are stopped.

## 4. Feature parity map (web → desktop)
| Web (`nvr_client/src/features/...`) | Desktop page / store | Notes |
|---|---|---|
| layout/AppLayout (sidebar + topbar + clock) | `ui/layout/*`, `Main.qml` | Same nav items, icons and collapse behaviour |
| dashboard/DashboardPage | `pages/dashboard`, `features/dashboard` | KPIs, `build_alerts` (same rules), streams-by-status, node cards |
| live/LivePage + LivePlayer + whep | `pages/live`, `features/live`, `video/*` | Camera list with search, click or drag to tile, layouts 1/4/9/16, protocol menu, clear, fullscreen, double-click → main stream, tile menu (protocol override, open main, **snapshot via mpv**, copy RTSP, details, remove), REC badge, overlay |
| playback/PlaybackPage + Timeline + VodPlayer | `pages/playback`, `features/playback` | Camera / profile / date (CalendarPopup, ‹ ›), HH:MM:SS go-to, copy VLC URL, player controls (±10 s, ±1 min, play/pause, speed 0.5–8×, fullscreen), wall-clock overlay, Timeline (24h/6h/1h/10m, Now, drag-pan, click-seek, local-time ticks, coverage), chunks table (click → seek, **Download** saves the MP4 with a progress toast) |
| cameras/CamerasPage + CameraFormSheet + CameraDetailPage | `pages/cameras`, `features/cameras` | Table, search, enable switch, row menu; add/edit Sheet (same validation, stream editor, brand URL hints); detail tabs Overview (live preview + profile toggle, details, live URLs with copy, streams table) / Recordings (24 h timeline → Playback) / Assignment (lease countdown, Move, history) |
| nodes/NodesPage + NodeActions + NodeDetailPage + LogViewer + ResourceCharts | `pages/nodes`, `features/nodes` | Totals tiles; table (CPU·cores, GPU, RAM, storage/quota, disk free, usable, cameras, network, versions, heartbeat); menu (Edit limits, Drain with confirm, Cordon, Activate, Delete with force); detail: Compute / Storage / Agent cards, live charts (240-point history), tabs Cameras / MediaMTX paths / Recorded chunks / Logs (Agent·MediaMTX, All/Warnings+/Errors, filter, pause, copy) |
| assignments/AssignmentsPage + MoveCameraDialog | `pages/assignments`, `features/assignments` | Table with lease countdown, Move dialog, History sheet, Run scheduler now |
| settings/SettingsPage | `pages/settings`, `features/settings` | Central URL (Test, Save), refresh interval, live protocol (Auto/RTSP/LL-HLS), substream in grids, **+ hardware decoding mode**, reset |
| api/queries.ts polling | `core/poller.py` per store | Same intervals: 5 s lists (setting), 3 s node detail and logs, 15 s live info, 20–30 s timeline |
| sonner toasts | `core/toasts.py` + `Toast.qml` | Success and error messages carry the server's `detail` text |

**Theme parity:** `Theme.qml` copies the tokens in `nvr_client/src/index.css` exactly (background `#2e3440`, card `#3b4252`, border `#4c566a`, primary `#88c0d0`, success `#a3be8c`, warning `#ebcb8b`, danger `#bf616a`, video `#1f232b`, radius 10 px…). Typography uses Geist with the same sizes (text-xl titles, text-sm body, text-xs hints). Status colours use the same tone map.

## 5. Phases
| Phase | Deliverable | Exit check |
|---|---|---|
| **0. Spike** (de-risk) | `MpvVideoItem` in a bare QML window: 1 RTSP tile, then 4 main + 16 sub tiles of the Axis camera; HLS VOD playback with `rebase-start-time=no` | Smooth 16 tiles, `hwdec-current` = d3d11va/nvdec, CPU fallback works, wall clock matches the camera's on-screen clock, a disconnect recovers without UI freezes |
| **1. Skeleton** | Folder structure, `main.py`, Theme, components library, Sidebar/Topbar/StackView, Preferences, tasks, poller, BaseStore, toasts, API client and models, tests for format/status | The app opens on the Dashboard shell; pytest passes |
| **2. Read-only pages** | Dashboard, Media Nodes (+ detail with charts and logs), Assignments, Settings | Numbers match the web client side by side |
| **3. Live View** | Grid, tiles, protocols, snapshot, fullscreen, persistence | Same behaviour as the web; latency below the web's HLS |
| **4. Cameras** | List, form sheet (create/edit/streams), detail tabs, move | Create a camera in the desktop app → RECORDING |
| **5. Playback** | Timeline, VOD player, chunks, download | Click-seek lands on the right wall time; downloads open in VLC |
| **6. Polish and package** | Keyboard shortcuts, empty/error states, window state memory, Nuitka build, README | The standalone build runs on a clean PC (with libmpv bundled) |

## 6. Critical existing code to reuse or port (with sources)
- Theme tokens: `nvr_client/src/index.css`.
- Status tones: `nvr_client/src/components/StatusBadge.tsx`.
- Formatting: `nvr_client/src/lib/format.ts`. Node resource math: `nvr_client/src/features/nodes/nodeUtils.ts`.
- Alert rules: `nvr_client/src/features/dashboard/DashboardPage.tsx::buildAlerts`.
- Timeline math: `nvr_client/src/features/playback/Timeline.tsx` (`mergeRanges`, `tickStep`, local tz alignment).
- Camera form validation and stream diff: `nvr_client/src/features/cameras/CameraFormSheet.tsx`; reconnect backoff: `live/LivePlayer.tsx`.
- API contract: `nvr_client/openapi/central.json`, `node.json` (generate the pydantic models from them or write them by hand; keep them in `app/core/api/models.py`).
- Wall-clock basis: `media_node/app/recordings/utils.py::TIMELINE_EPOCH` (2020-01-01 UTC).

## 7. Risks and mitigations
- **mpv render API + Qt Quick on Windows needs the OpenGL backend.** Phase 0 proves it. If OpenGL interop is a problem on a machine, use `hwdec=d3d11va-copy` / `nvdec-copy` (still GPU decode, one copy).
- **Many mpv instances:** test 16 sub + 4 main in Phase 0. Fall back to stopping off-screen tiles, which is planned anyway.
- **python-mpv / libmpv version mismatch:** pin both and document the exact libmpv build in the README.
- **Licensing:** PySide6 and Qt are LGPL (dynamic linking: fine for commercial use); libmpv must be an LGPL build for proprietary distribution (check before release).

## 8. Verification (end to end)
1. `pytest nvr_desktop/tests` passes (pure logic ported from the web, plus the API client against mocked responses).
2. Run the local stack (central on SQLite, node, `tools/camera_simulator.py --count 2`) and `py main.py` in `nvr_desktop`. Walk every page **side by side with `nvr_client`**: same data, same actions.
3. Against the server (`CENTRAL_URL=http://192.168.1.3:8000`) with the Axis camera:
   - Live: 16 tiles; check the `hwdec-current` overlay and delay.
   - Playback: wall clock matches the camera on-screen time.
   - Node page: quota edit takes effect.
4. Failure checks: stop the simulator (tile shows reconnecting, then recovers); stop central (Topbar shows offline, video keeps playing); force `hwdec=no` (CPU fallback).
5. Phase 6: Nuitka standalone build on a clean Windows PC.
