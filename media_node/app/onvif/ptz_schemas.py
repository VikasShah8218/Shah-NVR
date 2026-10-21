"""H3 first release: credential-free PTZ contract (kept identical in both services)."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class PtzCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    session_id: str = Field(min_length=16, max_length=64)
    sequence: int = Field(ge=1, le=2147483647)
    action: Literal["move", "stop", "refresh", "preset_save", "preset_goto", "preset_remove", "home_goto", "home_set"]
    pan: float = Field(0, ge=-0.5, le=0.5)
    tilt: float = Field(0, ge=-0.5, le=0.5)
    zoom: float = Field(0, ge=-0.5, le=0.5)
    preset_token: str | None = Field(None, min_length=1, max_length=128)
    preset_name: str | None = Field(None, min_length=1, max_length=64)
    confirm: bool = False

    @model_validator(mode="after")
    def valid_action(self):
        if self.action != "move" and any((self.pan, self.tilt, self.zoom)):
            raise ValueError("Velocities only apply to move")
        if self.action == "move" and not any((self.pan, self.tilt, self.zoom)):
            raise ValueError("Use Stop for a zero velocity")
        if self.action in ("preset_goto", "preset_remove") and not self.preset_token:
            raise ValueError("Preset token required")
        if self.action == "preset_save" and not (self.preset_name or "").strip():
            raise ValueError("Preset name required")
        if self.action in ("preset_remove", "home_set") and not self.confirm:
            raise ValueError("Explicit confirmation required")
        return self


class PtzStatus(BaseModel):
    pan: float | None = None
    tilt: float | None = None
    zoom: float | None = None
    pan_tilt_state: str | None = None
    zoom_state: str | None = None
    position_valid: bool = False


class PtzPreset(BaseModel):
    token: str
    name: str


class PtzCapabilities(BaseModel):
    pan_tilt: bool = False
    zoom: bool = False
    presets: bool = False
    home: bool = False
    home_set: bool = False
    camera_timeout_seconds: float | None = None


class PtzState(BaseModel):
    session_id: str
    expires_in_seconds: int = 120
    capabilities: PtzCapabilities
    status: PtzStatus
    presets: list[PtzPreset] = []
    warnings: list[str] = []


class PtzResult(BaseModel):
    message: str
    status: PtzStatus | None = None
    presets: list[PtzPreset] | None = None

