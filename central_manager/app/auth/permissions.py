"""Shah-NVR permission numbers (docs/AUTH_INTEGRATION_PLAN.md §5, docs/AUTH_V2_PLAN.md).

Inside Shah-NVR a permission is always one of these numbers: the route rules (policy.py), /auth/me and the web
and desktop clients use them. Only the token format differs between the two Auth Servers:
* legacy: the `perms` claim lists the numbers as text ("1", "20"...) plus "*" = everything;
* oidc:   the token carries a bit mask of named codes; CODES below maps each code to its number.
"""

from collections.abc import Callable
from enum import IntEnum

ALL = "*"


class Perm(IntEnum):
    LIVE = 1             # live grid, camera live, live URLs, snapshots
    PLAYBACK = 2         # timeline, recordings, playback, thumbnails, bookmarks (read)
    EXPORT = 3           # create / download / cancel exports, chunk download
    BOOKMARKS_EDIT = 4   # create, edit, delete bookmarks
    PTZ = 5              # move, zoom, use presets
    PTZ_ADMIN = 6        # save / delete presets, PTZ settings
    AUDIO = 7            # live and recorded audio
    CAMERAS_MANAGE = 20  # cameras, streams, discovery, ONVIF device actions
    ENCODER = 21         # camera encoder settings
    GROUPS_MANAGE = 22   # camera groups, assign cameras
    NODES_MANAGE = 23    # media nodes, volumes, quotas, ONVIF server, logs
    ASSIGNMENTS = 24     # move cameras between nodes, run the scheduler
    BACKFILL = 25        # edge-storage backfill
    ACCESS_MANAGE = 30   # camera-group grants for roles and users
    AUDIT_VIEW = 31      # read the audit log
    DASHBOARD = 40       # dashboard, alerts, cluster health


def parse_perms(raw: object) -> tuple[bool, frozenset[int]]:
    """Token `perms` claim -> (has "*", known permission numbers). Unknown codes are ignored."""
    if not isinstance(raw, list):
        return False, frozenset()
    known = {p.value for p in Perm}
    is_all = ALL in raw
    numbers = set()
    for item in raw:
        try:
            value = int(str(item).strip())
        except ValueError:
            continue
        if value in known:
            numbers.add(value)
    return is_all, frozenset(numbers)


# New Auth Server (AUTH_PROVIDER=oidc): the permission codes of app SNVR. Create exactly these in its console.
CODES: dict[str, Perm] = {
    "live.view": Perm.LIVE,
    "playback.view": Perm.PLAYBACK,
    "export.create": Perm.EXPORT,
    "bookmark.edit": Perm.BOOKMARKS_EDIT,
    "ptz.control": Perm.PTZ,
    "ptz.admin": Perm.PTZ_ADMIN,
    "audio.listen": Perm.AUDIO,
    "camera.manage": Perm.CAMERAS_MANAGE,
    "encoder.manage": Perm.ENCODER,
    "group.manage": Perm.GROUPS_MANAGE,
    "node.manage": Perm.NODES_MANAGE,
    "assignment.manage": Perm.ASSIGNMENTS,
    "backfill.manage": Perm.BACKFILL,
    "access.manage": Perm.ACCESS_MANAGE,
    "audit.view": Perm.AUDIT_VIEW,
    "dashboard.view": Perm.DASHBOARD,
}


def perms_from_codes(has_perm: Callable[[str], bool]) -> frozenset[int]:
    """The numbers whose code the token grants (`has_perm` = auth_sdk Principal.has_perm)."""
    return frozenset(perm.value for code, perm in CODES.items() if has_perm(code))
