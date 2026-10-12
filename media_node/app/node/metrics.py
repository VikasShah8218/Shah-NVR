"""Host resource metrics reported in every heartbeat (CPU, RAM, GPU, network)."""

import asyncio
import logging
import shutil
import subprocess
import time

import psutil

logger = logging.getLogger("node.metrics")

GPU_CACHE_SECONDS = 10.0
_NVIDIA_SMI = shutil.which("nvidia-smi")

_net_prev: tuple[float, int, int] | None = None
_gpu_cache: tuple[float, list[dict]] = (0.0, [])


def cpu_memory() -> dict:
    mem = psutil.virtual_memory()
    return {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "cpu_count": psutil.cpu_count(logical=True),
        "memory_percent": mem.percent,
        "memory_total_bytes": mem.total,
        "memory_used_bytes": mem.total - mem.available,
    }


def network_rates() -> dict:
    """Whole-host receive/transmit rate in Mbit/s since the previous call."""
    global _net_prev
    counters = psutil.net_io_counters()
    now = time.monotonic()
    prev, _net_prev = _net_prev, (now, counters.bytes_recv, counters.bytes_sent)
    if prev is None or now <= prev[0]:
        return {"net_rx_mbps": None, "net_tx_mbps": None}
    seconds = now - prev[0]
    return {
        "net_rx_mbps": round((counters.bytes_recv - prev[1]) * 8 / seconds / 1e6, 2),
        "net_tx_mbps": round((counters.bytes_sent - prev[2]) * 8 / seconds / 1e6, 2),
    }


def _query_nvidia() -> list[dict]:
    out = subprocess.run(
        [_NVIDIA_SMI, "--query-gpu=name,utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=2,
    )
    gpus = []
    for line in out.stdout.strip().splitlines():
        name, util, used, total = (v.strip() for v in line.split(","))
        gpus.append({
            "name": name,
            "utilization_percent": float(util) if util.replace(".", "").isdigit() else None,
            "memory_used_bytes": int(float(used) * 1024**2) if used.replace(".", "").isdigit() else None,
            "memory_total_bytes": int(float(total) * 1024**2) if total.replace(".", "").isdigit() else None,
        })
    return gpus


async def gpus() -> list[dict]:
    """NVIDIA GPUs via nvidia-smi (cached). Empty list when no NVIDIA GPU / driver is present."""
    global _gpu_cache
    if not _NVIDIA_SMI:
        return []
    if time.monotonic() - _gpu_cache[0] < GPU_CACHE_SECONDS:
        return _gpu_cache[1]
    try:
        result = await asyncio.to_thread(_query_nvidia)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        logger.debug("nvidia-smi failed: %r", exc)
        result = []
    _gpu_cache = (time.monotonic(), result)
    return result
