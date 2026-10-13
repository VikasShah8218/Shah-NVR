# 05: nvr_client (React web UI)

Purpose: test **every** backend feature and settle the UX. After that, the user rebuilds it as a **Python desktop app**,
so keep UX decisions explicit and portable.

## 1. Stack and versions (installed 2026-10-12)
- Vite **8.3** (`@vitejs/plugin-react` 6), React **19.2**, TypeScript **~6.0** (strict by default in TS 6), oxlint.
- Tailwind **v4.3** (`@tailwindcss/vite`, no tailwind.config; theme lives in CSS), `tw-animate-css`.
- shadcn/ui **CLI 4.21**, style **`radix-nova`** (preset Nova, Lucide icons, Geist font via `@fontsource-variable/geist`), `radix-ui` 1.8.
  Init command used: `npx shadcn@latest init -t vite -b radix -p nova -y --no-monorepo`.
- Components added: card badge input label select switch dialog sheet dropdown-menu table tabs tooltip progress separator skeleton alert-dialog popover calendar textarea scroll-area toggle-group toggle sonner (button came from init).
- `@tanstack/react-query` 5, `react-router` 7 (import from `"react-router"`), `hls.js` 1.7, `recharts` 3, `sonner` 2, `date-fns` 4, `lucide-react`, `openapi-fetch` 0.17, `openapi-typescript` 7.13 (dev).
- `package.json` has `"overrides": {"openapi-typescript": {"typescript": "$typescript"}}`, because openapi-typescript declares a peer dependency on TS 5 only.
- Removed on purpose: `next-themes` (the generated sonner component used it; replaced by a fixed `theme="dark"`) and `@tanstack/react-table` (plain shadcn tables are enough).
- Dev server **port 5180** with `strictPort` and `host: true` (vite.config.ts). **5173 is taken** by the user's HID Trinetra app: it listens on `::1`, so `localhost:5173` resolved to *that* app.
- Path alias `@/*` points to `./src/*` (set in vite.config.ts, tsconfig.json and tsconfig.app.json).

## 2. Structure
```
nvr_client/
├── .env.example            VITE_CENTRAL_URL=http://localhost:8000
├── openapi/central.json, node.json     exported by tools/export_openapi.py (committed)
├── src/
│   ├── main.tsx, App.tsx   providers: SettingsProvider → QueryClientProvider → TooltipProvider → BrowserRouter; pages lazy()
│   ├── index.css           Tailwind + Dusk slate tokens (:root), status colours, scrollbars, color-scheme: dark
│   ├── vite-env.d.ts       ImportMetaEnv.VITE_CENTRAL_URL
│   ├── api/
│   │   ├── central.d.ts, node.d.ts   GENERATED (npm run gen:api); never edit by hand
│   │   ├── types.ts        aliases (Camera, MediaNode, Timeline…) + NodeMetrics, NodeAssignment, MtxPath, NodeLogs
│   │   ├── client.ts       ApiError, unwrap(), centralClient(url), nodeClient(url), nodeGet(), mediaFileUrl(), playbackUrl()
│   │   └── queries.ts      every useQuery/useMutation hook (see §4)
│   ├── lib/  settings.tsx (context + localStorage), format.ts (bytes, Mbps, %, durations, timeAgo, ratio), time.ts, utils.ts (cn)
│   ├── components/
│   │   ├── ui/             shadcn components (toggle.tsx was edited: on-state = primary/20 + text-primary)
│   │   ├── layout/AppLayout.tsx    sidebar (collapsible, remembered) + Topbar (central status, nodes healthy, cameras recording, clock) + <Suspense><Outlet/>
│   │   ├── StatusBadge.tsx  TONE map status → success/info/warning/danger/muted; StatusDot; toneOf()
│   │   ├── UsageBar.tsx     UsageBar(percent, warnAt, dangerAt), UsageMeter(label, value, percent, hint)
│   │   └── common.tsx       PageHeader, KpiCard, Loading, EmptyState, ErrorState, ConfirmDialog, Field
│   └── features/
│       ├── dashboard/DashboardPage.tsx
│       ├── live/ LivePage.tsx, LivePlayer.tsx, whep.ts
│       ├── playback/ PlaybackPage.tsx, Timeline.tsx, VodPlayer.tsx
│       ├── cameras/ CamerasPage.tsx, CameraFormSheet.tsx, CameraDetailPage.tsx
│       ├── nodes/ NodesPage.tsx, NodeDetailPage.tsx, NodeActions.tsx (+NodeLimitsDialog), ResourceCharts.tsx, LogViewer.tsx, nodeUtils.ts
│       ├── assignments/ AssignmentsPage.tsx, MoveCameraDialog.tsx
│       └── settings/SettingsPage.tsx
```

## 3. Theme: "Dusk slate" (user chose it: "night mode but not too dark, near light mode")
CSS variables in `src/index.css` (`:root`, single theme):

| Token | Value | Token | Value |
|---|---|---|---|
| background | `#2e3440` | foreground | `#eceff4` |
| card / popover | `#3b4252` | muted | `#353c4a` |
| secondary / accent | `#434c5e` | muted-foreground | `#a9b1c2` |
| border / input | `#4c566a` | primary / ring | `#88c0d0` |
| primary-foreground | `#242933` | destructive | `#bf616a` |
| sidebar | `#272c36` | radius | 0.625rem |
| **success** | `#a3be8c` | **warning** | `#ebcb8b` |
| **info** | `#88c0d0` | **danger** | `#bf616a` |
| **video-bg** | `#1f232b` | | |

Charts use `#88c0d0, #a3be8c, #ebcb8b, #b48ead, #d08770`. Tailwind classes: `bg-success/15 text-success`, `bg-video`, and so on.

Status colours are consistent everywhere:
- green: RECORDING, ACTIVE, AVAILABLE
- cyan: STREAMING, IDLE, READY
- amber: CONNECTING, ASSIGNED, CORDONED, DRAINING, DELETING
- red: NOT_RECORDING, UNKNOWN, UNREACHABLE
- grey: UNASSIGNED, DISABLED, OFFLINE

## 4. Data layer
- `useCentral()` returns `{url, api, poll}` from settings. **Query keys always start with the central URL**, so changing the URL invalidates everything (the Settings page also calls `qc.clear()`).
- Polling: cluster, cameras, nodes and assignments every `settings.pollSeconds` (default 5 s). Node detail every 3 s. Node logs 3 s (pausable). Live info 15 s. Timeline 20–30 s for today. Segments 10 s.
- Mutations go through `useCentralMutation(fn, {success, invalidate})`. On success it invalidates `[url, "cameras"|"nodes"|"assignments"|"cluster-health"]` and shows a success toast; on error it shows the server's `detail` in a toast (`errorMessage` also flattens FastAPI validation arrays).
- Hooks:
  - queries: `useClusterHealth`, `useNodes`, `useNode`, `useCameras`, `useCamera`, `useLive`, `useTimeline`, `useAssignments`, `useAssignmentHistory`, `useNodeStatus`, `useNodeAssignments`, `useNodePaths`, `useNodeSegments`, `useNodeLogs`
  - mutations: `useCreateCamera`, `useUpdateCamera`, `useDeleteCamera`, `useSyncStreams` (add/patch/delete profiles), `useUpdateNode`, `useNodeAction` (drain/cordon/activate), `useDeleteNode`, `useMoveCamera`, `useRunScheduler`
- Typed central calls use `api.GET("/api/v1/cameras/{camera_id}", {params:{path:{camera_id}}})` wrapped in `unwrap()`. Node calls use `nodeGet()` (plain fetch) for untyped endpoints.
- `NodeMetrics` is a hand-written interface for `MediaNode.metrics` (free JSON on the server). Update it when the heartbeat payload changes.

## 5. Pages
| Route | Highlights |
|---|---|
| `/` Dashboard | KPI tiles (cameras, recording X/Y, nodes healthy, chunks last hour, storage plus ingest) and **alerts** built client-side by `buildAlerts`: unreachable node, disk ≥ 85%, quota ≥ 85%, unassigned camera, recorded stream not RECORDING. Also a streams-by-status breakdown and node cards. |
| `/live` | Left: camera list with search; click or drag a camera to a tile. Toolbar: layout 1/2×2/3×3/4×4 and protocol Auto/WebRTC/HLS. Clear and Fullscreen buttons. State is kept in localStorage `shah-nvr.live` `{layout, tiles[16]}`. Grid tiles use `sub` when `gridUsesSubstream` is on and the layout has more than one tile. Double-click opens a dialog with the main stream. Tile menu: protocol override, open main, snapshot (canvas → PNG), copy RTSP, camera details, remove. REC badge. |
| `/playback` | Camera, profile and date (Calendar popover, previous/next day), HH:MM:SS go-to, VLC URL copy. `VodPlayer` with controls and a wall-clock overlay (top-right). Below: Timeline card (zoom 24h/6h/1h/10m, Now, legend, coverage) and a chunks-in-view table (click to seek, download). URL query `?camera=&profile=&t=` is kept in sync. |
| `/cameras` | Table: #, name, stream badges, node link, retention, last recording, enable switch, menu (edit, live, recordings, delete). "Add camera" opens `CameraFormSheet`. |
| `/cameras/:id` | Tabs. **Overview:** live preview with profile toggle, details, live URLs with copy buttons, streams table. **Recordings:** 24 h Timeline; clicking opens Playback at that time. **Assignment:** owner, generation, lease countdown, Move dialog, history. |
| `/nodes` | **Resources page (the user's request):** totals tiles (healthy, average CPU and cores, RAM, recordings with quota and free disk, cameras placed against capacity). The table shows CPU %·cores, GPU util/VRAM ("No GPU data" when there isn't one), RAM used/total, **storage: recordings / quota (%)**, free disk, usable space, cameras/capacity, network ↓/↑, versions and heartbeat age. The row menu: Edit limits (capacity, quota GB or "use whole disk"), Drain (with confirm), Cordon, Activate, Delete (confirm, with a force switch). |
| `/nodes/:id` | Compute, Storage and Node-agent cards. Live charts (CPU/RAM %, network Mb/s); the history lives in a module-level Map, holds about 240 points and survives navigation. Tabs: Cameras (node's own assignments), MediaMTX paths, Recorded chunks (download), Logs (Agent/MediaMTX, All/Warnings+/Errors, filter, pause, copy). |
| `/assignments` | Table with lease countdown, Move, History sheet (vertical timeline), "Run scheduler now". |
| `/settings` | Central URL (Test, Save), refresh interval, default live protocol, substream in grids, reset. localStorage `shah-nvr.settings`. |

`nodeUtils.ts::nodeResources(node)` computes `remaining = min(quota − recordings, disk free)` and `usable = recordings + remaining`. `storagePercent` is recordings/quota when a quota is set, otherwise disk used %.

## 6. Live player (`LivePlayer.tsx` + `whep.ts`)
- **WHEP:**
  - `RTCPeerConnection` with recvonly video and audio transceivers. Create the offer, wait for ICE gathering (up to 1.5 s, non-trickle).
  - `POST {webrtc}/whep` with `Content-Type: application/sdp`. Expect 201 with the answer SDP, then wait for `connectionState=connected` (12 s timeout).
  - The `Location` header (if readable) is used to DELETE the session on close.
  - The delay figure is `jitterBufferDelay / jitterBufferEmittedCount` from getStats.
- **Fallback:** in protocol `auto`, a WebRTC failure falls back to hls.js `{lowLatencyMode: true, backBufferLength: 10, liveDurationInfinity: true}`. The delay figure is `hls.latency`. Safari uses native HLS.
- **Reconnect:** a fatal error or a WebRTC `failed`/`disconnected` state triggers a retry with backoff `2 s × 2^failures` (max 30 s). The failure count is a ref that resets on the `playing` event; the `attempt` state bump re-runs the effect.
- The effect deps are `[stream.webrtc, stream.hls, protocol, attempt]`, so the player reconnects when a camera moves node.
- Overlay: `WxH · WebRTC|HLS · N ms`. `saveSnapshot(video, name)` downloads a PNG.
- **Verified:** locally WebRTC at about 10 ms; against the server over Tailscale with the Axis camera, 1080p main at 41 ms and 640×360 sub at 21 ms.

## 7. Playback internals
- `PlaybackPage` state: cameraId, profile, day (local midnight), zoom (ms), viewStart, playFrom, **playTo** (fixed when playback starts, so the playlist URL stays stable; an early bug rebuilt it with `Date.now()` on every render), playhead.
- Clicking the timeline (or a chunk, or Go) calls `seek(t)`, which sets `playFrom = t` and `playTo = min(dayEnd, now)`. That builds a new playlist URL, and `VodPlayer` reloads.
- `VodPlayer` reads the wall clock from `hlsRef.current.playingDate`. ±10 s and ±60 s seek inside the loaded playlist (`video.currentTime`). Speeds are 0.5, 1, 2, 4, 8. The video is capped at `max-w-[calc(55vh*16/9)]` so the timeline stays visible.
- `Timeline` (SVG):
  - The gap background is muted; recorded ranges (`mergeRanges`, 2 s tolerance) are green; the future area is dimmed; there's a "now" dashed line and a playhead.
  - Click to seek; drag to pan (only when zoomed in).
  - **Ticks are aligned to local time** using `getTimezoneOffset` (the user is in UTC+05:30). Edge labels are anchored start/end.
  - `tickStep` chooses from 1 min to 3 h, aiming for at most 14 labels.

## 8. Commands
```bash
npm install
npm run dev            # :5180
npm run build          # tsc -b && vite build (pages are lazy chunks; hls.js and recharts chunks are large, which is fine)
npm run lint           # oxlint (remaining warnings are deliberate: Date.now in render for clocks, exhaustive-deps on reload effects)
npm run gen:api        # openapi-typescript openapi/central.json → src/api/central.d.ts ; node.json → node.d.ts
```
Run `py tools/export_openapi.py` (repo root, nvr venv) before `gen:api`. It imports each service's `main.app.openapi()` in a separate interpreter, because both services use the package names `app` and `settings`.

## 9. Known UI caveats
- In dev, React StrictMode double-mounts, so one playlist request appears as `ERR_ABORTED`. This doesn't happen in production builds.
- A node's direct API must be reachable from the browser (via `api_url` / PUBLIC_HOST). If it isn't, the node detail tabs show an error but the central data still loads.
- The Postman collection does not yet include quota, logs or delete-node.
