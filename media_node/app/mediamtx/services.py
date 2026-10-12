import asyncio
import logging

import psutil

from app.mediamtx.utils import MANAGED_PREFIX, mtx, write_config
from app.node.services import refresh_assignments
from app.node.utils import runtime
from settings.settings import settings

logger = logging.getLogger("node.mediamtx")


def kill_orphan_mediamtx() -> None:
    """If the agent was killed hard, its MediaMTX child may still hold our ports. Stop it."""
    for conn in psutil.net_connections(kind="tcp"):
        if conn.status != psutil.CONN_LISTEN or not conn.pid:
            continue
        if conn.laddr.port not in (settings.MEDIAMTX_API_PORT, settings.RTSP_PORT):
            continue
        try:
            proc = psutil.Process(conn.pid)
            if "mediamtx" in proc.name().lower():
                logger.warning("Stopping leftover MediaMTX (pid %s) holding port %s", conn.pid, conn.laddr.port)
                proc.kill()
                proc.wait(timeout=5)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
            pass


class MediaMTXSupervisor:
    """Starts MediaMTX as a child process and restarts it if it exits."""

    def __init__(self) -> None:
        self._proc: asyncio.subprocess.Process | None = None
        self._task: asyncio.Task | None = None
        self._stopping = False

    async def start(self) -> None:
        if not settings.MEDIAMTX_BIN.exists():
            raise FileNotFoundError(f"MediaMTX binary not found: {settings.MEDIAMTX_BIN} (set MEDIAMTX_BIN in .env)")
        settings.RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        kill_orphan_mediamtx()
        self._task = asyncio.create_task(self._run_forever())
        for _ in range(50):  # wait up to ~10 s for the API
            if await mtx.ping():
                runtime.mediamtx_running = True
                runtime.mediamtx_version = await mtx.version()
                logger.info("MediaMTX is up (version %s)", runtime.mediamtx_version)
                return
            await asyncio.sleep(0.2)
        logger.error("MediaMTX API did not come up; check %s", settings.DATA_DIR / "logs" / "mediamtx.log")

    async def _run_forever(self) -> None:
        log_dir = settings.DATA_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        backoff = 1.0
        while not self._stopping:
            config_path = write_config()
            with open(log_dir / "mediamtx.log", "ab") as log:
                self._proc = await asyncio.create_subprocess_exec(
                    str(settings.MEDIAMTX_BIN), str(config_path),
                    cwd=str(settings.DATA_DIR), stdout=log, stderr=log,
                )
                logger.info("MediaMTX started (pid %s)", self._proc.pid)
                code = await self._proc.wait()
            runtime.mediamtx_running = False
            if self._stopping:
                break
            logger.error("MediaMTX exited with code %s; restarting in %.0fs", code, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
            # When it comes back, the reconcile loop re-adds every camera path.

    async def stop(self) -> None:
        self._stopping = True
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=10)
            except TimeoutError:
                self._proc.kill()
        if self._task:
            self._task.cancel()
        logger.info("MediaMTX stopped")


supervisor = MediaMTXSupervisor()


def desired_paths() -> dict[str, dict]:
    """MediaMTX path config for every stream this node must pull."""
    desired = {}
    for cam in runtime.assignments.values():
        for s in cam["streams"]:
            conf = {
                "source": s["source_url"],
                "record": bool(s["record"]),
                # Recorded streams are always pulled; live-only streams connect when someone watches.
                "sourceOnDemand": not s["record"],
            }
            if s["source_url"].lower().startswith(("rtsp://", "rtsps://")):
                conf["rtspTransport"] = s["rtsp_transport"]
            desired[s["path_name"]] = conf
    return desired


async def reconcile_tick() -> None:
    """Make MediaMTX run exactly the camera paths assigned to this node (level-triggered)."""
    await refresh_assignments()
    if not await mtx.ping():
        runtime.mediamtx_running = False
        return
    runtime.mediamtx_running = True

    desired = desired_paths()
    actual = {n: c for n, c in (await mtx.list_config_paths()).items() if n.startswith(MANAGED_PREFIX)}

    for name in actual.keys() - desired.keys():
        await mtx.delete_path(name)
        runtime.ready_since.pop(name, None)
        logger.info("Stopped path %s (no longer assigned)", name)

    for name, conf in desired.items():
        try:
            if name not in actual:
                await mtx.add_path(name, conf)
                logger.info("Started path %s (record=%s)", name, conf["record"])
            else:
                changed = {k: v for k, v in conf.items() if actual[name].get(k) != v}
                if changed:
                    await mtx.patch_path(name, changed)
                    logger.info("Updated path %s: %s", name, sorted(changed))
        except Exception as exc:  # one bad camera must not block the others
            logger.error("Failed to apply path %s: %r", name, exc)
