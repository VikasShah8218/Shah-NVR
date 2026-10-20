from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class DiscoverIn(BaseModel):
    node_id: int | None = None  # None = scan from every online node
    seconds: float = Field(3.0, ge=1, le=15)


class DiscoveredOut(BaseModel):
    endpoint: str
    host: str
    port: int
    xaddr: str
    name: str | None
    hardware: str | None
    location: str | None
    mac: str | None
    profiles: list[str]  # ONVIF profiles announced in scopes: Streaming (= S), T, G, M ...
    node_id: int  # node that found it (use it for probe / add)
    node_name: str
    camera_id: int | None  # already added as this camera
    camera_name: str | None


class DeviceIn(BaseModel):
    node_id: int | None = None
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(80, ge=1, le=65535)
    xaddr: str | None = None
    username: str = ""
    password: str = ""


class SnapshotIn(DeviceIn):
    uri: str


class ClockOut(BaseModel):
    offset_seconds: float | None  # camera clock minus node clock
    source: str | None  # Manual / NTP
    timezone: str | None
    camera_utc: str | None


class ProfileOut(BaseModel):
    token: str
    name: str | None
    api: str
    encoding: str | None
    width: int | None
    height: int | None
    fps: int | None
    bitrate_kbps: int | None
    has_audio: bool
    audio_encoder_token: str | None = None
    audio_encoding: str | None = None
    audio_codec: str | None = None
    audio_bitrate_kbps: int | None = None
    audio_sample_rate: int | None = None
    audio_channels: int | None = None
    has_ptz: bool
    rtsp: str | None
    snapshot: str | None


class SuggestedOut(BaseModel):
    main: str | None
    sub: str | None


class DeviceInfoOut(BaseModel):
    manufacturer: str | None = None
    model: str | None = None
    firmwareversion: str | None = None
    serialnumber: str | None = None
    hardwareid: str | None = None


class ProbeOut(BaseModel):
    node_id: int
    host: str
    port: int
    device_url: str
    clock: ClockOut
    info: DeviceInfoOut
    services: list[str]
    profiles: list[ProfileOut]
    suggested: SuggestedOut
    camera_id: int | None  # already added as this camera


class StreamPick(BaseModel):
    profile: str = Field(pattern=r"^[a-z0-9_-]{1,32}$", examples=["main"])  # our stream name
    token: str  # ONVIF profile token
    record: bool = True


class OnvifCameraCreate(DeviceIn):
    name: str | None = Field(default=None, max_length=128)  # default "<model> (<ip>)"
    description: str | None = None
    enabled: bool = True
    retention_days: int | None = Field(default=None, ge=1, le=3650)  # omitted = default, null = until full
    # None = the suggestion: main (recorded) + sub (live only) when the camera has a smaller profile
    streams: list[StreamPick] | None = None
    allow_duplicate: bool = False

    @field_validator("streams")
    @classmethod
    def unique(cls, v: list[StreamPick] | None) -> list[StreamPick] | None:
        if v is not None:
            if not v:
                raise ValueError("pick at least one stream")
            if len({s.profile for s in v}) != len(v):
                raise ValueError("stream profiles must be unique")
        return v


class NtpOut(BaseModel):
    from_dhcp: bool
    servers: list[str]


class NetworkOut(BaseModel):
    mac: str | None
    dhcp: bool
    ip: str | None
    prefix_length: int | None


class DeviceStateOut(BaseModel):
    camera_id: int
    node_id: int
    host: str
    port: int
    clock: ClockOut
    info: DeviceInfoOut
    services: list[str]
    ntp: NtpOut | None
    hostname: str | None
    network: NetworkOut | None
    checked_at: datetime


class NtpIn(BaseModel):
    from_dhcp: bool = False
    servers: list[str] = []


class MessageOut(BaseModel):
    message: str
