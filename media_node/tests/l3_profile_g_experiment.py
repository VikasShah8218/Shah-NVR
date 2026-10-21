"""Read-only Profile G experiment against one camera assigned to this media node.

Run from the repository root on the media-node host:

    python3 media_node/tests/l3_profile_g_experiment.py

The script intentionally takes no command-line arguments. Change the constants
below for a different node/camera. Credentials are obtained from the node's
existing assignment and are never printed.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit
from xml.sax.saxutils import escape

import httpx
from lxml import etree


NODE_API = "http://127.0.0.1:7100"
CAMERA_ID = 9
SOAP_TIMEOUT_SECONDS = 20.0
MAX_RESULTS = 100
VERIFY_REPLAY_MEDIA = True
REPLAY_SAMPLE_SECONDS = 8

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "media_node"))

from app.onvif.services import OnvifDevice  # noqa: E402
from app.recordings.utils import index_fmp4  # noqa: E402


TRC = "http://www.onvif.org/ver10/recording/wsdl"
TSE = "http://www.onvif.org/ver10/search/wsdl"
TRP = "http://www.onvif.org/ver10/replay/wsdl"
TT = "http://www.onvif.org/ver10/schema"


def local_name(element: etree._Element) -> str:
    return etree.QName(element).localname


def values(element: etree._Element, name: str) -> list[str]:
    return [e.text.strip() for e in element.iter() if local_name(e) == name and e.text and e.text.strip()]


def first(element: etree._Element, name: str) -> str | None:
    found = values(element, name)
    return found[0] if found else None


def redact_uri(uri: str | None) -> str:
    if not uri:
        return "<missing>"
    p = urlsplit(uri)
    host = p.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    if p.port:
        host += f":{p.port}"
    return p._replace(netloc=host).geturl()


def authenticated_uri(uri: str, username: str, password: str) -> str:
    p = urlsplit(uri)
    host = p.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    if p.port:
        host += f":{p.port}"
    credentials = f"{quote(username, safe='')}:{quote(password, safe='')}@" if username else ""
    return p._replace(netloc=f"{credentials}{host}").geturl()


def verify_replay_media(uri: str, username: str, password: str) -> None:
    """Capture a short replay sample with codec copy and prove our fMP4 indexer accepts it."""
    with tempfile.TemporaryDirectory(prefix="shah-l3-") as folder:
        output = Path(folder) / "sample.mp4"
        base = [
            "ffmpeg", "-hide_banner", "-loglevel", "warning", "-y",
            "-rtsp_transport", "tcp", "-timeout", "15000000",
            "-i", authenticated_uri(uri, username, password),
            "-t", str(REPLAY_SAMPLE_SECONDS), "-map", "0:v:0",
        ]
        output_options = [
            "-c", "copy", "-movflags", "frag_keyframe+empty_moov+default_base_moof",
            "-frag_duration", "4000000", str(output),
        ]

        def capture(include_audio: bool) -> subprocess.CompletedProcess[str]:
            command = base + (["-map", "0:a?"] if include_audio else []) + output_options
            return subprocess.run(command, capture_output=True, text=True, timeout=40, check=False)

        try:
            result = capture(include_audio=True)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("replay sample timed out") from exc
        audio_omitted = False
        if result.returncode != 0 and "codec not currently supported in container" in result.stderr:
            audio_omitted = True
            print("[WARN] Replay audio cannot be copied into standard MP4; retrying the sample with video only")
            try:
                result = capture(include_audio=False)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("video-only replay sample timed out") from exc
        if result.returncode != 0 or not output.exists() or output.stat().st_size == 0:
            safe = (result.stderr or "ffmpeg failed").replace(password, "<hidden>").replace(username, "<user>")
            raise RuntimeError(f"replay sample failed: {safe[-400:].strip()}")
        indexed = index_fmp4(output, 4.0)
        print(
            "[PASS] Replay media captured and indexed:",
            f"bytes={indexed.size_bytes}",
            f"duration={indexed.duration_ms / 1000:.3f}s",
            f"video={indexed.codec}",
            f"audio={'omitted' if audio_omitted else (indexed.audio_codec or 'none')}",
            f"parts={len(indexed.parts)}",
        )


async def assignment() -> tuple[dict, str, str]:
    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.get(f"{NODE_API}/api/v1/assignments")
        response.raise_for_status()
        cameras = response.json()
    camera = next((item for item in cameras if item.get("camera_id") == CAMERA_ID), None)
    if camera is None:
        raise RuntimeError(f"camera {CAMERA_ID} is not assigned to this node")
    stream = next((item for item in camera.get("streams", []) if item.get("source_url")), None)
    if stream is None:
        raise RuntimeError("the assignment has no credential-bearing source URL")
    parsed = urlsplit(stream["source_url"])
    return camera, unquote(parsed.username or ""), unquote(parsed.password or "")


async def soap_call(device: OnvifDevice, url: str, prefix: str, namespace: str, operation: str,
                    inner: str = "") -> etree._Element:
    body = f'<{prefix}:{operation} xmlns:{prefix}="{namespace}">{inner}</{prefix}:{operation}>'
    reply = await device.soap.call(url, body)
    print(f"[PASS] {operation}")
    return reply


def print_recording_result(result: etree._Element) -> None:
    token = first(result, "RecordingToken") or "<missing>"
    earliest = first(result, "EarliestRecording") or first(result, "DataFrom") or "unknown"
    latest = first(result, "LatestRecording") or first(result, "DataUntil") or "unknown"
    source = first(result, "SourceId") or first(result, "Name") or "unknown"
    print(f"  token={token} source={source} range={earliest} .. {latest}")


async def main() -> None:
    print("Shah-NVR L3 Profile G read-only experiment")
    print(f"Node API: {NODE_API}; camera ID: {CAMERA_ID}")
    camera, username, password = await assignment()
    host = camera.get("onvif_host")
    port = int(camera.get("onvif_port") or 80)
    if not host:
        raise RuntimeError("assigned camera has no ONVIF host")
    print(f"Camera: {camera.get('camera_name')} at {host}:{port}; credentials: <hidden>")

    async with OnvifDevice(host, port, username, password, timeout=SOAP_TIMEOUT_SECONDS) as device:
        clock = await device.clock()
        print(f"[PASS] Camera clock; offset={clock.get('offset_seconds')} seconds")
        services = await device.services()
        recording_url = services.get(TRC)
        search_url = services.get(TSE)
        replay_url = services.get(TRP)
        for name, url in (("Recording", recording_url), ("Search", search_url), ("Replay", replay_url)):
            print(f"{'[PASS]' if url else '[FAIL]'} {name} service: {redact_uri(url)}")
        if not search_url or not replay_url:
            raise RuntimeError("camera does not expose the mandatory Profile G search/replay services")

        summary = await soap_call(device, search_url, "tse", TSE, "GetRecordingSummary")
        print(
            "  summary:",
            f"from={first(summary, 'DataFrom')}",
            f"until={first(summary, 'DataUntil')}",
            f"recordings={first(summary, 'NumberRecordings')}",
        )

        recording_tokens: list[str] = []
        if recording_url:
            listing = await soap_call(device, recording_url, "trc", TRC, "GetRecordings")
            recording_tokens = list(dict.fromkeys(values(listing, "RecordingToken")))
            print(f"  Recording service returned {len(recording_tokens)} token(s)")

        found = await soap_call(
            device,
            search_url,
            "tse",
            TSE,
            "FindRecordings",
            '<tse:Scope/><tse:KeepAliveTime>PT30S</tse:KeepAliveTime>',
        )
        search_token = first(found, "SearchToken")
        if not search_token:
            raise RuntimeError("FindRecordings returned no SearchToken")
        try:
            page = await soap_call(
                device,
                search_url,
                "tse",
                TSE,
                "GetRecordingSearchResults",
                f"<tse:SearchToken>{search_token}</tse:SearchToken>"
                f"<tse:MaxResults>{MAX_RESULTS}</tse:MaxResults>"
                "<tse:WaitTime>PT10S</tse:WaitTime>",
            )
            results = [e for e in page.iter() if local_name(e) == "Result"]
            searched_tokens = list(dict.fromkeys(values(page, "RecordingToken")))
            recording_tokens = searched_tokens or recording_tokens
            print(f"  Search returned {len(results)} result(s), state={first(page, 'SearchState')}")
            for result in results:
                print_recording_result(result)
        finally:
            try:
                await soap_call(
                    device,
                    search_url,
                    "tse",
                    TSE,
                    "EndSearch",
                    f"<tse:SearchToken>{search_token}</tse:SearchToken>",
                )
            except Exception as exc:  # cleanup failure must remain visible without hiding the main result
                print(f"[WARN] EndSearch failed: {type(exc).__name__}: {exc}")

        if not recording_tokens:
            raise RuntimeError("camera returned no recordings; verify its SD-card recording configuration")

        print("\nRecording details and replay URIs")
        for token in recording_tokens:
            escaped = escape(token)
            info = await soap_call(
                device,
                search_url,
                "tse",
                TSE,
                "GetRecordingInformation",
                f"<tse:RecordingToken>{escaped}</tse:RecordingToken>",
            )
            print_recording_result(info)
            when = first(info, "EarliestRecording") or datetime.now(timezone.utc).isoformat()
            attributes = await soap_call(
                device,
                search_url,
                "tse",
                TSE,
                "GetMediaAttributes",
                f"<tse:RecordingTokens>{escaped}</tse:RecordingTokens><tse:Time>{when}</tse:Time>",
            )
            print(
                "  tracks:",
                f"video={values(attributes, 'VideoAttributes')}",
                f"audio={values(attributes, 'AudioAttributes')}",
                f"tokens={values(attributes, 'TrackToken')}",
            )
            replay = await soap_call(
                device,
                replay_url,
                "trp",
                TRP,
                "GetReplayUri",
                "<trp:StreamSetup>"
                f'<tt:Stream xmlns:tt="{TT}">RTP-Unicast</tt:Stream>'
                f'<tt:Transport xmlns:tt="{TT}"><tt:Protocol>RTSP</tt:Protocol></tt:Transport>'
                "</trp:StreamSetup>"
                f"<trp:RecordingToken>{escaped}</trp:RecordingToken>",
            )
            replay_uri = first(replay, "Uri")
            print(f"  replay={redact_uri(replay_uri)}")
            if VERIFY_REPLAY_MEDIA and replay_uri:
                await asyncio.to_thread(verify_replay_media, replay_uri, username, password)

    print("\nRESULT: Profile G search and replay URI discovery PASSED")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"\nRESULT: FAILED: {type(exc).__name__}: {exc}")
        raise SystemExit(1)
