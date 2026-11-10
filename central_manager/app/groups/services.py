"""Camera group tree: create / move / delete with path upkeep, labels and roll-up counts (docs/GROUPING_PLAN.md)."""

from collections.abc import Iterable, Sequence

from fastapi import HTTPException, status
from tortoise.expressions import Q, Subquery
from tortoise.functions import Count
from tortoise.transactions import in_transaction

from app.cameras.models import Camera, CameraStream, StreamStatus
from app.groups.models import CameraGroup, path_ids
from app.groups.schemas import GroupDetail, GroupOut, GroupRef

MAX_DEPTH = 8  # levels: depth 0..7
SEPARATOR = " › "
ONLINE = (StreamStatus.RECORDING, StreamStatus.STREAMING, StreamStatus.IDLE)


def _err(code: int, message: str) -> HTTPException:
    return HTTPException(code, message)


async def get_group(group_id: int) -> CameraGroup:
    group = await CameraGroup.get_or_none(id=group_id)
    if group is None:
        raise _err(status.HTTP_404_NOT_FOUND, "Group not found")
    return group


def _children_of(parent_id: int | None):
    return CameraGroup.filter(parent_id__isnull=True) if parent_id is None else CameraGroup.filter(parent_id=parent_id)


async def _check_name(parent_id: int | None, name: str, exclude_id: int | None = None) -> None:
    """Sibling names are unique, case-insensitive (D6). Checked in code: a NULL parent defeats a unique index."""
    qs = _children_of(parent_id).filter(name__iexact=name)
    if exclude_id is not None:
        qs = qs.exclude(id=exclude_id)
    if await qs.exists():
        raise _err(status.HTTP_409_CONFLICT, f"A group named '{name}' already exists here")


def _own_path(parent: CameraGroup | None, group_id: int) -> str:
    return f"{parent.path if parent else '/'}{group_id}/"


# ------------------------------------------------------------------ create / update / delete
async def create_group(name: str, description: str | None, parent_id: int | None) -> CameraGroup:
    async with in_transaction():
        parent = await get_group(parent_id) if parent_id is not None else None
        depth = parent.depth + 1 if parent else 0
        if depth >= MAX_DEPTH:
            raise _err(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Groups can be nested at most {MAX_DEPTH} levels deep")
        await _check_name(parent_id, name)
        group = await CameraGroup.create(name=name, description=description, parent_id=parent_id, depth=depth)
        group.path = _own_path(parent, group.id)
        await group.save(update_fields=["path"])
    return group


async def update_group(group: CameraGroup, data: dict) -> CameraGroup:
    async with in_transaction():
        moving = "parent_id" in data and data["parent_id"] != group.parent_id
        target_parent = data["parent_id"] if moving else group.parent_id
        name = data.get("name") or group.name
        if moving or "name" in data:
            await _check_name(target_parent, name, exclude_id=group.id)
        if moving:
            await _move(group, target_parent)
        changed = [f for f in ("name", "description") if f in data]
        for f in changed:
            setattr(group, f, data[f])
        if changed:
            await group.save(update_fields=[*changed, "updated_at"])
    return group


async def _move(group: CameraGroup, parent_id: int | None) -> None:
    """Re-parent `group` and rewrite path/depth of its whole subtree (the caller holds the transaction)."""
    parent = await get_group(parent_id) if parent_id is not None else None
    if parent is not None and parent.path.startswith(group.path):
        raise _err(status.HTTP_409_CONFLICT, "A group cannot be moved into itself or one of its sub-groups")
    subtree = await CameraGroup.filter(path__startswith=group.path)
    height = max(g.depth for g in subtree) - group.depth
    new_depth = parent.depth + 1 if parent else 0
    if new_depth + height >= MAX_DEPTH:
        raise _err(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Groups can be nested at most {MAX_DEPTH} levels deep")
    old_path, new_path, shift = group.path, _own_path(parent, group.id), new_depth - group.depth
    for g in subtree:
        g.path = new_path + g.path[len(old_path):]
        g.depth += shift
    await CameraGroup.bulk_update(subtree, fields=["path", "depth"])
    group.parent_id, group.path, group.depth = parent_id, new_path, new_depth
    await group.save(update_fields=["parent_id", "updated_at"])


async def delete_group(group: CameraGroup, move_children: bool) -> None:
    """Refused when not empty (D3), unless `move_children`: sub-groups and cameras go up one level."""
    async with in_transaction():
        children = await CameraGroup.filter(parent_id=group.id)
        cameras = await Camera.filter(group_id=group.id).count()
        if (children or cameras) and not move_children:
            raise _err(status.HTTP_409_CONFLICT,
                       f"Group is not empty ({len(children)} sub-groups, {cameras} cameras). "
                       "Move its contents to the parent group, or empty it first.")
        if children:
            taken = {n.lower() for n in await _children_of(group.parent_id).exclude(id=group.id)
                     .values_list("name", flat=True)}
            clash = sorted(c.name for c in children if c.name.lower() in taken)
            if clash:
                raise _err(status.HTTP_409_CONFLICT,
                           f"The parent already has groups named {', '.join(clash)}; rename them first")
            for child in children:
                await _move(child, group.parent_id)
        if cameras:
            await Camera.filter(group_id=group.id).update(group_id=group.parent_id)
        await group.delete()


async def assign_cameras(camera_ids: list[int], group_id: int | None) -> int:
    if group_id is not None:
        await get_group(group_id)
    return await Camera.filter(id__in=list(set(camera_ids))).update(group_id=group_id)


async def check_group_id(group_id: int | None) -> None:
    """422 for a camera create/update that names a group which does not exist."""
    if group_id is not None and not await CameraGroup.filter(id=group_id).exists():
        raise _err(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Group {group_id} does not exist")


# ------------------------------------------------------------------ camera filters
async def camera_scope(group_id: int | None, ungrouped: bool, recursive: bool) -> Q | None:
    """Filter for the camera lists: directly in a group, in its whole subtree, or in no group."""
    if ungrouped:
        return Q(group_id__isnull=True)
    if group_id is None:
        return None
    if not recursive:
        return Q(group_id=group_id)
    group = await get_group(group_id)
    return Q(group_id__in=Subquery(CameraGroup.filter(path__startswith=group.path).values("id")))


# ------------------------------------------------------------------ labels
async def group_labels(group_ids: Iterable[int | None]) -> dict[int, str]:
    """{group id: "Anantnag › Bijbehara"} for a page of cameras or groups: 2 small queries."""
    ids = {g for g in group_ids if g is not None}
    if not ids:
        return {}
    paths = dict(await CameraGroup.filter(id__in=ids).values_list("id", "path"))
    return await _labels_for_paths(paths)


async def _labels_for_paths(paths: dict[int, str]) -> dict[int, str]:
    needed = {i for p in paths.values() for i in path_ids(p)}
    names = dict(await CameraGroup.filter(id__in=needed).values_list("id", "name")) if needed else {}
    return {gid: SEPARATOR.join(names.get(i, "?") for i in path_ids(p)) for gid, p in paths.items()}


# ------------------------------------------------------------------ output with roll-up counts
async def groups_out(groups: Sequence[CameraGroup]) -> list[GroupOut]:
    """A page of groups with labels and counts, in a fixed number of queries (not per group):
    descendants of the page, cameras per group, online cameras per group, ancestor names."""
    if not groups:
        return []
    cond = Q(*[Q(path__startswith=g.path) for g in groups], join_type="OR")
    subtree = dict(await CameraGroup.filter(cond).values_list("id", "path"))
    sub_ids = list(subtree)
    cams = dict(await Camera.filter(group_id__in=sub_ids).annotate(n=Count("id")).group_by("group_id")
                .values_list("group_id", "n"))
    online = dict(await Camera.filter(
        group_id__in=sub_ids, enabled=True,
        id__in=Subquery(CameraStream.filter(status__in=ONLINE).values("camera_id")),
    ).annotate(n=Count("id")).group_by("group_id").values_list("group_id", "n"))
    labels = await _labels_for_paths({g.id: g.path for g in groups})
    out = []
    for g in groups:
        inside = [gid for gid, p in subtree.items() if p.startswith(g.path)]
        out.append(GroupOut(
            id=g.id, name=g.name, description=g.description, parent_id=g.parent_id, depth=g.depth, path=g.path,
            path_label=labels[g.id], sort_order=g.sort_order,
            child_groups=sum(1 for gid in inside if len(path_ids(subtree[gid])) == g.depth + 2),
            cameras_direct=cams.get(g.id, 0),
            cameras_total=sum(cams.get(gid, 0) for gid in inside),
            online_total=sum(online.get(gid, 0) for gid in inside),
            created_at=g.created_at, updated_at=g.updated_at,
        ))
    return out


async def group_detail(group: CameraGroup) -> GroupDetail:
    (out,) = await groups_out([group])
    ancestors = group.ancestor_ids()
    names = dict(await CameraGroup.filter(id__in=ancestors).values_list("id", "name")) if ancestors else {}
    return GroupDetail(**out.model_dump(), breadcrumb=[GroupRef(id=i, name=names.get(i, "?")) for i in ancestors])


def children_query(parent_id: int | None):
    return _children_of(parent_id).order_by("sort_order", "name", "id")
