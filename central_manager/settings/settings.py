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
    EXPORT_MAX_HOURS: int = 4
    EXPORT_FILE_TTL_HOURS: int = 24

    # ---------------- Authentication (docs/AUTH_INTEGRATION_PLAN.md)
    # Off = open API like before (every request runs as a built-in local admin). On = a valid Auth Server
    # access token for app AUTH_APP_KEY is required on every API call.
    AUTH_ENABLED: bool = False
    AUTH_SERVER: str = "http://localhost:5082"
    AUTH_APP_KEY: str = "SNVR"
    AUTH_CLIENT_ID: str = "SNVR"
    AUTH_CLIENT_SECRET: str = ""  # downstream service secret (never commit it)
    AUTH_KEY: str = ""  # Auth Server user-token signing secret (HS256); never logged
    AUTH_STATE_BACKEND: str = "memory"  # memory (one central process) | redis (later)
    AUTH_FAIL_MODE: str = "closed"  # closed: unknown token version = rejected | open: allowed (documented risk)
    AUTH_USERS_REFRESH_SECONDS: int = 600
    AUTH_LEEWAY_SECONDS: int = 30
    AUTH_HTTP_TIMEOUT_SECONDS: float = 10.0
    # Which Auth Server (docs/AUTH_V2_PLAN.md). Switch with this line and a restart; both stay supported until
    # every site runs on oidc.
    #   legacy: the old Authentication-Server (AUTH_SERVER, AUTH_KEY HS256, login proxied by central)
    #   oidc:   the new Auth Server through auth_sdk (ES256 + JWKS, events; clients sign in on its login page)
    AUTH_PROVIDER: str = "legacy"
    AUTH_ISSUER: str = "http://localhost:5181"  # exactly the new Auth Server's ISSUER
    AUTH_API_URL: str = ""  # where central reaches it when that differs from the issuer (empty = issuer)
    AUTH_OIDC_CLIENT_ID: str = "snvr-a"  # confidential server client: events.read permissions.read users.read
    AUTH_OIDC_CLIENT_SECRET: str = ""  # never commit it
    AUTH_WEB_CLIENT_ID: str = "snvr-web"  # public clients, handed to the apps by GET /auth/config
    AUTH_DESKTOP_CLIENT_ID: str = "snvr-desktop"
    AUTH_CLIENT_SCOPES: str = "openid profile email"
    AUTH_STATE_PATH: str = "./data/auth-state.json"  # SDK keys + revocations, so a restart works during an outage
    AUTH_INSTANCE_ID: str = ""  # name on the Auth Server's Downstream Sync page (empty = saved / random)
    AUTH_MAX_STALENESS_SECONDS: int = 0  # 0 = keep serving through an outage (token lifetime is the limit)
    AUDIT_RETENTION_DAYS: int = 365

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
