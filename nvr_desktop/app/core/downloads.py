"""Download recorded chunks (MP4) to the user's Downloads folder, with toasts for progress/result."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QStandardPaths

from app.core.api import node as node_api
from app.core.tasks import run_task
from app.core.toasts import ToastBus


def downloads_folder() -> Path:
    return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation))


def download_chunk(toasts: ToastBus, api_url: str, segment_id: str, camera_id: int, profile: str, start: datetime) -> None:
    target = downloads_folder() / f"cam{camera_id}_{profile}_{start:%Y%m%d_%H%M%S}.mp4"
    url = node_api.media_file_url(api_url, segment_id)
    toasts.info(f"Downloading {target.name}…")
    run_task(lambda: node_api.download(url, target),
             lambda path: toasts.success(f"Saved {path}"),
             lambda exc: toasts.error(str(exc)))
