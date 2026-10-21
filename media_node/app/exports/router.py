import json
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.exports.service import EXPORT_DIR, capabilities

router = APIRouter(prefix="/api/v1/exports", tags=["Exports"])


@router.get("/capabilities")
async def export_capabilities():
    return await capabilities()


@router.get("/{job_id}/file")
async def export_file(job_id: UUID):
    folder = EXPORT_DIR / str(job_id)
    path = folder / "output.mp4"
    if not path.is_file():
        raise HTTPException(404, "Export file not found or expired")
    name = f"export-{job_id}.mp4"
    metadata = folder / "metadata.json"
    if metadata.is_file():
        try:
            name = str(json.loads(metadata.read_text(encoding="utf-8")).get("name") or name)
        except (OSError, ValueError):
            pass
    return FileResponse(path, media_type="video/mp4", filename=name)
