from datetime import datetime

from pydantic import BaseModel, Field


class DiscoverIn(BaseModel):
    seconds: float = Field(3.0, ge=1, le=15)


class DiscoveredDevice(BaseModel):
    endpoint: str
    host: str
    port: int
    xaddr: str
    name: str | None = None
    hardware: str | None = None
    location: str | None = None
    mac: str | None = None
    profiles: list[str] = []  # ONVIF profiles from scopes: Streaming (= S), T, G, M ...
    interface_ip: str  # node address the reply came in on


class DeviceIn(BaseModel):
    """How to reach one device. Credentials are used for this request only, never stored on the node."""

    host: str = Field(min_length=1, max_length=255)
    port: int = Field(80, ge=1, le=65535)
    username: str = ""
    password: str = ""
    xaddr: str | None = None  # device service URL from discovery (default http://host:port/onvif/device_service)


class SnapshotIn(DeviceIn):
    uri: str


class NtpIn(DeviceIn):
    from_dhcp: bool = False
    servers: list[str] = []


class ClockOut(BaseModel):
    offset_seconds: float | None  # camera clock minus node clock
    source: str | None  # Manual / NTP
    timezone: str | None
    camera_utc: str | None


class ProfileOut(BaseModel):
    token: str
    name: str | None
    api: str  # media1 / media2
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
    rtsp: str | None  # without credentials
    snapshot: str | None


class SuggestedOut(BaseModel):
    main: str | None  # profile token
    sub: str | None


class ProbeOut(BaseModel):
    host: str
    port: int
    device_url: str
    clock: ClockOut
    info: dict  # manufacturer, model, firmwareversion, serialnumber, hardwareid
    services: list[str]  # ONVIF service namespaces the device offers
    profiles: list[ProfileOut]
    suggested: SuggestedOut


class NtpOut(BaseModel):
    from_dhcp: bool
    servers: list[str]


class NetworkOut(BaseModel):
    mac: str | None
    dhcp: bool
    ip: str | None
    prefix_length: int | None


class DeviceStateOut(BaseModel):
    """Live device page: identity, clock and read-only settings."""

    clock: ClockOut
    info: dict
    services: list[str]
    ntp: NtpOut | None
    hostname: str | None
    network: NetworkOut | None


class RebootOut(BaseModel):
    message: str


class ProfileGRecordingOut(BaseModel):
    token: str
    source_id: str | None = None
    earliest: datetime | None = None
    latest: datetime | None = None
    replay_available: bool = False


class ProfileGProbeOut(BaseModel):
    supported: bool
    recording_service: bool
    search_service: bool
    replay_service: bool
    earliest: datetime | None = None
    latest: datetime | None = None
    recordings: list[ProfileGRecordingOut]
