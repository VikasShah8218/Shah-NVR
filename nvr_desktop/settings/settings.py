"""Startup settings (from nvr_desktop/.env or environment variables).

These are only first-run defaults. Everything the user changes in the app (central URL, refresh
interval, live protocol, hardware decoding...) is stored by app/core/preferences.py (QSettings).
"""

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "Shah-NVR"
    CENTRAL_URL: str = "http://localhost:8000"
    LOG_LEVEL: str = "INFO"
    MPV_DLL_DIR: Path = BASE_DIR / "bin"
    HTTP_TIMEOUT_SECONDS: float = 10.0
    # Force the video render mode ("cpu" | "gpu"), overriding Settings in the app. Empty = use Settings.
    RENDER_MODE: str = ""

    @field_validator("MPV_DLL_DIR")
    @classmethod
    def relative_to_base(cls, v: Path) -> Path:
        return (v if v.is_absolute() else BASE_DIR / v).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
