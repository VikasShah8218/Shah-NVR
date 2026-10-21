"""Small read-only ONVIF Profile G client used by L3 edge-storage backfill."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from xml.sax.saxutils import escape

from lxml import etree

from app.onvif.services import OnvifDevice
from app.onvif.soap import Fault

TRC = "http://www.onvif.org/ver10/recording/wsdl"
TSE = "http://www.onvif.org/ver10/search/wsdl"
TRP = "http://www.onvif.org/ver10/replay/wsdl"
TT = "http://www.onvif.org/ver10/schema"


def _local(element: etree._Element) -> str:
    return etree.QName(element).localname


def _values(element: etree._Element, name: str) -> list[str]:
    return [e.text.strip() for e in element.iter() if _local(e) == name and e.text and e.text.strip()]


def _first(element: etree._Element, name: str) -> str | None:
    found = _values(element, name)
    return found[0] if found else None


def _time(value: str | None) -> datetime | None:
    if not value or value.startswith("1970-01-01T00:00:00"):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass(frozen=True)
class ProfileGRecording:
    token: str
    source_id: str | None
    earliest: datetime | None
    latest: datetime | None

    def as_dict(self) -> dict:
        return {
            "token": self.token,
            "source_id": self.source_id,
            "earliest": self.earliest,
            "latest": self.latest,
        }


class ProfileGClient:
    def __init__(self, device: OnvifDevice):
        self.device = device
        self.recording_url: str | None = None
        self.search_url: str | None = None
        self.replay_url: str | None = None

    async def services(self) -> None:
        found = await self.device.services()
        self.recording_url = found.get(TRC)
        self.search_url = found.get(TSE)
        self.replay_url = found.get(TRP)
        if not self.search_url or not self.replay_url:
            raise Fault("Camera does not expose ONVIF Recording Search and Replay services")

    async def _call(self, url: str, prefix: str, namespace: str, operation: str,
                    inner: str = "") -> etree._Element:
        body = f'<{prefix}:{operation} xmlns:{prefix}="{namespace}">{inner}</{prefix}:{operation}>'
        return await self.device.soap.call(url, body)

    async def summary(self) -> dict:
        if not self.search_url:
            await self.services()
        reply = await self._call(self.search_url, "tse", TSE, "GetRecordingSummary")  # type: ignore[arg-type]
        return {
            "earliest": _time(_first(reply, "DataFrom")),
            "latest": _time(_first(reply, "DataUntil")),
            "recordings": int(_first(reply, "NumberRecordings") or 0),
        }

    async def recordings(self) -> list[ProfileGRecording]:
        if not self.search_url:
            await self.services()
        tokens: list[str] = []
        if self.recording_url:
            reply = await self._call(self.recording_url, "trc", TRC, "GetRecordings")
            tokens = list(dict.fromkeys(_values(reply, "RecordingToken")))

        # Some cameras return an empty FindRecordings page while GetRecordings and
        # GetRecordingInformation work. Query both and merge instead of rejecting them.
        found = await self._call(
            self.search_url, "tse", TSE, "FindRecordings",  # type: ignore[arg-type]
            "<tse:Scope/><tse:KeepAliveTime>PT30S</tse:KeepAliveTime>",
        )
        search_token = _first(found, "SearchToken")
        if search_token:
            try:
                page = await self._call(
                    self.search_url, "tse", TSE, "GetRecordingSearchResults",  # type: ignore[arg-type]
                    f"<tse:SearchToken>{escape(search_token)}</tse:SearchToken>"
                    "<tse:MaxResults>200</tse:MaxResults><tse:WaitTime>PT10S</tse:WaitTime>",
                )
                tokens += _values(page, "RecordingToken")
            finally:
                await self._call(
                    self.search_url, "tse", TSE, "EndSearch",  # type: ignore[arg-type]
                    f"<tse:SearchToken>{escape(search_token)}</tse:SearchToken>",
                )

        out: list[ProfileGRecording] = []
        for token in dict.fromkeys(tokens):
            reply = await self._call(
                self.search_url, "tse", TSE, "GetRecordingInformation",  # type: ignore[arg-type]
                f"<tse:RecordingToken>{escape(token)}</tse:RecordingToken>",
            )
            out.append(ProfileGRecording(
                token=token,
                source_id=_first(reply, "SourceId"),
                earliest=_time(_first(reply, "EarliestRecording")),
                latest=_time(_first(reply, "LatestRecording")),
            ))
        return out

    async def replay_uri(self, recording_token: str) -> str:
        if not self.replay_url:
            await self.services()
        reply = await self._call(
            self.replay_url, "trp", TRP, "GetReplayUri",  # type: ignore[arg-type]
            "<trp:StreamSetup>"
            f'<tt:Stream xmlns:tt="{TT}">RTP-Unicast</tt:Stream>'
            f'<tt:Transport xmlns:tt="{TT}"><tt:Protocol>RTSP</tt:Protocol></tt:Transport>'
            "</trp:StreamSetup>"
            f"<trp:RecordingToken>{escape(recording_token)}</trp:RecordingToken>",
        )
        uri = _first(reply, "Uri")
        if not uri:
            raise Fault("GetReplayUri returned no URI")
        return uri


def exact_replay_uri(uri: str, start: datetime, end: datetime) -> str:
    """Constrain replay URIs used by known Tyco/Sparsh cameras to an exact UTC range.

    Generic ONVIF RTSP Range support is a later adapter. Refuse unknown URI
    formats instead of importing the wrong period under a requested timestamp.
    """
    parts = urlsplit(uri)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if "start" not in query or "stop" not in query:
        raise Fault("Camera replay URI needs generic ONVIF RTSP Range support")
    query["start"] = start.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")
    query["stop"] = end.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


__all__ = ["ProfileGClient", "ProfileGRecording", "exact_replay_uri"]
