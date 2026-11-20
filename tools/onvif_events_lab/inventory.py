"""Camera inventory for the lab.

`export`: read the cameras of a Shah-NVR central straight from its PostgreSQL database (connection settings from
central's .env), so the lab can run where auth is on and without an API token. Camera passwords are written only to
the local `cameras.json` next to the lab (never to reports). The ONVIF address is the camera's `onvif_host:port`, or
the host of its first RTSP URL on port 80 when it was added by hand. Credentials come from the camera fields, or from
the RTSP URL (rtsp://user:pass@host/...).
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import unquote, urlsplit


def read_env(path: Path) -> dict:
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


async def export(central_dir: Path, out: Path) -> list[dict]:
    import asyncpg

    env = read_env(central_dir / ".env")
    conn = await asyncpg.connect(host=env.get("DB_HOST", "127.0.0.1"), port=int(env.get("DB_PORT", 5432)),
                                 user=env.get("DB_USER"), password=env.get("DB_PASSWORD"),
                                 database=env.get("DB_NAME"))
    try:
        rows = await conn.fetch("""
            SELECT c.id, c.name, c.enabled, c.username, c.password, c.onvif_host, c.onvif_port, c.manufacturer,
                   c.model, c.firmware, c.has_ptz,
                   (SELECT s.source_url FROM camera_streams s WHERE s.camera_id = c.id ORDER BY s.id LIMIT 1) AS url
            FROM cameras c ORDER BY c.id""")
    finally:
        await conn.close()
    cams = []
    for r in rows:
        u = urlsplit(r["url"] or "")
        host = r["onvif_host"] or u.hostname
        if not host:
            continue
        cams.append({
            "id": r["id"], "name": r["name"], "enabled": r["enabled"], "host": host,
            "port": r["onvif_port"] or 80,
            "username": r["username"] or (unquote(u.username) if u.username else None),
            "password": r["password"] or (unquote(u.password) if u.password else None),
            "manufacturer": r["manufacturer"], "model": r["model"], "firmware": r["firmware"],
            "has_ptz": r["has_ptz"], "onvif_known": bool(r["onvif_host"]),
        })
    out.write_text(json.dumps(cams, indent=2), encoding="utf-8")
    return cams


def load(path: Path, only: list[int] | None = None, enabled_only: bool = True) -> list[dict]:
    cams = json.loads(path.read_text(encoding="utf-8"))
    if only:
        return [c for c in cams if c["id"] in only]
    return [c for c in cams if c.get("enabled", True) or not enabled_only]


def public(cam: dict) -> dict:
    """A camera entry safe for reports (no credentials)."""
    return {k: v for k, v in cam.items() if k not in ("username", "password")}
