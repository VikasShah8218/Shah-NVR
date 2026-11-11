"""Permission numbers (mirror of central_manager/app/auth/permissions.py and nvr_client/src/lib/auth/permissions.ts).

The server enforces every rule; the desktop only hides what a user cannot use. tests/test_auth_core.py checks
that these numbers match the server's.
"""

from __future__ import annotations

from enum import IntEnum


class Perm(IntEnum):
    LIVE = 1
    PLAYBACK = 2
    EXPORT = 3
    BOOKMARKS_EDIT = 4
    PTZ = 5
    PTZ_ADMIN = 6
    AUDIO = 7
    CAMERAS_MANAGE = 20
    ENCODER = 21
    GROUPS_MANAGE = 22
    NODES_MANAGE = 23
    ASSIGNMENTS = 24
    BACKFILL = 25
    ACCESS_MANAGE = 30
    AUDIT_VIEW = 31
    DASHBOARD = 40


ALL_PERMS = tuple(int(p) for p in Perm)

# Anyone who works with cameras may open the camera list (same rule as the server's CAMERA_READ).
CAMERA_READ = (Perm.LIVE, Perm.PLAYBACK, Perm.EXPORT, Perm.CAMERAS_MANAGE, Perm.GROUPS_MANAGE, Perm.ASSIGNMENTS)

PERM_LABELS = {
    1: "Live view", 2: "Playback", 3: "Export", 4: "Bookmarks edit", 5: "PTZ control", 6: "PTZ admin", 7: "Audio",
    20: "Cameras manage", 21: "Encoder", 22: "Groups manage", 23: "Nodes manage", 24: "Assignments", 25: "Backfill",
    30: "Access manage", 31: "Audit view", 40: "Dashboard",
}

# Pages and the permissions that open them (any one is enough; empty = every signed-in user). Same as the web NAV.
PAGE_PERMS: dict[str, tuple[int, ...]] = {
    "dashboard": (Perm.DASHBOARD,),
    "live": (Perm.LIVE,),
    "playback": (Perm.PLAYBACK,),
    "cameras": CAMERA_READ,
    "camera": CAMERA_READ,
    "groups": (Perm.GROUPS_MANAGE,),
    "discover": (Perm.CAMERAS_MANAGE,),
    "nodes": (Perm.NODES_MANAGE,),
    "node": (Perm.NODES_MANAGE,),
    "assignments": (Perm.ASSIGNMENTS,),
    "access": (Perm.ACCESS_MANAGE,),
    "audit": (Perm.AUDIT_VIEW,),
    "settings": (),
}

# Sidebar order: the start page is the first of these the user may open.
NAV_ORDER = ("dashboard", "live", "playback", "cameras", "groups", "discover", "nodes", "assignments", "access",
             "audit", "settings")


def allows(is_admin: bool, permissions, any_of=()) -> bool:
    """Does a user with these permissions pass a check that needs any one of `any_of`? Empty = any user."""
    if is_admin or not any_of:
        return True
    have = set(permissions)
    return any(int(p) in have for p in any_of)


def start_page(is_admin: bool, permissions) -> str:
    return next(p for p in NAV_ORDER if allows(is_admin, permissions, PAGE_PERMS[p]))


def summary_text(summary: dict | None, is_admin: bool = False) -> str:
    """Which cameras a camera scope / grant summary covers, in words ({all_cameras, groups, cameras} counts)."""
    if is_admin:
        return "Everything (admin)"
    if not summary:
        return "No cameras"
    if summary.get("all_cameras"):
        return "All cameras"
    groups, cameras = summary.get("groups") or 0, summary.get("cameras") or 0
    parts = [f"{groups} group{'' if groups == 1 else 's'}" if groups else "",
             f"{cameras} camera{'' if cameras == 1 else 's'}" if cameras else ""]
    return " · ".join(p for p in parts if p) or "No cameras"
