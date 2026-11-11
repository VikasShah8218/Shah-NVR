"""Camera scope: which cameras (and groups) the current user may see (docs/AUTH_INTEGRATION_PLAN.md §6).

`None` everywhere means "no restriction" (admin, or auth off). The result is computed once per request and
cached on the Principal. Lists filter with these helpers; a forbidden camera id answers 404 (not 403), so the
existence of other cameras is not revealed.
"""

from __future__ import annotations

from tortoise.expressions import Q, Subquery

from app.access.models import AccessGrant
from app.auth.principal import Principal, current
from app.cameras.models import Camera
from app.groups.models import CameraGroup, path_ids

NOTHING = Q(id=-1)  # matches no row (an empty IN list is not portable)


async def _load(p: Principal) -> dict:
    cache = p.scope_cache
    if "loaded" in cache:
        return cache
    cache["loaded"] = True
    cache["all"] = p.is_admin
    cache["group_paths"], cache["camera_ids"] = [], []
    if p.is_admin:
        return cache
    who = Q(subject_type="user", subject=str(p.user_id))
    if p.roles:
        who |= Q(subject_type="role", subject__in=list(p.roles))
    grants = await AccessGrant.filter(who).prefetch_related("group")
    if any(g.all_cameras for g in grants):
        cache["all"] = True
        return cache
    cache["group_paths"] = sorted({g.group.path for g in grants if g.group is not None})
    cache["camera_ids"] = sorted({g.camera_id for g in grants if g.camera_id is not None})
    return cache


async def camera_q(p: Principal | None = None) -> Q | None:
    """Filter for Camera querysets, or None when every camera is visible."""
    scope = await _load(p or current())
    if scope["all"]:
        return None
    parts = [Q(group__path__startswith=path) for path in scope["group_paths"]]
    if scope["camera_ids"]:
        parts.append(Q(id__in=scope["camera_ids"]))
    return Q(*parts, join_type="OR") if parts else NOTHING


async def camera_ids_subquery(p: Principal | None = None) -> Subquery | None:
    """For other tables' `camera_id__in=` filters (bookmarks, exports, assignments...)."""
    q = await camera_q(p)
    return None if q is None else Subquery(Camera.filter(q).values("id"))


async def camera_visible(camera_id: int, p: Principal | None = None) -> bool:
    q = await camera_q(p)
    return True if q is None else await Camera.filter(q, id=camera_id).exists()


async def group_q(p: Principal | None = None) -> Q | None:
    """Filter for CameraGroup querysets: granted groups with their subtrees, plus the ancestors of granted
    groups and of the groups of granted cameras (so the tree can be navigated down to them)."""
    p = p or current()
    scope = await _load(p)
    if scope["all"]:
        return None
    ancestors: set[int] = set()
    for path in scope["group_paths"]:
        ancestors.update(path_ids(path))
    if scope["camera_ids"]:
        cam_paths = await CameraGroup.filter(cameras__id__in=scope["camera_ids"]).values_list("path", flat=True)
        for path in cam_paths:
            ancestors.update(path_ids(path))
    parts = [Q(path__startswith=path) for path in scope["group_paths"]]
    if ancestors:
        parts.append(Q(id__in=sorted(ancestors)))
    return Q(*parts, join_type="OR") if parts else NOTHING


async def summary(p: Principal | None = None) -> dict:
    scope = await _load(p or current())
    return {"all_cameras": scope["all"], "groups": len(scope["group_paths"]), "cameras": len(scope["camera_ids"])}
