from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server
    APP_NAME: str = "Shah-NVR Central Manager"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"
    # Browser origins allowed to call this API (comma-separated, "*" = any). Needed by nvr_client.
    CORS_ORIGINS: str = "*"

    # Database (PostgreSQL)
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_USER: str = "postgres"
    DB_PASSWORD: str = ""
    DB_NAME: str = "nvr"
    # Optional full override, e.g. "sqlite://./dev.sqlite3" for quick local tests.
    DATABASE_URL: str | None = None

    # Node health / ownership
    HEARTBEAT_TIMEOUT_SECONDS: int = 15
    LEASE_TTL_SECONDS: int = 30
    FAILOVER_GRACE_SECONDS: int = 10

    # Background loops
    SCHEDULER_INTERVAL_SECONDS: int = 5
    HEALTH_INTERVAL_SECONDS: int = 5
    RETENTION_INTERVAL_SECONDS: int = 600
    BACKFILL_SCHEDULER_INTERVAL_SECONDS: int = 60
    BACKFILL_PROBE_INTERVAL_SECONDS: int = 300
    BACKFILL_MAX_LOOKBACK_HOURS: int = 24
    MAX_MOVES_PER_CYCLE: int = 20
    STREAM_STATUS_STALE_SECONDS: int = 60

    # Recording / playback
    DEFAULT_RETENTION_DAYS: int = 7
    PLAYBACK_GAP_TOLERANCE_SECONDS: float = 2.0
    PLAYBACK_MAX_HOURS: int = 24

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def db_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"postgres://{quote(self.DB_USER)}:{quote(self.DB_PASSWORD)}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
