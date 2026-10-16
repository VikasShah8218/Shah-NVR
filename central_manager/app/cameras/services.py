from tortoise.transactions import in_transaction

from app.cameras.models import Camera, CameraStream


async def create_camera_with_streams(fields: dict, streams: list[dict]) -> Camera:
    """One camera + its streams in one transaction (manual form and ONVIF add share this)."""
    async with in_transaction():
        camera = await Camera.create(**fields)
        for s in streams:
            await CameraStream.create(camera=camera, **s)
    return camera
