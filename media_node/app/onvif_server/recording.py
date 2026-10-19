"""Read-only ONVIF Recording and Search services backed by local_segments."""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from lxml import etree
from tortoise.expressions import Q
from tortoise.functions import Count, Max, Min

from app.node.utils import runtime
from app.onvif_server.soap import SOAP, TT, SoapFault, action, envelope
from app.recordings.models import LocalSegment, OnvifRecordingExport
from app.storage.services import storage

TRC = "http://www.onvif.org/ver10/recording/wsdl"
TSE = "http://www.onvif.org/ver10/search/wsdl"
TRP = "http://www.onvif.org/ver10/replay/wsdl"
TOKEN_RE = re.compile(r"^recording_cam_(\d+)_(.+)$")
SEARCH_TTL_SECONDS = 120.0
MAX_SEARCH_SESSIONS = 64
MAX_RESULTS = 200


@dataclass
class Recording:
    token: str
    camera_id: int
    profile: str
    name: str
    codec: str | None
    earliest: datetime
    latest: datetime
    segments: int


@dataclass
class SearchSession:
    items: list[Recording]
    cursor: int
    expires_at: float


_searches: dict[str, SearchSession] = {}


def recording_token(camera_id: int, profile: str) -> str:
    return f"recording_cam_{camera_id}_{profile}"


def track_token(camera_id: int, profile: str) -> str:
    return f"track_cam_{camera_id}_{profile}_video"


def _utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _text(parent: etree._Element, namespace: str, name: str, value: object) -> etree._Element:
    child = etree.SubElement(parent, etree.QName(namespace, name))
    child.text = str(value).lower() if isinstance(value, bool) else str(value)
    return child


def _request_text(operation: etree._Element, name: str) -> str | None:
    found = operation.xpath(f".//*[local-name()='{name}']/text()")
    return str(found[0]).strip() if found else None


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)
    except ValueError as exc:
        raise SoapFault("ter:InvalidArgVal", f"Invalid UTC date/time: {value}") from exc


async def recordings(start: datetime | None = None, end: datetime | None = None) -> list[Recording]:
    query = LocalSegment.all().order_by("start_time")
    if start is not None:
        query = query.filter(end_time__gte=start)
    if end is not None:
        query = query.filter(start_time__lte=end)
    # PENDING is accepted during startup; ERROR/UNAVAILABLE volumes are hidden.
    keys = [key for key, volume in storage.volumes.items() if volume.state not in ("ERROR", "UNAVAILABLE")]
    if not keys:
        return []
    volume_filter = Q(volume_id__in=[key for key in keys if key is not None])
    if None in keys:
        volume_filter |= Q(volume_id__isnull=True)
    rows = await (
        query.filter(volume_filter)
        .group_by("camera_id", "profile")
        .annotate(earliest=Min("start_time"), latest=Max("end_time"), segments=Count("id"), codec=Max("codec"))
        .values("camera_id", "profile", "earliest", "latest", "segments", "codec")
    )

    current_names = {
        camera_id: assignment.get("camera_name") or f"Camera {camera_id}"
        for camera_id, assignment in runtime.assignments.items()
    }
    output: list[Recording] = []
    for row in rows:
        camera_id, profile = int(row["camera_id"]), str(row["profile"])
        token = recording_token(camera_id, profile)
        export = await OnvifRecordingExport.get_or_none(token=token)
        display_name = current_names.get(camera_id) or (export.display_name if export else f"Camera {camera_id}")
        codec = row["codec"]
        if export is None or export.display_name != display_name or export.codec != codec:
            await OnvifRecordingExport.update_or_create(
                token=token,
                defaults={
                    "camera_id": camera_id,
                    "profile": profile,
                    "display_name": display_name,
                    "codec": codec,
                },
            )
        output.append(Recording(
            token=token,
            camera_id=camera_id,
            profile=profile,
            name=f"{display_name} - {profile}",
            codec=codec,
            earliest=row["earliest"],
            latest=row["latest"],
            segments=int(row["segments"]),
        ))
    return sorted(output, key=lambda item: (item.camera_id, item.profile))


def _recording_configuration(parent: etree._Element, item: Recording) -> None:
    config = etree.SubElement(parent, etree.QName(TRC, "Configuration"))
    source = etree.SubElement(config, etree.QName(TT, "Source"))
    _text(source, TT, "SourceId", f"source_cam_{item.camera_id}")
    _text(source, TT, "Name", item.name)
    _text(source, TT, "Location", runtime.onvif_server_config.get("location") or "")
    _text(source, TT, "Description", f"Shah-NVR camera {item.camera_id} {item.profile}")
    _text(source, TT, "Address", f"shahnvr://camera/{item.camera_id}/{item.profile}")
    _text(config, TT, "Content", item.name)
    _text(config, TT, "MaximumRetentionTime", "PT0S")


def _recording_item(parent: etree._Element, item: Recording) -> None:
    node = etree.SubElement(parent, etree.QName(TRC, "RecordingItem"))
    _text(node, TRC, "RecordingToken", item.token)
    _recording_configuration(node, item)
    tracks = etree.SubElement(node, etree.QName(TRC, "Tracks"))
    track = etree.SubElement(tracks, etree.QName(TRC, "Track"))
    _text(track, TRC, "TrackToken", track_token(item.camera_id, item.profile))
    config = etree.SubElement(track, etree.QName(TRC, "Configuration"))
    _text(config, TT, "TrackType", "Video")
    _text(config, TT, "Description", item.codec or "Video")


def _track_information(parent: etree._Element, item: Recording) -> None:
    _text(parent, TT, "TrackToken", track_token(item.camera_id, item.profile))
    _text(parent, TT, "TrackType", "Video")
    _text(parent, TT, "Description", item.codec or "Video")
    _text(parent, TT, "DataFrom", _utc(item.earliest))
    _text(parent, TT, "DataTo", _utc(item.latest))


def _recording_information(parent: etree._Element, item: Recording) -> None:
    result = etree.SubElement(parent, etree.QName(TT, "RecordingInformation"))
    _text(result, TT, "RecordingToken", item.token)
    source = etree.SubElement(result, etree.QName(TT, "Source"))
    _text(source, TT, "SourceId", f"source_cam_{item.camera_id}")
    _text(source, TT, "Name", item.name)
    _text(source, TT, "Location", runtime.onvif_server_config.get("location") or "")
    _text(source, TT, "Description", f"{item.segments} local recording segment(s)")
    _text(source, TT, "Address", f"shahnvr://camera/{item.camera_id}/{item.profile}")
    _text(result, TT, "EarliestRecording", _utc(item.earliest))
    _text(result, TT, "LatestRecording", _utc(item.latest))
    _text(result, TT, "Content", item.name)
    track = etree.SubElement(result, etree.QName(TT, "Track"))
    _track_information(track, item)
    _text(result, TT, "RecordingStatus", "Recording")


def _cleanup_searches() -> None:
    now = time.monotonic()
    for token, session in list(_searches.items()):
        if session.expires_at <= now:
            _searches.pop(token, None)


def _search(token: str | None) -> SearchSession:
    _cleanup_searches()
    session = _searches.get(token or "")
    if session is None:
        raise SoapFault("ter:InvalidToken", "Unknown or expired search token")
    session.expires_at = time.monotonic() + SEARCH_TTL_SECONDS
    return session


async def _recording_service(operation: str, request: etree._Element) -> etree._Element:
    items = await recordings()
    if operation == "GetServiceCapabilities":
        out = etree.Element(etree.QName(TRC, "GetServiceCapabilitiesResponse"))
        caps = etree.SubElement(out, etree.QName(TRC, "Capabilities"))
        caps.set("DynamicRecordings", "false")
        caps.set("DynamicTracks", "false")
        caps.set("Encoding", "H264 H265")
        return out
    if operation == "GetRecordings":
        out = etree.Element(etree.QName(TRC, "GetRecordingsResponse"))
        for item in items:
            _recording_item(out, item)
        return out
    if operation == "GetRecordingConfiguration":
        token = _request_text(request, "RecordingToken")
        item = next((candidate for candidate in items if candidate.token == token), None)
        if item is None:
            raise SoapFault("ter:InvalidToken", "Unknown recording token")
        out = etree.Element(etree.QName(TRC, "GetRecordingConfigurationResponse"))
        _recording_configuration(out, item)
        return out
    raise SoapFault("ter:ActionNotSupported", f"Recording action {operation} is not supported")


async def _search_service(operation: str, request: etree._Element) -> etree._Element:
    if operation == "GetServiceCapabilities":
        out = etree.Element(etree.QName(TSE, "GetServiceCapabilitiesResponse"))
        caps = etree.SubElement(out, etree.QName(TSE, "Capabilities"))
        caps.set("MetadataSearch", "false")
        return out
    if operation == "GetRecordingSummary":
        items = await recordings()
        out = etree.Element(etree.QName(TSE, "GetRecordingSummaryResponse"))
        summary = etree.SubElement(out, etree.QName(TSE, "Summary"))
        now = datetime.now(timezone.utc)
        _text(summary, TT, "DataFrom", _utc(min((item.earliest for item in items), default=now)))
        _text(summary, TT, "DataUntil", _utc(max((item.latest for item in items), default=now)))
        _text(summary, TT, "NumberRecordings", len(items))
        return out
    if operation == "GetRecordingInformation":
        items = await recordings()
        token = _request_text(request, "RecordingToken")
        item = next((candidate for candidate in items if candidate.token == token), None)
        if item is None:
            raise SoapFault("ter:InvalidToken", "Unknown recording token")
        out = etree.Element(etree.QName(TSE, "GetRecordingInformationResponse"))
        _recording_information(out, item)
        return out
    if operation == "GetMediaAttributes":
        items = await recordings()
        requested = set(request.xpath(".//*[local-name()='RecordingTokens']/text()"))
        point = _parse_time(_request_text(request, "Time"))
        selected = [item for item in items if not requested or item.token in requested]
        out = etree.Element(etree.QName(TSE, "GetMediaAttributesResponse"))
        for item in selected:
            attributes = etree.SubElement(out, etree.QName(TSE, "MediaAttributes"))
            _text(attributes, TT, "RecordingToken", item.token)
            track_attributes = etree.SubElement(attributes, etree.QName(TT, "TrackAttributes"))
            track_info = etree.SubElement(track_attributes, etree.QName(TT, "TrackInformation"))
            _track_information(track_info, item)
            # Width/frame rate are not persisted in local_segments, so do not invent
            # a VideoAttributes structure with false values.
            valid_at = point if point and item.earliest <= point <= item.latest else item.earliest
            _text(attributes, TT, "From", _utc(valid_at))
            _text(attributes, TT, "Until", _utc(valid_at))
        return out
    if operation == "FindRecordings":
        _cleanup_searches()
        if len(_searches) >= MAX_SEARCH_SESSIONS:
            raise SoapFault("ter:MaxLimit", "Too many active recording searches")
        start = _parse_time(_request_text(request, "EarliestRecording"))
        end = _parse_time(_request_text(request, "LatestRecording"))
        items = await recordings(start, end)
        requested = _request_text(request, "RecordingToken")
        if requested:
            items = [item for item in items if item.token == requested]
        try:
            max_matches = int(_request_text(request, "MaxMatches") or len(items))
        except ValueError as exc:
            raise SoapFault("ter:InvalidArgVal", "MaxMatches must be an integer") from exc
        items = items[:max(0, max_matches)]
        token = uuid.uuid4().hex
        _searches[token] = SearchSession(items, 0, time.monotonic() + SEARCH_TTL_SECONDS)
        out = etree.Element(etree.QName(TSE, "FindRecordingsResponse"))
        _text(out, TSE, "SearchToken", token)
        return out
    if operation == "GetRecordingSearchResults":
        session = _search(_request_text(request, "SearchToken"))
        try:
            maximum = int(_request_text(request, "MaxResults") or 50)
        except ValueError as exc:
            raise SoapFault("ter:InvalidArgVal", "MaxResults must be an integer") from exc
        maximum = max(1, min(maximum, MAX_RESULTS))
        page = session.items[session.cursor:session.cursor + maximum]
        session.cursor += len(page)
        out = etree.Element(etree.QName(TSE, "GetRecordingSearchResultsResponse"))
        result_list = etree.SubElement(out, etree.QName(TSE, "ResultList"))
        _text(result_list, TT, "SearchState", "Completed" if session.cursor >= len(session.items) else "Searching")
        for item in page:
            _recording_information(result_list, item)
        return out
    if operation == "KeepAliveSearch":
        _search(_request_text(request, "SearchToken"))
        return etree.Element(etree.QName(TSE, "KeepAliveSearchResponse"))
    if operation == "EndSearch":
        token = _request_text(request, "SearchToken")
        if not token or _searches.pop(token, None) is None:
            raise SoapFault("ter:InvalidToken", "Unknown or expired search token")
        return etree.Element(etree.QName(TSE, "EndSearchResponse"))
    raise SoapFault("ter:ActionNotSupported", f"Search action {operation} is not supported")


async def dispatch_recording(service: str, root: etree._Element) -> bytes:
    operation, request = action(root)
    if service == "recording":
        response = await _recording_service(operation, request)
    elif service == "search":
        response = await _search_service(operation, request)
    else:
        raise SoapFault("ter:ActionNotSupported", "Replay is not available yet")
    return envelope(response)
