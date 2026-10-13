# 09: The user and how they like to work

## Who
- **Vikas Shah** ("Mr. Shah"), GitHub `VikasShah8218`, work email domain essi.co.in. He's a backend-leaning Python developer (FastAPI, Tortoise, Django in other projects), comfortable with video/CCTV (has used Frigate, Tyco VMS and ONVIF), and builds several projects (HID Trinetra, ANPR, FRS, auth server).
- Writes quickly, with typos ("archetecture", "centeral"), in Indian English. Understands well. Prefers practical explanations with step-by-step flows ("small small steps").

## Communication preferences
- Often says **"answer in short"**. When he does, give a compact answer: tables and bullets, no essays.
- Likes **step-by-step pipeline breakdowns** (e.g. "main server does X → slave does Y").
- Wants **professional, industry-standard** approaches and asks whether something is "competitive" (compared with Milestone, Genetec, Frigate, Tyco).
- Wants to be asked before big choices, and picks from options (theme, UI library, protocols). When asked, he gave clear choices. Offer a recommended option first.
- Reviews plans before building (used plan mode for the UI).

## Explicit instructions he gave (keep following them)
- Activate the environment with **`workon nvr`**.
- Use **Tortoise ORM + Aerich**. The DB name is `nvr`.
- Python service layout: `main.py` at the root (run with **`py main.py`**), `app/<app>/{router,models,schemas,utils}.py`, a `database/` folder for Tortoise settings, a `settings/settings.py` with pydantic BaseSettings, a `.env` next to `main.py`, and a utilities folder.
- **No authentication, JWT or nginx for now.** Testing is done with **Postman and VLC**, and now the React UI.
- The UI has to be clean and easy, with a **soft night theme close to light mode, not too dark**. React first; later a **Python desktop app**.
- A Media Nodes page showing per-node **CPU, GPU, RAM, storage left, total storage assigned, and a usable storage quota** ("node can only use 100 GB").
- Ignore the `tests/` folder and stray files when building (`tests/onvif_explorer.py` is his own ONVIF explorer script).
- Asked for this memory dump to be **very detailed**, so future sessions can import it.

## Git / repo habits
- Repo: https://github.com/VikasShah8218/Shah-NVR.git, branch `main`.
- He pushes himself, and **rewrote history to remove `Co-Authored-By: Claude` trailers**. Don't add them unless he asks.
- Commit only when asked; ask before pushing. Never commit secrets: `.env`, `media_node/bin/` and `media_node/data/` are git-ignored.
- He pulls on the server himself sometimes; Claude has also deployed through SSH and git bundles.

## Things he will likely ask next (be ready)
- Pushing or syncing the server repo (needs `git reset --hard origin/main` on the server; see 07 §4).
- More cameras or brands, ONVIF discovery, the RTSP URL for brand X.
- Exports (time-range MP4, compressed export), motion or events, AI analytics.
- Authentication and security when moving towards production.
- Desktop app (Python, maybe PyQt/PySide since he has a `pyqt` venv), reusing the same APIs.
- Scaling to 1,000 cameras: partitioning `recording_segments`, multiple central instances, Windows services.
