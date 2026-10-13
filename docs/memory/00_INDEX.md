# Shah-NVR project memory: index

This folder is the project's long-term memory. It was written so that a **new Claude session (or a new developer)
can pick up the project with full context**: what was built, how it works, why it was built that way, what was
tested, what broke and how it was fixed, how the user likes to work, and what comes next.

Last full update: **2026-10-13** (desktop client added 2026-10-14). Code at commit `afd25cb` on GitHub `main` (see 10_status_and_roadmap.md).

## Reading order
| # | File | Read it when |
|---|---|---|
| 01 | [01_project_overview.md](01_project_overview.md) | Always, first: goals, scope, history of the conversation and decisions |
| 02 | [02_architecture.md](02_architecture.md) | Before any design or cross-service change: components, data flows, ports, state machines |
| 03 | [03_central_manager.md](03_central_manager.md) | Touching `central_manager/`: models, routers, scheduler, settings, migrations |
| 04 | [04_media_node.md](04_media_node.md) | Touching `media_node/`: MediaMTX control, recording pipeline, fMP4 indexer, quota, logs |
| 05 | [05_frontend_nvr_client.md](05_frontend_nvr_client.md) | Touching `nvr_client/`: stack, structure, pages, live/playback players, theme |
| 06 | [06_api_reference.md](06_api_reference.md) | Every HTTP endpoint (public, internal, node, MediaMTX) with payloads |
| 07 | [07_operations_and_deployment.md](07_operations_and_deployment.md) | Running, deploying to the server, testing tools, troubleshooting |
| 08 | [08_decisions_and_lessons.md](08_decisions_and_lessons.md) | Before changing behaviour that looks odd: the reason is probably here |
| 09 | [09_user_and_workflow.md](09_user_and_workflow.md) | How the user communicates and what they expect |
| 10 | [10_status_and_roadmap.md](10_status_and_roadmap.md) | What is done, known limits, next steps |
| 11 | [11_desktop_nvr_desktop.md](11_desktop_nvr_desktop.md) | Touching `nvr_desktop/`: architecture, differences from the web, **video engine rules** |
| — | `environment.local.md` | **Git-ignored**: SSH, DB and camera credentials. Present only on the user's PC. |

Other useful files in the repo:
- `Initial_archetecture.txt`: the user's original architecture spec (DVMS, 24 sections). Typos in the filename are the user's.
- `IMPLEMENTATION_PLAN.md`: the first full plan written by Claude (HLS-first review of the spec).
- **`docs/DESKTOP_APP_PLAN.md`**: approved plan for the desktop client `nvr_desktop` (Python + PySide6 QML + libmpv), giving the same design, UX and operations as nvr_client. **Built 2026-10-14**; see 11_desktop_nvr_desktop.md.
- `README.md` (root) and `nvr_client/README.md`: how to run things.
- `docs/Shah-NVR.postman_collection.json`: 30 Postman requests. It predates the quota, logs and delete-node APIs.
- Claude's plan file outside the repo (`C:\Users\Mr. Shah\.claude\plans\now-can-you-please-playful-sunset.md`) now holds the desktop plan; `docs/DESKTOP_APP_PLAN.md` is the copy in the repo. The earlier web-UI plan is summarised in 05_frontend_nvr_client.md.

## How to "import" this memory in a new session
`CLAUDE.md` loads automatically. For deep work say: *"read docs/memory/00_INDEX.md and the files relevant to X"*.
When this memory and the code disagree, **the code wins**. Fix the memory file in the same change.
