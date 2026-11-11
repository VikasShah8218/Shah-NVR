"""Who may call what: one rule per API route (docs/AUTH_INTEGRATION_PLAN.md §7.1).

A rule lists the permission sets that allow the call (any one set is enough; every number in that set is
needed). The request guard (app/auth/deps.py) looks the rule up by method + route template, so a route
without a rule is refused with 403 - and tests/test_auth.py fails when a new route has no rule.

Also per rule:
* `query_token`: the access token may come as `?access_token=` (players and download links cannot set headers);
* `audit`: an audit action name for reads worth recording (changes are always audited).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.auth.permissions import Perm as P


@dataclass(frozen=True)
class Rule:
    need: tuple[frozenset[int], ...] = ()  # () = any signed-in user
    public: bool = False  # no token at all (login, config, health)
    internal: bool = False  # node -> central API (its own key, docs plan §7.6)
    query_token: bool = False
    audit: str | None = None  # audit action for reads; False-y = only changes are audited
    audit_changes: bool = True


def any_of(*perms: int, **kw) -> Rule:
    return Rule(need=tuple(frozenset({int(p)}) for p in perms), **kw)


def all_of(*perms: int, **kw) -> Rule:
    return Rule(need=(frozenset(int(p) for p in perms),), **kw)


SIGNED_IN = Rule()
PUBLIC = Rule(public=True)
INTERNAL = Rule(internal=True)
CAMERA_READ = any_of(P.LIVE, P.PLAYBACK, P.EXPORT, P.CAMERAS_MANAGE, P.GROUPS_MANAGE, P.ASSIGNMENTS)

POLICY: dict[tuple[str, str], Rule] = {
    ("GET", "/"): PUBLIC,
    # ---------------------------------------------------------------- auth / access / audit
    ("GET", "/api/v1/auth/config"): PUBLIC,
    ("POST", "/api/v1/auth/login"): PUBLIC,
    ("POST", "/api/v1/auth/refresh"): PUBLIC,
    ("POST", "/api/v1/auth/logout"): Rule(audit_changes=False),  # the router writes "auth.logout"
    ("GET", "/api/v1/auth/me"): SIGNED_IN,
    ("GET", "/api/v1/access/subjects"): any_of(P.ACCESS_MANAGE),
    ("GET", "/api/v1/access/grants"): any_of(P.ACCESS_MANAGE),
    ("PUT", "/api/v1/access/grants"): any_of(P.ACCESS_MANAGE),
    ("GET", "/api/v1/audit"): any_of(P.AUDIT_VIEW),
    # ---------------------------------------------------------------- cameras
    ("POST", "/api/v1/cameras"): any_of(P.CAMERAS_MANAGE),
    ("GET", "/api/v1/cameras"): CAMERA_READ,
    ("GET", "/api/v1/cameras/options"): SIGNED_IN,
    ("GET", "/api/v1/cameras/{camera_id}"): CAMERA_READ,
    ("PATCH", "/api/v1/cameras/{camera_id}"): any_of(P.CAMERAS_MANAGE),
    ("DELETE", "/api/v1/cameras/{camera_id}"): any_of(P.CAMERAS_MANAGE),
    ("POST", "/api/v1/cameras/{camera_id}/streams"): any_of(P.CAMERAS_MANAGE),
    ("PATCH", "/api/v1/cameras/{camera_id}/streams/{profile}"): any_of(P.CAMERAS_MANAGE),
    ("DELETE", "/api/v1/cameras/{camera_id}/streams/{profile}"): any_of(P.CAMERAS_MANAGE),
    ("GET", "/api/v1/cameras/{camera_id}/live"): any_of(P.LIVE, audit="live.open"),
    # ---------------------------------------------------------------- groups (visibility follows the camera scope)
    ("GET", "/api/v1/groups"): SIGNED_IN,
    ("GET", "/api/v1/groups/search"): SIGNED_IN,
    ("GET", "/api/v1/groups/{group_id}"): SIGNED_IN,
    ("POST", "/api/v1/groups"): any_of(P.GROUPS_MANAGE),
    ("POST", "/api/v1/groups/assign"): any_of(P.GROUPS_MANAGE),
    ("PATCH", "/api/v1/groups/{group_id}"): any_of(P.GROUPS_MANAGE),
    ("DELETE", "/api/v1/groups/{group_id}"): any_of(P.GROUPS_MANAGE),
    # ---------------------------------------------------------------- recordings / playback / bookmarks / exports
    ("GET", "/api/v1/cameras/{camera_id}/recordings"): any_of(P.PLAYBACK),
    ("GET", "/api/v1/playback/{camera_id}/index.m3u8"): any_of(P.PLAYBACK, query_token=True, audit="playback.open"),
    ("GET", "/api/v1/playback/{camera_id}/audio.m3u8"): all_of(P.PLAYBACK, P.AUDIO, query_token=True),
    ("GET", "/api/v1/bookmarks"): any_of(P.PLAYBACK),
    ("GET", "/api/v1/bookmarks/{bookmark_id}"): any_of(P.PLAYBACK),
    ("POST", "/api/v1/bookmarks"): any_of(P.BOOKMARKS_EDIT),
    ("PATCH", "/api/v1/bookmarks/{bookmark_id}"): any_of(P.BOOKMARKS_EDIT),
    ("DELETE", "/api/v1/bookmarks/{bookmark_id}"): any_of(P.BOOKMARKS_EDIT),
    ("POST", "/api/v1/exports"): any_of(P.EXPORT),
    ("GET", "/api/v1/exports"): any_of(P.EXPORT),
    ("GET", "/api/v1/exports/{job_id}"): any_of(P.EXPORT),
    ("POST", "/api/v1/exports/{job_id}/cancel"): any_of(P.EXPORT),
    ("GET", "/api/v1/exports/{job_id}/download"): any_of(P.EXPORT, query_token=True, audit="export.download"),
    # ---------------------------------------------------------------- nodes
    ("GET", "/api/v1/nodes"): any_of(P.NODES_MANAGE, P.DASHBOARD, P.ASSIGNMENTS),
    ("GET", "/api/v1/nodes/{node_id}"): any_of(P.NODES_MANAGE, P.DASHBOARD),
    ("PATCH", "/api/v1/nodes/{node_id}"): any_of(P.NODES_MANAGE),
    ("DELETE", "/api/v1/nodes/{node_id}"): any_of(P.NODES_MANAGE),
    ("GET", "/api/v1/nodes/{node_id}/onvif-server"): any_of(P.NODES_MANAGE),
    ("PATCH", "/api/v1/nodes/{node_id}/onvif-server"): any_of(P.NODES_MANAGE),
    ("GET", "/api/v1/nodes/{node_id}/volumes"): any_of(P.NODES_MANAGE),
    ("POST", "/api/v1/nodes/{node_id}/volumes"): any_of(P.NODES_MANAGE),
    ("PATCH", "/api/v1/nodes/{node_id}/volumes/{volume_id}"): any_of(P.NODES_MANAGE),
    ("DELETE", "/api/v1/nodes/{node_id}/volumes/{volume_id}"): any_of(P.NODES_MANAGE),
    ("POST", "/api/v1/nodes/{node_id}/volumes/reorder"): any_of(P.NODES_MANAGE),
    ("POST", "/api/v1/nodes/{node_id}/drain"): any_of(P.NODES_MANAGE),
    ("POST", "/api/v1/nodes/{node_id}/cordon"): any_of(P.NODES_MANAGE),
    ("POST", "/api/v1/nodes/{node_id}/activate"): any_of(P.NODES_MANAGE),
    # ---------------------------------------------------------------- assignments / cluster
    ("GET", "/api/v1/assignments"): any_of(P.ASSIGNMENTS),
    ("PUT", "/api/v1/assignments/{camera_id}"): any_of(P.ASSIGNMENTS),
    ("GET", "/api/v1/assignments/{camera_id}/history"): any_of(P.ASSIGNMENTS, P.CAMERAS_MANAGE),
    ("POST", "/api/v1/assignments/run-scheduler"): any_of(P.ASSIGNMENTS),
    ("GET", "/api/v1/cluster/health"): SIGNED_IN,  # top bar status for everyone
    ("GET", "/api/v1/cluster/alerts"): any_of(P.DASHBOARD),
    # ---------------------------------------------------------------- ONVIF / encoder / PTZ / backfill
    ("POST", "/api/v1/onvif/discover"): any_of(P.CAMERAS_MANAGE),
    ("POST", "/api/v1/onvif/probe"): any_of(P.CAMERAS_MANAGE),
    ("POST", "/api/v1/onvif/snapshot"): any_of(P.CAMERAS_MANAGE),
    ("POST", "/api/v1/onvif/cameras"): any_of(P.CAMERAS_MANAGE),
    ("GET", "/api/v1/onvif/cameras/{camera_id}/device"): any_of(P.CAMERAS_MANAGE),
    ("POST", "/api/v1/onvif/cameras/{camera_id}/time-sync"): any_of(P.CAMERAS_MANAGE),
    ("POST", "/api/v1/onvif/cameras/{camera_id}/ntp"): any_of(P.CAMERAS_MANAGE),
    ("POST", "/api/v1/onvif/cameras/{camera_id}/reboot"): any_of(P.CAMERAS_MANAGE),
    ("GET", "/api/v1/cameras/{camera_id}/streams/{profile}/encoder"): any_of(P.ENCODER),
    ("PUT", "/api/v1/cameras/{camera_id}/streams/{profile}/encoder"): any_of(P.ENCODER),
    ("PUT", "/api/v1/cameras/{camera_id}/streams/{profile}/encoder/mapping"): any_of(P.ENCODER),
    ("POST", "/api/v1/cameras/{camera_id}/streams/{profile}/encoder/check"): any_of(P.ENCODER, audit_changes=False),
    ("GET", "/api/v1/cameras/{camera_id}/streams/{profile}/encoder/history"): any_of(P.ENCODER),
    ("POST", "/api/v1/cameras/{camera_id}/streams/{profile}/encoder/resolve"): any_of(P.ENCODER),
    ("GET", "/api/v1/cameras/{camera_id}/streams/{profile}/encoder/recovery"): any_of(P.ENCODER),
    ("POST", "/api/v1/cameras/{camera_id}/streams/{profile}/ptz"): any_of(P.PTZ),
    ("POST", "/api/v1/cameras/{camera_id}/streams/{profile}/ptz/session"): any_of(P.PTZ),
    ("POST", "/api/v1/cameras/{camera_id}/streams/{profile}/ptz/command"): any_of(P.PTZ, audit_changes=False),
    ("GET", "/api/v1/cameras/{camera_id}/backfill"): any_of(P.BACKFILL),
    ("PATCH", "/api/v1/cameras/{camera_id}/backfill"): any_of(P.BACKFILL),
    ("POST", "/api/v1/cameras/{camera_id}/backfill/probe"): any_of(P.BACKFILL),
    ("POST", "/api/v1/cameras/{camera_id}/backfill/jobs"): any_of(P.BACKFILL),
    ("GET", "/api/v1/cameras/{camera_id}/backfill/jobs"): any_of(P.BACKFILL),
}


def rule_for(method: str, path: str) -> Rule | None:
    """The rule of a route template. `/internal/v1/*` is the node API (plan §7.6)."""
    if path.startswith("/internal/v1/"):
        return INTERNAL
    return POLICY.get((method.upper(), path))


def allows(rule: Rule, perms: frozenset[int], is_admin: bool) -> bool:
    if is_admin or not rule.need:
        return True
    return any(needed <= perms for needed in rule.need)


# Audit action names for changes: the route's fixed words + a verb, e.g. "cameras.streams.update"
_VERBS = {"POST": "create", "PUT": "update", "PATCH": "update", "DELETE": "delete"}


def change_action(method: str, path: str) -> str:
    parts = [p for p in path.split("/") if p and not p.startswith("{") and p not in ("api", "v1")]
    return f"{'.'.join(parts) or 'root'}.{_VERBS.get(method.upper(), method.lower())}"
