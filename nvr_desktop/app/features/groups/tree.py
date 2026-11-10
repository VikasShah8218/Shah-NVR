"""Pure helpers of the camera-group tree (port of nvr_client/src/lib/groupTree.ts). No Qt here."""

from __future__ import annotations

import json

UNGROUPED = "ungrouped"  # tree key of the virtual "Ungrouped" node (real groups use their id as the key)
MAX_EXPANDED = 500


def path_ids(path: str) -> list[int]:
    """"/3/17/42/" -> [3, 17, 42]"""
    return [int(p) for p in (path or "").split("/") if p]


def reveal_keys(path: str) -> list[str]:
    """Keys to expand so a group becomes visible: every ancestor (not the group itself)."""
    return [str(i) for i in path_ids(path)[:-1]]


def is_in_subtree(path: str, ancestor_path: str) -> bool:
    """Is `path` the group at `ancestor_path` or below it? (a group cannot move into its own subtree)"""
    return bool(ancestor_path) and (path or "").startswith(ancestor_path)


def count_label(group: dict, mode: str) -> str:
    """"35/38" (online of total) for the live tree, "38" for management, "" for an empty group."""
    total = group.get("cameras_total", 0)
    if not total:
        return ""
    return f"{group.get('online_total', 0)}/{total}" if mode == "online" else str(total)


def parse_expanded(raw) -> list[str]:
    try:
        value = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    return [k for k in value if isinstance(k, str)][:MAX_EXPANDED] if isinstance(value, list) else []


def toggle_key(keys: list[str], key: str) -> list[str]:
    return [k for k in keys if k != key] if key in keys else (keys + [key])[-MAX_EXPANDED:]


def add_keys(keys: list[str], add: list[str]) -> list[str]:
    return (keys + [k for k in dict.fromkeys(add) if k not in keys])[-MAX_EXPANDED:]
