# nvr_client

The React + TypeScript web UI for Shah-NVR: browser access to every operator feature, with the same pages and design as the Windows desktop client (`nvr_desktop/`).

**Stack:** Vite, React 19, TypeScript, Tailwind v4, shadcn/ui (Radix), TanStack Query, React Router, hls.js, and recharts. The colour scheme is the soft-dark "Dusk slate" theme, defined in `src/index.css`.

## Run

```bash
cd nvr_client
npm install
cp .env.example .env          # set VITE_CENTRAL_URL, e.g. http://192.168.1.3:8000 (the server's LAN IP)
npm run dev                   # http://localhost:5180
```

The central manager URL can also be changed in the app under **Settings**; that value is saved in the browser.

Other commands:

| Command | What it does |
|---|---|
| `npm run build` | Type-check and build to `dist/` (a static site you can serve from any web server) |
| `npm run lint` | oxlint |
| `npm run gen:api` | Regenerate `src/api/central.d.ts` and `node.d.ts` from `openapi/*.json` |

After changing a backend API, refresh the types so the UI stays in sync:
```bash
py tools/export_openapi.py        # from the repo root: writes nvr_client/openapi/*.json
cd nvr_client && npm run gen:api
```

## Pages

| Page | What you can do |
|---|---|
| **Dashboard** | See cluster totals and alerts (cameras not recording, unreachable nodes, disk or quota nearly full), plus a card for each node |
| **Live View** | Build a 1, 2×2, 3×3 or 4×4 grid by clicking or dragging cameras. Choose WebRTC, LL-HLS, or Auto (WebRTC first, HLS if that fails). Grid tiles use the substream; double-click a tile for the main stream, with digital zoom and pan (mouse wheel, drag, on-screen controls, or + / − / arrows / 0) and PTZ. Each tile can take a snapshot, copy its RTSP URL for VLC, or switch protocol. |
| **Playback** | Pick a camera, stream and day, then browse a 24h / 6h / 1h / 10m timeline. Click to play from a moment. The clock shows the real recorded time. Controls: ±10 s, ±1 min, 0.5×–8× speed, go-to-time, digital zoom and pan, and copy VLC URL. Each chunk can be downloaded as an MP4, and longer ranges can be exported. |
| **Cameras** | Add, edit, enable/disable and delete cameras. Edit a camera's streams (profile, RTSP URL, record on/off, transport). The detail page has a live preview, stream status, the last 24 h of recordings, and ownership (move to another node, assignment history). |
| **Media Nodes** | Per-node CPU, GPU, RAM, network, recordings used against the **storage quota**, free disk and usable space. Edit a node's camera capacity and quota; drain, cordon, activate or delete a node. The detail page shows live charts, the node's cameras, MediaMTX paths, recorded chunks and live **logs**. |
| **Assignments** | See which node records each camera, with generation and lease. Move a camera, view its history, or run the scheduler now. |
| **Settings** | Central URL (with a connection test), refresh interval, media-node route (LAN / public), default live protocol, and the LL-HLS stability buffer (2–10 s, plays slightly behind live for smoothness on unstable links). |

## How it talks to the backend
- **Central manager:** all reads and every action (`/api/v1/...`) go here. The backend needs `CORS_ORIGINS` set (the default `*` works for development).
- **Media nodes:** read-only pages (status, MediaMTX paths, chunks, logs) and recorded media are fetched directly from each node's `api_url`.
- **Live video:** comes straight from the media node's MediaMTX. WebRTC uses `http://<node>:8889/<path>/whep`; LL-HLS uses `http://<node>:8888/<path>/index.m3u8`.
- **Recordings:** the central manager's HLS playlist (`/api/v1/playback/{id}/index.m3u8`) points at the nodes holding each chunk.
