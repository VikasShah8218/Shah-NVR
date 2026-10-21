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
    # Host/IP put into every client link (live, playback, downloads). "auto" = this PC's LAN IP
    # (utilities/netaddr.py). VPN/virtual addresses are never used, even if written here.
    PUBLIC_HOST: str = "auto"
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
    # Used only to make browser-compatible AAC for recorded listening. Video is never transcoded.
    FFMPEG_BIN: str = "ffmpeg"
    MEDIAMTX_API_PORT: int = 9997
    MEDIAMTX_METRICS_PORT: int = 9998
    RTSP_PORT: int = 8554
    RTP_PORT: int = 8000
    RTCP_PORT: int = 8001
    HLS_PORT: int = 8888
    HLS_VARIANT: str = "lowLatency"  # lowLatency | fmp4 | mpegts
    WEBRTC_PORT: int = 8889
    WEBRTC_UDP_PORT: int = 8189

    # H5 virtual ONVIF NVR. Desired enable/name come from central; the secret stays on this node.
    ONVIF_AUTH_MODE: str = "local"
    ONVIF_SERVER_USERNAME: str = ""
    ONVIF_SERVER_PASSWORD: str = ""
    ONVIF_RTSP_PORT: int = 8555
    ONVIF_AUTH_NONCE_SECONDS: int = 300

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
    ONVIF_CHECK_INTERVAL_SECONDS: float = 300  # camera reachable + clock offset (no login, see app/onvif/health.py)
    BACKFILL_INTERVAL_SECONDS: float = 5

    # Disk protection: above MAX, delete oldest recordings until below TARGET.
    STORAGE_CHECK_INTERVAL_SECONDS: float = 10
    ADDRESS_CHECK_INTERVAL_SECONDS: float = 120  # re-detect the LAN IP (PUBLIC_HOST=auto)  # health / space of every storage volume
    DISK_MAX_USED_PERCENT: float = 95.0
    DISK_TARGET_USED_PERCENT: float = 92.0
    DISK_MIN_KEEP_HOURS: float = 1.0  # never auto-delete recordings younger than this

    @field_validator("DATA_DIR", "RECORDINGS_DIR", "MEDIAMTX_BIN")
    @classmethod
    def relative_to_base(cls, v: Path) -> Path:
        """Relative paths in .env are relative to the media_node folder, not the working directory."""
        return (v if v.is_absolute() else BASE_DIR / v).resolve()

    @property
    def public_host(self) -> str:
        from utilities.netaddr import public_host

        return public_host(self.PUBLIC_HOST)

    @property
    def api_url(self) -> str:
        return f"http://{self.public_host}:{self.PORT}"

    @property
    def mediamtx_api(self) -> str:
        return f"http://127.0.0.1:{self.MEDIAMTX_API_PORT}"

    @property
    def db_path(self) -> Path:
        return self.DATA_DIR / "node_state.sqlite3"

    @property
    def onvif_credentials_configured(self) -> bool:
        return bool(self.ONVIF_SERVER_USERNAME and self.ONVIF_SERVER_PASSWORD)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
