from datetime import datetime

from pydantic import BaseModel


class NodeStatusOut(BaseModel):
    node_name: str
    node_id: int | None
    api_url: str
    central_url: str
    central_online: bool
    last_central_contact: datetime | None
    mediamtx_running: bool
    mediamtx_version: str | None
    recordings_dir: str
    disk: dict
    volumes: list[dict] = []  # storage volumes: path, state, caps, sizes, which one is being written
    assigned_cameras: int
    ready_paths: list[str]
    pending_uploads: int
    local_segments: int
