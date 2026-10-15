# 07: Operations, deployment, testing, troubleshooting

## 1. Machines
| Machine | Role | Facts |
|---|---|---|
| **Dev PC** (user's laptop) | development | Windows 11, `D:\Drive-1\Shah-Secret-Project\Shah-NVR`, Python 3.13.3, venv `C:\Users\Mr. Shah\Envs\nvr`, Node 22.14 / npm 10.9, FFmpeg at `C:\ffmpeg-2026-01-22\bin`, Chrome and Edge installed, local PostgreSQL on 5432 (password unknown to Claude; tests use SQLite), RTX 3050 Laptop GPU, Tailscale IP `100.64.14.13`, Wi-Fi `192.168.1.37`. Port 5173 is used by the HID Trinetra Vite app. |
| **Server `shah-ho-1`** | test/prod node + central | Windows (build 26200), user `shah`, repo `F:\Drive-1\Shah-NVR`, Python 3.12.0, venv `C:\Users\Shah\Envs\nvr` (has onvif-zeep + project deps), **no FFmpeg**, PostgreSQL 5432 with DB `nvr`, 20 cores, 16 GB RAM, RTX 3050 8 GB, F: drive ~200 GB, Tailscale `100.64.182.102` (MagicDNS `shah-ho-1.tail6dae1b.ts.net`), LAN `192.168.1.3`. OpenSSH server enabled; the default shell is cmd. |
| **Camera** | AXIS M1125, fw 6.50.1.3 | `192.168.1.241` (LAN of the server). VAPIX works with digest auth; ONVIF returns "Sender not authorized" for root. Image is 1920×1080, rotation 180. Default GOP is 32 frames @30 fps. |

Credentials for all three are in **`docs/memory/environment.local.md`** (git-ignored).

## 2. Server layout and service control
- `F:\Drive-1\Shah-NVR\central_manager\.env`: `DB_PASSWORD=<see local file>`, everything else default.
- `F:\Drive-1\Shah-NVR\media_node\.env`: `NODE_NAME=shah-ho-node-1`, `PUBLIC_HOST=100.64.182.102` until 2026-10-15. **Change it to `PUBLIC_HOST=auto`**: a Tailscale IP made every video link Tailscale-only, so LAN PCs without Tailscale could not play anything.
- `F:\Drive-1\Shah-NVR\media_node\bin\mediamtx.exe`: v1.21.2 (downloaded with curl and unpacked with `tar -xf` on the server).
- Recordings: `F:\Drive-1\Shah-NVR\media_node\data\recordings\`.
- Logs: `C:\Users\Shah\nvr-logs\central_manager.log`, `media_node.log`. The MediaMTX log is in `media_node\data\logs\mediamtx.log`.
- **`C:\Users\Shah\nvr-start.ps1 <central_manager|media_node>`** starts the service *detached* from SSH using `Invoke-CimMethod Win32_Process Create`, so it survives the SSH session ending:
  ```powershell
  param([string]$Service)
  $py = "C:\Users\Shah\Envs\nvr\Scripts\python.exe"; $dir = "F:\Drive-1\Shah-NVR\$Service"; $logs = "C:\Users\Shah\nvr-logs"
  New-Item -ItemType Directory -Force $logs | Out-Null
  $cmd = "cmd /c set PYTHONUNBUFFERED=1&& `"$py`" main.py > `"$logs\$Service.log`" 2>&1"
  Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine=$cmd; CurrentDirectory=$dir}
  ```
- **`C:\Users\Shah\nvr-stop.ps1`** stops the processes listening on 8000 and 7100, and any mediamtx under `F:\Drive-1\Shah-NVR\`.
- Usage: `powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\Shah\nvr-start.ps1 central_manager`, then the same with `media_node`.
- These services are **not Windows services**, so they don't start on boot. A future improvement is NSSM or Task Scheduler.

## 3. How Claude reached the server
- Windows OpenSSH can't take a password non-interactively, so **paramiko** was installed into the scratchpad (`pip install --target <scratch>/pylib paramiko`). Neither project venv was touched.
- Helpers (scratchpad, recreate when needed):
  - `rssh.py "<cmd.exe command>"`: run a command and print stdout, stderr and the exit code. The password comes from the `SSH_PASS` env var.
  - `rput.py <local> <remote>`: SFTP upload. Remote paths are like `F:\…`, converted to `/F:/…`.
  - `rget.py <remote dir> <local dir>`: download the `.py` files in a folder.
- Quirks:
  - The cmd shell sometimes prints "The system cannot find the path specified." to stderr. It's harmless noise.
  - `move` can't move a **directory across drives** (Access is denied); use PowerShell `Move-Item` on the same drive.
  - Complex quoting is easier with a .py or .ps1 file uploaded and then run.
  - Bash `$var` expansion inside the rssh argument loop didn't work reliably; write explicit commands.

## 4. Deploying code to the server
GitHub is the source of truth (https://github.com/VikasShah8218/Shah-NVR.git).

**Preferred** (once commits are pushed):
```cmd
cd /d F:\Drive-1\Shah-NVR && git pull --ff-only
```

**Used before pushing** (no GitHub involved): create a git bundle locally, upload it, then fast-forward:
```bash
git bundle create fix.bundle <server_head>..main      # local
# upload to F:\Drive-1\Shah-NVR\.fix.bundle, then on server:
git pull --ff-only .fix.bundle main && del .fix.bundle
```

> ⚠️ **Current server repo state (2026-10-13):** the server is at old commit **`188b919`**. The user later
> **rewrote history** to remove Co-Authored-By trailers (same file contents, new hashes; GitHub `main` = `afd25cb`).
> A plain `git pull` on the server will **fail or merge badly**. Since the trees are identical, fix it with:
> `git fetch origin && git reset --hard origin/main` (this keeps untracked `.env`, `bin/` and `data/`; check `git status` first).

After pulling:
- **If central models changed:** `cd central_manager && aerich upgrade` (or `aerich migrate --name x` first, if the migration wasn't generated yet).
- **If requirements changed:** `C:\Users\Shah\Envs\nvr\Scripts\python.exe -m pip install -r central_manager\requirements.txt -r media_node\requirements.txt`.
- **Restart both:** `nvr-stop.ps1`, then `nvr-start.ps1 central_manager`, then `nvr-start.ps1 media_node`.

## 5. Local testing toolkit
- **Camera simulator** (`tools/camera_simulator.py`):
  - A separate MediaMTX on `:8654` (TCP only), plus one FFmpeg process per camera publishing a `testsrc2` pattern with a drawtext clock.
  - `--count N --size 1280x720 --fps 25 --bitrate 1500k --codec h264|h265 --file sample.mp4`.
  - GOP is equal to fps (1 s).
  - The font is set with `fontfile='C\:/Windows/Fonts/arial.ttf'`, because this FFmpeg build has no fontconfig.
- **Central on SQLite:** `DATABASE_URL="sqlite://<scratch>/c.sqlite3" py main.py` (schema auto-generated).
- **Fast node:** `DATA_DIR=<scratch>/n1 RECORDINGS_DIR=<scratch>/n1/recordings SEGMENT_SECONDS=10 HLS_PART_TARGET_SECONDS=2 py main.py`.
  - Quota test: add `DISK_MIN_KEEP_HOURS=0 DELETION_INTERVAL_SECONDS=10`, run the simulator with `--bitrate 4000k`, and `PATCH storage_quota_gb=0.02`.
- **Verify playback with FFmpeg** (as a stand-in for a player):
  ```bash
  ffprobe -v error -count_frames -select_streams v:0 -show_entries stream=nb_read_frames:format=duration -of compact "<playlist url>"
  ffmpeg -v error -i "<playlist url>" -f null -        # should be silent
  ```
  frames ÷ duration should equal the fps. Before tfdt rebasing, FFmpeg marked 25 frames (D flag) per chunk join.
- **Headless UI testing** (the Browser MCP extension wasn't connected):
  - `npm install playwright-core@1.48.2` in the scratchpad.
  - Launch `C:/Program Files/Google/Chrome/Application/chrome.exe`, headless, with `--autoplay-policy=no-user-gesture-required`.
  - Scripts: `shoot.mjs` (screenshots every page, prints `video.videoWidth`/`currentTime` and overlay text, collects console errors and failed requests) and `interact.mjs` (adds a camera through the form, edits limits, opens logs, clicks the timeline).
  - Use `addInitScript` to seed localStorage (`shah-nvr.live`, `shah-nvr.settings`).
- **Wall-clock check:** compare the playback overlay time with the simulator's burned-in clock (or the camera OSD). They matched exactly.
- **Failover test:** run two nodes with different ports, kill node-1's agent and MediaMTX by PID (`Get-NetTCPConnection -LocalPort 7100`), and watch the `/assignments/{id}/history`.

## 6. Troubleshooting
| Symptom | Cause / fix |
|---|---|
| `ZoneInfoNotFoundError: 'No time zone found with key UTC'` | Install `tzdata` (in requirements). Windows has no tz database. |
| Node start: MediaMTX API never comes up / ports busy | A leftover mediamtx from a hard kill. The agent kills it automatically (`kill_orphan_mediamtx`); otherwise `taskkill /F /IM mediamtx.exe`. |
| `localhost:5173` shows "HID Trinetra" login | The other app owns `::1:5173`. nvr_client uses **5180**. |
| Chunks split into 1–2 huge parts (~30 s) | Camera GOP doesn't line up with MediaMTX fragments. Already handled by the 1.5× forced cut (see 08). |
| Playlist plays but FFmpeg drops frames at chunk joins | tfdt not rebased. The node must serve parts through `/part/` (rebasing); check `LocalSegment.tracks` isn't empty. |
| Camera stuck CONNECTING | Wrong RTSP URL or credentials, or the camera is unreachable from the **node**. Check node Logs → MediaMTX. |
| Stream IDLE | Normal for `record=false` profiles: they connect on demand. |
| NOT_RECORDING | The stream is up but no chunk finished in 2×segment + 30 s. Check disk, permissions, MediaMTX log. |
| Playback 404 "No playable recordings" | No AVAILABLE segments in range (the newest chunk isn't finished yet), or the node holding them is UNREACHABLE. |
| Browser can't open node tabs / media | The node advertises an address the browser can't reach: Node page → "Clients connect to …". Use `PUBLIC_HOST=auto` (LAN IP). Otherwise check Windows Firewall for TCP 7100/8000/8554/8888/8889 and UDP 8189 on the LAN (Private/Public) profile. |
| ONVIF "Sender not authorized" (Axis) | Axis keeps a separate ONVIF user list. Use VAPIX `param.cgi` or the known RTSP format instead. |
| `aerich` warning "use native migrations for tortoise>=1.0" | Harmless; Aerich works with Tortoise 1.1.8. |
| npm ERESOLVE with openapi-typescript | Already handled by the `overrides` in package.json. |
