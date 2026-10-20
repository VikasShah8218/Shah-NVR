import asyncio

import pytest
from fastapi import HTTPException
from tortoise import Tortoise

from app.assignments.models import CameraAssignment
from app.cameras.models import Camera, CameraStream
from app.cameras.router import get_live
from app.nodes.models import MediaNode
from app.nodes.router import update_node
from app.nodes.schemas import NodeUpdate
from database.config import APP_MODELS


def run(coro_fn):
    async def wrapper():
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": APP_MODELS})
        await Tortoise.generate_schemas()
        try:
            await coro_fn()
        finally:
            await Tortoise.close_connections()

    asyncio.run(wrapper())


def test_public_toggle_changes_only_client_facing_endpoints():
    async def body():
        node = await MediaNode.create(
            name="node-1", api_url="http://192.168.1.115:7100", media_host="192.168.1.115",
            rtsp_port=8554, hls_port=8888, webrtc_port=8889,
        )
        out = await update_node(node.id, NodeUpdate(
            public_enabled=True,
            public_api_url="https://nvr.example.com:17100/",
            public_media_host="nvr.example.com",
            public_rtsp_port=18554,
            public_hls_port=18888,
            public_webrtc_port=18889,
            public_media_tls=True,
        ))
        assert out.client_api_url == "https://nvr.example.com:17100"
        assert out.client_media_host == "nvr.example.com"
        assert out.client_rtsp_port == 18554
        assert out.client_hls_port == 18888
        assert out.client_webrtc_port == 18889
        assert out.client_media_scheme == "https"

        stored = await MediaNode.get(id=node.id)
        assert stored.api_url == "http://192.168.1.115:7100"
        assert stored.media_host == "192.168.1.115"

        disabled = await update_node(node.id, NodeUpdate(public_enabled=False))
        assert disabled.client_api_url == "http://192.168.1.115:7100"
        assert disabled.client_media_host == "192.168.1.115"
        assert disabled.client_media_scheme == "http"

    run(body)


def test_public_toggle_requires_api_url_and_media_host():
    async def body():
        node = await MediaNode.create(name="node-1", api_url="http://node:7100", media_host="node")
        with pytest.raises(HTTPException) as exc:
            await update_node(node.id, NodeUpdate(public_enabled=True))
        assert exc.value.status_code == 422

    run(body)


def test_live_urls_use_public_media_mapping():
    async def body():
        node = await MediaNode.create(
            name="node-1", api_url="http://192.168.1.115:7100", media_host="192.168.1.115",
            public_enabled=True, public_api_url="https://nvr.example.com:17100",
            public_media_host="nvr.example.com", public_rtsp_port=18554,
            public_hls_port=18888, public_webrtc_port=18889, public_media_tls=True,
        )
        camera = await Camera.create(name="camera")
        await CameraStream.create(camera=camera, profile="main", source_url="rtsp://camera/main")
        await CameraAssignment.create(camera=camera, node=node, generation=1)

        live = await get_live(camera.id)
        assert live.streams[0].rtsp == "rtsp://nvr.example.com:18554/cam-1/main"
        assert live.streams[0].hls == "https://nvr.example.com:18888/cam-1/main/index.m3u8"
        assert live.streams[0].webrtc == "https://nvr.example.com:18889/cam-1/main"

    run(body)
