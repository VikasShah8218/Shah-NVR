"""Authenticated RTSP/TCP proxy for H5 live streams; it never decodes video."""

from __future__ import annotations

import asyncio
import logging
import re
from contextlib import suppress
from urllib.parse import urlsplit

from app.node.utils import runtime
from app.onvif_server.auth import digest_challenge, verify_digest
from settings.settings import settings

logger = logging.getLogger("node.onvif-rtsp")
_REQUEST = re.compile(rb"^([A-Z_]+)\s+(\S+)\s+(RTSP/\d\.\d)\r\n")


def _headers(block: bytes) -> dict[str, str]:
    result = {}
    for line in block.split(b"\r\n")[1:]:
        if b":" in line:
            key, value = line.split(b":", 1)
            result[key.decode("latin1").lower()] = value.decode("latin1").strip()
    return result


async def _message(reader: asyncio.StreamReader) -> tuple[bytes, bool]:
    first = await reader.readexactly(1)
    if first == b"$":
        header = first + await reader.readexactly(3)
        size = int.from_bytes(header[2:4], "big")
        return header + await reader.readexactly(size), True
    head = first + await reader.readuntil(b"\r\n\r\n")
    if len(head) > 65536:
        raise ValueError("RTSP headers too large")
    length = int(_headers(head).get("content-length", "0"))
    if length > 1024 * 1024:
        raise ValueError("RTSP body too large")
    return head + (await reader.readexactly(length) if length else b""), False


def _allowed(path: str) -> bool:
    parts = path.strip("/").split("/")
    if len(parts) < 3 or parts[0] != "live" or not parts[1].startswith("cam-"):
        return False
    try:
        camera_id = int(parts[1][4:])
    except ValueError:
        return False
    assignment = runtime.assignments.get(camera_id)
    if not assignment or not assignment.get("expose_via_onvif", True):
        return False
    return any(stream.get("profile") == parts[2] for stream in assignment.get("streams", []))


def _reply(code: int, reason: str, cseq: str, headers: dict[str, str] | None = None) -> bytes:
    lines = [f"RTSP/1.0 {code} {reason}", f"CSeq: {cseq}"]
    lines.extend(f"{k}: {v}" for k, v in (headers or {}).items())
    return ("\r\n".join(lines) + "\r\n\r\n").encode()


def _rewrite_request(message: bytes, public_uri: str) -> tuple[bytes, str, str]:
    match = _REQUEST.match(message)
    if not match:
        raise ValueError("Malformed RTSP request")
    method, raw_uri, version = (part.decode("latin1") for part in match.groups())
    uri = urlsplit(raw_uri)
    path = uri.path if uri.scheme else raw_uri
    if not _allowed(path):
        raise PermissionError("RTSP path is not exposed")
    upstream_path = "/" + path.strip("/").removeprefix("live/")
    suffix = ("?" + uri.query) if uri.query else ""
    upstream_uri = f"rtsp://127.0.0.1:{settings.RTSP_PORT}{upstream_path}{suffix}"
    lines = message.split(b"\r\n")
    lines[0] = f"{method} {upstream_uri} {version}".encode()
    lines = [line for line in lines if not line.lower().startswith((b"authorization:", b"proxy-authorization:"))]
    return b"\r\n".join(lines), upstream_uri.split("/track", 1)[0], public_uri.split("/track", 1)[0]


async def _client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    upstream_reader = upstream_writer = None
    response_task = None
    peer = writer.get_extra_info("peername")
    try:
        while True:
            message, interleaved = await _message(reader)
            if interleaved:
                if upstream_writer:
                    upstream_writer.write(message); await upstream_writer.drain()
                continue
            match = _REQUEST.match(message)
            if not match:
                raise ValueError("Malformed RTSP request")
            method, raw_uri, _ = (part.decode("latin1") for part in match.groups())
            headers = _headers(message)
            cseq = headers.get("cseq", "0")
            if not verify_digest(headers.get("authorization"), method, raw_uri):
                writer.write(_reply(401, "Unauthorized", cseq, {"WWW-Authenticate": digest_challenge()}))
                await writer.drain(); continue
            if raw_uri == "*":
                writer.write(_reply(200, "OK", cseq, {"Public": "OPTIONS, DESCRIBE, SETUP, PLAY, PAUSE, TEARDOWN"}))
                await writer.drain(); continue
            path = urlsplit(raw_uri).path
            if not _allowed(path):
                writer.write(_reply(404, "Not Found", cseq)); await writer.drain(); continue
            if upstream_writer is None:
                upstream_reader, upstream_writer = await asyncio.open_connection("127.0.0.1", settings.RTSP_PORT)
                response_task = asyncio.create_task(_upstream(upstream_reader, writer))
            public_base = f"rtsp://{settings.public_host}:{settings.ONVIF_RTSP_PORT}{path}"
            rewritten, upstream_base, public_base = _rewrite_request(message, public_base)
            # Used by the response relay to repair Content-Base and SDP control URLs.
            response_task.upstream_base = upstream_base.encode()  # type: ignore[attr-defined]
            response_task.public_base = public_base.encode()  # type: ignore[attr-defined]
            upstream_writer.write(rewritten); await upstream_writer.drain()
    except (asyncio.IncompleteReadError, ConnectionError):
        pass
    except Exception as exc:
        logger.warning("RTSP gateway client %s closed: %s", peer, exc)
    finally:
        if response_task:
            response_task.cancel()
        if upstream_writer:
            upstream_writer.close()
            with suppress(Exception): await upstream_writer.wait_closed()
        writer.close()
        with suppress(Exception): await writer.wait_closed()


async def _upstream(reader: asyncio.StreamReader, client: asyncio.StreamWriter) -> None:
    task = asyncio.current_task()
    try:
        while True:
            message, interleaved = await _message(reader)
            if not interleaved:
                old = getattr(task, "upstream_base", b"")
                new = getattr(task, "public_base", b"")
                if old and new and old in message:
                    head, sep, body = message.partition(b"\r\n\r\n")
                    head, body = head.replace(old, new), body.replace(old, new)
                    lines = [line for line in head.split(b"\r\n") if not line.lower().startswith(b"content-length:")]
                    if body:
                        lines.append(f"Content-Length: {len(body)}".encode())
                    message = b"\r\n".join(lines) + sep + body
            client.write(message); await client.drain()
    except (asyncio.IncompleteReadError, ConnectionError, asyncio.CancelledError):
        pass


class RtspProxy:
    def __init__(self):
        self.server: asyncio.Server | None = None

    async def start(self) -> None:
        if self.server is None:
            self.server = await asyncio.start_server(_client, settings.HOST, settings.ONVIF_RTSP_PORT)
            logger.info("Authenticated ONVIF RTSP gateway listening on :%s", settings.ONVIF_RTSP_PORT)

    async def stop(self) -> None:
        if self.server:
            self.server.close(); await self.server.wait_closed(); self.server = None


rtsp_proxy = RtspProxy()
