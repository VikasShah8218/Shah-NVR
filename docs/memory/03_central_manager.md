# 03: central_manager (the "main server")

Path: `central_manager/`. Run it with `py main.py` (inside `workon nvr`). Swagger is at `http://<host>:8000/docs`.

## 1. Files
```
central_manager/
├── main.py                 FastAPI app, lifespan (RegisterTortoise + 3 background loops), CORS, routers, uvicorn.run
├── .env / .env.example     settings (.env is git-ignored)
├── pyproject.toml          [tool.tortoise] for Aerich: tortoise_orm="database.config.TORTOISE_ORM", location ./migrations
├── migrations/models/      0_20261012144543_init.py, 1_20261012172329_node_quota.py (PostgreSQL)
├── requirements.txt        fastapi, uvicorn[standard], tortoise-orm[asyncpg], aerich, pydantic, pydantic-settings, tzdata
├── settings/settings.py    Settings(BaseSettings) + `settings` singleton; properties db_url, cors_origins
├── database/config.py      TORTOISE_ORM dict (apps.models = app models + "aerich.models"; use_tz True, timezone UTC)
├── utilities/common.py     utcnow(), run_periodic(name, interval, coro_fn): logs and swallows errors
└── app/
    ├── cameras/      models.py (Camera, CameraStream, StreamStatus), schemas.py, router.py (CRUD, streams, live), utils.py
    ├── nodes/        models.py (MediaNode, NodeState, SCHEDULABLE_STATES), schemas.py, router.py (public + internal), services.py (health loop)
    ├── assignments/  models.py (CameraAssignment, AssignmentHistory), schemas.py, router.py, services.py (scheduler)
    ├── recordings/   models.py (RecordingSegment, SegmentStatus), schemas.py, router.py (timeline + internal ingest/deletions), utils.py, services.py (retention)
    ├── playback/     router.py (index.m3u8), utils.py (build_vod_playlist)
    └── cluster/      router.py (GET /api/v1/cluster/health)
```
`main.py` runs `generate_schemas=settings.db_url.startswith("sqlite")`. With PostgreSQL the schema comes **only from Aerich**; with SQLite (tests) it is auto-created.

## 2. Settings (`settings/settings.py`, overridable in `.env` or environment variables)
| Name | Default | Meaning |
|---|---|---|
| APP_NAME | Shah-NVR Central Manager | |
| HOST / PORT | 0.0.0.0 / 8000 | |
| LOG_LEVEL | INFO | |
| CORS_ORIGINS | `*` | comma-separated; `cors_origins` property |
| DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME | localhost/5432/postgres/""/nvr | `db_url` builds `postgres://user:pass@host:port/name` (URL-quoted) |
| DATABASE_URL | None | full override, e.g. `sqlite://C:/tmp/x.sqlite3` for tests |
| HEARTBEAT_TIMEOUT_SECONDS | 15 | node → UNREACHABLE |
| LEASE_TTL_SECONDS | 30 | lease renewed per heartbeat |
| FAILOVER_GRACE_SECONDS | 10 | extra wait after lease expiry |
| SCHEDULER_INTERVAL_SECONDS / HEALTH_INTERVAL_SECONDS | 5 / 5 | |
| RETENTION_INTERVAL_SECONDS | 600 | |
| MAX_MOVES_PER_CYCLE | 20 | |
| STREAM_STATUS_STALE_SECONDS | 60 | stream → UNKNOWN when no report arrives |
| DEFAULT_RETENTION_DAYS | 7 | for new cameras without retention_days |
| PLAYBACK_GAP_TOLERANCE_SECONDS | 2.0 | timeline gap calculation |
| PLAYBACK_MAX_HOURS | 24 | max range per timeline/playlist request (422 above it) |

## 3. Models (Tortoise 1.x syntax: `fields.IntField(primary_key=True)`)
- **Camera:** id, name, description, username, password (plaintext; the API only exposes `has_password`), enabled, retention_days, timestamps. Reverse relation `streams`.
- **CameraStream:** camera FK (CASCADE), profile, source_url (**without** credentials), record, rtsp_transport (`tcp|udp|automatic`), status (StreamStatus enum), status_detail, bytes_received, last_status_at, last_segment_at. `path_name()` returns `cam-{camera_id}/{profile}`.
- **MediaNode:** see the 02 data model. `SCHEDULABLE_STATES = (READY, ACTIVE)`.
- **CameraAssignment:** a OneToOne with camera (related_name `assignment`). Node FK nullable SET_NULL, generation, lease_expires_at, reason.
- **AssignmentHistory:** ordered by `-started_at`.
- **RecordingSegment:** UUID PK. `parts` is a list of int ms durations (part N is served at `/part/N.m4s` on the node). `file_path` is relative to the node's RECORDINGS_DIR. Indexes (camera_id, profile, start_time) and (status, end_time). Not partitioned yet (needed at scale).

## 4. Key functions
- `cameras/utils.py`:
  - `build_source_url(stream, camera)` injects `quote(username):quote(password)@` into the URL unless the URL already has credentials. Special characters such as `p@ss:word` are quoted (tested).
  - `camera_to_out(camera)` builds `CameraOut`, including assignment info. It queries `CameraAssignment.get_or_none(...).prefetch_related("node")`; don't use `fetch_related` on the reverse O2O, because it breaks when there is no row.
- `assignments/services.py`: `pick_node`, `assign_camera(camera_id, node|None, reason)`, `scheduler_tick()`, all guarded by an `asyncio.Lock`. **There is no leader election**, so run one central instance only. A PostgreSQL advisory lock is the planned fix.
- `nodes/services.py::node_health_tick`: stale nodes become UNREACHABLE; stale stream statuses become UNKNOWN.
- `recordings/utils.py`:
  - `find_segments(camera, profile, start, end)` returns AVAILABLE segments overlapping the range, ordered by start_time then `-generation`.
  - `compute_gaps(segments, start, end)` merges overlaps and reports gaps longer than the tolerance.
- `recordings/router.py::resolve_range(start, end, minutes)`: naive datetimes are treated as UTC; `minutes` means "last N minutes"; the range is limited to PLAYBACK_MAX_HOURS.
- `recordings/services.py::retention_tick`: per camera, `end_time < now − retention_days` becomes DELETING.
- `playback/utils.py::build_vod_playlist`: see 02 §7. Constants: `OVERLAP_TOLERANCE=500ms`, `GAP_TOLERANCE=1s`, `UNAVAILABLE_NODE_STATES=(UNREACHABLE, OFFLINE)`. The response media type is `application/vnd.apple.mpegurl`.

## 5. Behaviours worth knowing
- **Delete camera** returns 409 when it has recordings ("disable it instead"). Recordings disappear through retention.
- **Delete a stream** returns 409 if it is the last stream of the camera.
- **Live** returns 409 if the camera is disabled or unassigned.
- **Delete node** returns 409 while cameras are assigned (drain first). With recordings, `force=true` is needed, and it cascades and removes the catalog rows. A node that is still running will register again.
- **Heartbeat** renews leases with `CameraAssignment.filter(node_id).update(lease_expires_at=now+TTL)`. It sets `node.metrics = body.model_dump()` (free JSON) and returns `storage_quota_bytes`.
- **Register** upserts by `name`, moves UNREACHABLE to READY, and returns `heartbeat_interval_seconds`.
- **Segment ingest** ignores unknown cameras (counted as `ignored`) and returns `{accepted, duplicates, ignored}`. The node marks the whole batch uploaded either way.
- **Stream-status reports** from a node that no longer owns the camera are ignored (stale-owner protection).
- `NodeUpdate.storage_quota_gb`: `null` removes the limit; a float sets bytes = gb × 1024³. The quota is GiB-based.

## 6. Migrations (Aerich)
- `aerich init -t database.config.TORTOISE_ORM` was already done; the config is in pyproject.toml.
- First time on a new DB: `aerich init-db`. After model changes: `aerich migrate --name <change>`, then `aerich upgrade`.
- Migrations are generated against PostgreSQL. **Do not generate them against SQLite** (the dialect differs).
- Existing: `0_…_init.py` (all tables) and `1_…_node_quota.py` (`ALTER TABLE media_nodes ADD storage_quota_bytes BIGINT`).

## 7. Adding a new central app (pattern)
1. Create `app/<name>/{__init__.py, models.py, schemas.py, router.py, services.py|utils.py}`.
2. Add the models module to `APP_MODELS` in `database/config.py`.
3. Include the router in `main.py`. Add a background loop to the `tasks` list if needed (`run_periodic`).
4. Run `aerich migrate && aerich upgrade`, then refresh the OpenAPI types for the UI (07 §5).
