"""Public, credential-free H2 encoder contract."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class EncoderValues(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    encoding: Literal["H264", "H265"] | None = None
    width: int | None = Field(None, gt=0)
    height: int | None = Field(None, gt=0)
    fps: float | None = Field(None, gt=0)
    bitrate_kbps: int | None = Field(None, gt=0)
    gop: int | None = Field(None, gt=0)
    quality: float | None = None
    rate_control: Literal["CBR", "VBR"] | None = None
    codec_profile: str | None = Field(None, max_length=64)


class EncoderOption(BaseModel):
    encoding: str
    resolutions: list[list[int]] = []
    fps_range: list[float] | None = None
    frame_rates: list[float] = []
    bitrate_range: list[float] | None = None
    gop_range: list[float] | None = None
    quality_range: list[float] | None = None
    codec_profiles: list[str] = []
    rate_controls: list[str] = []


class EncoderProfile(BaseModel):
    token: str
    name: str | None = None
    encoder_token: str | None = None


class EncoderState(BaseModel):
    api: str
    profile_token: str | None
    encoder_token: str | None = None
    revision: str | None = None
    current: EncoderValues | None = None
    options: list[EncoderOption] = []
    profiles: list[EncoderProfile] = []
    shared_profiles: list[str] = []
    use_count: int = 0
    warnings: list[str] = []


class EncoderWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str = Field(min_length=16, max_length=64, pattern=r"^[a-zA-Z0-9-]+$")
    revision: str = Field(min_length=64, max_length=64)
    values: EncoderValues
    acknowledge_shared: bool = False
    restore_from: str | None = Field(None, max_length=64)


class EncoderResult(BaseModel):
    outcome: Literal["verified", "mismatch", "unknown"]
    before: EncoderState
    after: EncoderState | None = None
    message: str
    recovery: dict = {}

