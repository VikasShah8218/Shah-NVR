# CLAUDE.md: Shah-NVR

Claude Code loads this file automatically in every session. It holds the essentials. Full detail
is in **[docs/memory/](docs/memory/00_INDEX.md)**: read `00_INDEX.md` first when starting non-trivial
work, then the file for the area you will touch.

## What this project is
Shah-NVR is a distributed **Network Video Recorder** for IP cameras (initial target 1,000 cameras at 1080p30, built to grow to 10,000+).
- **central_manager/**: the "main server" (Python FastAPI, PostgreSQL). It holds the camera and node registry, runs the scheduler and failover, keeps the recording catalog, and builds live URLs and HLS playlists. **It never handles video.**
- **media_node/**: the "recording/streaming server" (Python FastAPI agent plus MediaMTX). It pulls cameras, records fMP4 chunks, indexes them, uploads metadata, and serves recorded media. **It never touches PostgreSQL**; it keeps its own SQLite file.
- **nvr_client/**: a React 19 + TypeScript web UI used to test every feature and settle the UX.
- **nvr_desktop/** (built 2026-10-14, not committed yet): the product desktop client, Python + PySide6 QML + libmpv, with the same design and operations as nvr_client. Run `py main.py` in `nvr_desktop/`; tests: `python -m pytest`. **Read `docs/memory/11_desktop_nvr_desktop.md` before touching `app/video/`**: the video engine rules there come from real crashes.

## Hard rules / user preferences (follow these)
- **Python env:** `workon nvr` (virtualenvwrapper-win, `%USERPROFILE%\Envs\nvr`). Run every service with **`py main.py`** from its folder.
- **ORM:** **Tortoise ORM** with **Aerich** migrations, in `central_manager/` only. `media_node` uses SQLite with `generate_schemas=True`.
- **Folder pattern for every Python service** (the user asked for this explicitly):
  `main.py` at the service root, `.env` next to `main.py`, `settings/settings.py` (pydantic `BaseSettings`),
  `database/config.py` (`TORTOISE_ORM`), `utilities/`, and `app/<app_name>/{router.py, models.py, schemas.py, utils.py | services.py}`.
- **No authentication, JWT or nginx** in this phase; the user asked for this explicitly. Testing is done with Postman, VLC and the React UI.
- **Short answers when asked:** the user often writes "answer in short". Then keep it brief.
- **Commits:** the user rewrote history to **remove the `Co-Authored-By: Claude` trailer**. Do not add it unless the user asks. Commit only when asked, and ask before pushing.
- **Secrets** (SSH, DB and camera passwords) live in the git-ignored `docs/memory/environment.local.md`. Never put them in committed files.
- UI theme: **"Dusk slate"**, a soft dark that is close to light, never pure black (see `docs/memory/05_frontend_nvr_client.md`).

## Run (dev)
```bash
workon nvr
cd central_manager && py main.py          # :8000  docs at /docs
cd media_node && py main.py               # :7100  (starts MediaMTX from media_node/bin)
py tools/camera_simulator.py --count 2    # fake RTSP cams: rtsp://127.0.0.1:8654/sim-1, sim-2
cd nvr_client && npm run dev              # :5180 (NOT 5173 – another local app uses 5173)
```
- Quick central test without PostgreSQL: set the environment variable `DATABASE_URL=sqlite://<path>` and the schema is generated automatically.
- Media node test settings: `SEGMENT_SECONDS=10 HLS_PART_TARGET_SECONDS=2`. Put `DATA_DIR` and `RECORDINGS_DIR` in a scratch folder.
- After changing a backend API: run `py tools/export_openapi.py`, then `cd nvr_client && npm run gen:api`.
- After changing central models: `cd central_manager && aerich migrate --name <x> && aerich upgrade`.

## Production-like test server
- Windows host `shah-ho-1`, Tailscale IP `100.64.182.102`, LAN `192.168.1.3`. The repo is at `F:\Drive-1\Shah-NVR`.
- The real camera is an **AXIS M1125** at `192.168.1.241`. Its RTSP address is `/axis-media/media.amp?videocodec=h264&resolution=1920x1080&fps=30&videokeyframeinterval=30`. ONVIF refuses the root user.
- Services run detached. Start them with `C:\Users\Shah\nvr-start.ps1 <central_manager|media_node>` and stop them with `nvr-stop.ps1`. Logs are in `C:\Users\Shah\nvr-logs\`.
- See `docs/memory/07_operations_and_deployment.md`. Credentials are in `environment.local.md`.

## Where things are
| Need | File |
|---|---|
| Overall architecture and data flows | docs/memory/02_architecture.md |
| Central manager internals | docs/memory/03_central_manager.md |
| Media node internals (MediaMTX, fMP4 indexer, tfdt rebasing) | docs/memory/04_media_node.md |
| React client | docs/memory/05_frontend_nvr_client.md |
| Every API endpoint | docs/memory/06_api_reference.md |
| Deploy, server, testing, troubleshooting | docs/memory/07_operations_and_deployment.md |
| Why things are the way they are, bugs found | docs/memory/08_decisions_and_lessons.md |
| How the user likes to work | docs/memory/09_user_and_workflow.md |
| Status, open items, next steps | docs/memory/10_status_and_roadmap.md |
