import asyncio

from tortoise import Tortoise

from app.cameras.models import Camera
from app.nodes.models import MediaNode
from app.nodes.router import get_onvif_server, update_onvif_server
from app.nodes.schemas import OnvifServerUpdate
from database.config import APP_MODELS


def run(fn):
    async def wrapper():
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": APP_MODELS})
        await Tortoise.generate_schemas()
        try:
            await fn()
        finally:
            await Tortoise.close_connections()
    asyncio.run(wrapper())


def test_h5_config_contains_no_secret_and_camera_exposure_defaults_true():
    async def go():
        node = await MediaNode.create(name="n1", api_url="http://n1:7100", media_host="n1")
        camera = await Camera.create(name="Lobby")
        assert camera.expose_via_onvif is True
        initial = await get_onvif_server(node.id)
        assert initial.enabled is False and initial.status == "disabled"
        assert "password" not in initial.model_dump()
        changed = await update_onvif_server(node.id, OnvifServerUpdate(
            enabled=True, discovery_name="Floor 1 NVR", location="HQ"
        ))
        assert changed.enabled and changed.discovery_name == "Floor 1 NVR" and changed.status == "pending"
    run(go)
