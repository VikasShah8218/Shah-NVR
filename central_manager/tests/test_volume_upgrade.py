"""Upgrade path: an existing node's old node-wide quota becomes the cap of its default volume."""

import asyncio

from tortoise import Tortoise

from app.nodes import volumes as vol
from app.nodes.models import MediaNode, StorageVolume, VolumeState
from app.nodes.schemas import VolumeReport
from database.config import APP_MODELS

GB = 1024**3


async def _init():
    await Tortoise.init(db_url="sqlite://:memory:", modules={"models": APP_MODELS})
    await Tortoise.generate_schemas()


def test_default_volume_inherits_old_quota_and_follows_the_folder():
    async def run():
        await _init()
        try:
            node = await MediaNode.create(name="n1", api_url="http://n1:7100", media_host="n1",
                                          storage_quota_bytes=800 * GB)
            await StorageVolume.create(node=node, path=r"D:\nvr", position=0)  # added before the upgrade heartbeat

            await vol.ensure_default_volume(node, r"C:\nvr\recordings")
            default = await StorageVolume.get(node=node, is_default=True)
            assert default.quota_bytes == 800 * GB and default.path == r"C:\nvr\recordings"
            assert default.position == -1  # stays first in the fill order

            await vol.ensure_default_volume(node, r"C:\nvr\recordings")  # idempotent
            assert await StorageVolume.filter(node=node, is_default=True).count() == 1

            await vol.ensure_default_volume(node, "E:/moved/")  # RECORDINGS_DIR changed on the node
            default = await StorageVolume.get(node=node, is_default=True)
            assert default.path == r"E:\moved" and default.state == VolumeState.PENDING

            await vol.apply_reports(node.id, [VolumeReport(id=default.id, state=VolumeState.FULL, recordings_bytes=5,
                                                           writing=False)])
            default = await StorageVolume.get(id=default.id)
            assert default.state == VolumeState.FULL and default.recordings_bytes == 5 and default.last_report_at
            assert [v.path for v in await vol.node_volumes(node.id)] == [r"E:\moved", r"D:\nvr"]
        finally:
            await Tortoise.close_connections()

    asyncio.run(run())
