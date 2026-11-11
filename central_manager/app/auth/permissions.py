"""Shah-NVR permission numbers (docs/AUTH_INTEGRATION_PLAN.md §5).

The Auth Server puts permission *codes* in the access token's `perms` claim. For app SNVR the codes are these
numbers as text ("1", "20"...) plus "*" = everything. Numbers keep the token small; the meaning lives here.
The web and desktop clients mirror this table to hide what a user cannot do (the server enforces it).
"""

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
