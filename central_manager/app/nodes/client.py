"""Central -> media node HTTP calls (ONVIF work runs on the node that sits on the cameras' LAN).

Until H1 central never called nodes; nodes only pushed (register / heartbeat). Errors keep the node's
{"code", "message"} detail so clients can tell "wrong password" from "camera unreachable" or "node offline".
"""

from __future__ import annotations

import httpx
from fastapi import HTTPException

from app.assignments.models import CameraAssignment
from app.nodes.models import MediaNode, NodeState

# Nodes that answer API calls (admin states still run the agent; UNREACHABLE / OFFLINE do not).
REACHABLE_STATES = (NodeState.READY, NodeState.ACTIVE, NodeState.DRAINING, NodeState.CORDONED)


def _err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message})


async def call_node(node: MediaNode, path: str, json: dict | None = None, *, timeout: float = 30.0,
                    raw: bool = False) -> dict | list | httpx.Response:
    """POST to the node API. Returns the JSON body (or the response when `raw`), raises HTTPException."""
    url = f"{node.api_url.rstrip('/')}{path}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as http:
            r = await http.post(url, json=json or {})
    except httpx.TimeoutException:
        raise _err(504, "node_timeout", f"Media node '{node.name}' did not answer in {timeout:.0f} s") from None
    except httpx.HTTPError as exc:
        raise _err(502, "node_unreachable", f"Media node '{node.name}' is not reachable ({type(exc).__name__})") from None
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail")
        except ValueError:
            detail = None
        if not isinstance(detail, dict) or "code" not in detail:
            detail = {"code": "node_error", "message": str(detail or f"HTTP {r.status_code} from node '{node.name}'")}
        raise HTTPException(r.status_code, detail)
    return r if raw else r.json()


async def online_nodes() -> list[MediaNode]:
    return await MediaNode.filter(state__in=REACHABLE_STATES).order_by("id")


async def pick_node(node_id: int | None = None, camera_id: int | None = None) -> MediaNode:
    """The node to talk through: the one asked for, else the camera's node, else the first online node."""
    if node_id is not None:
        node = await MediaNode.get_or_none(id=node_id)
        if node is None:
            raise _err(404, "node_not_found", "Media node not found")
        if node.state not in REACHABLE_STATES:
            raise _err(409, "node_offline", f"Media node '{node.name}' is {node.state.value}")
        return node
    if camera_id is not None:
        a = await CameraAssignment.get_or_none(camera_id=camera_id).prefetch_related("node")
        if a is not None and a.node is not None and a.node.state in REACHABLE_STATES:
            return a.node
    nodes = await online_nodes()
    if not nodes:
        raise _err(409, "no_node_online", "No media node is online")
    return nodes[0]
