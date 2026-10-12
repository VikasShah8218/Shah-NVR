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
    assigned_cameras: int
    ready_paths: list[str]
    pending_uploads: int
    local_segments: int
