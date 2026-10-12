import os
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Identity / API
    NODE_NAME: str = "node-1"
    HOST: str = "0.0.0.0"
    PORT: int = 7100
    # Host/IP that clients (VLC, browsers) and the central manager use to reach this node.
    PUBLIC_HOST: str = "127.0.0.1"
    CAPACITY_CAMERAS: int = 100
    LOG_LEVEL: str = "INFO"

    # Central manager
    CENTRAL_URL: str = "http://127.0.0.1:8000"
    CENTRAL_TIMEOUT_SECONDS: float = 10.0

    # Storage
    DATA_DIR: Path = BASE_DIR / "data"
    RECORDINGS_DIR: Path = BASE_DIR / "data" / "recordings"

    # MediaMTX
    MEDIAMTX_BIN: Path = BASE_DIR / "bin" / ("mediamtx.exe" if os.name == "nt" else "mediamtx")
    MEDIAMTX_API_PORT: int = 9997
    MEDIAMTX_METRICS_PORT: int = 9998
    RTSP_PORT: int = 8554
    RTP_PORT: int = 8000
    RTCP_PORT: int = 8001
    HLS_PORT: int = 8888
    HLS_VARIANT: str = "lowLatency"  # lowLatency | fmp4 | mpegts
    WEBRTC_PORT: int = 8889
    WEBRTC_UDP_PORT: int = 8189

    # Recording
    SEGMENT_SECONDS: int = 60  # length of one recorded chunk
    PART_SECONDS: float = 1.0  # MediaMTX fMP4 fragment length (= max data lost on power cut)
    HLS_PART_TARGET_SECONDS: float = 4.0  # playback part length (grouped on keyframes)

    # Loops
    HEARTBEAT_INTERVAL_SECONDS: int = 5
    RECONCILE_INTERVAL_SECONDS: int = 5
    SCAN_INTERVAL_SECONDS: int = 5
    UPLOAD_INTERVAL_SECONDS: int = 3
    STATUS_INTERVAL_SECONDS: int = 10
    DELETION_INTERVAL_SECONDS: int = 60

    # Disk protection: above MAX, delete oldest recordings until below TARGET.
    DISK_MAX_USED_PERCENT: float = 95.0
    DISK_TARGET_USED_PERCENT: float = 92.0
    DISK_MIN_KEEP_HOURS: float = 1.0  # never auto-delete recordings younger than this

    @field_validator("DATA_DIR", "RECORDINGS_DIR", "MEDIAMTX_BIN")
    @classmethod
    def relative_to_base(cls, v: Path) -> Path:
        """Relative paths in .env are relative to the media_node folder, not the working directory."""
        return (v if v.is_absolute() else BASE_DIR / v).resolve()

    @property
    def api_url(self) -> str:
        return f"http://{self.PUBLIC_HOST}:{self.PORT}"

    @property
    def mediamtx_api(self) -> str:
        return f"http://127.0.0.1:{self.MEDIAMTX_API_PORT}"

    @property
    def db_path(self) -> Path:
        return self.DATA_DIR / "node_state.sqlite3"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
