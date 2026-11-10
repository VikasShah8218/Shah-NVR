"""Camera groups: a lazy tree. Each call returns one level (direct sub-groups), paged; the cameras of a group come
from GET /api/v1/cameras/options?group_id= (docs/GROUPING_PLAN.md)."""

from fastapi import APIRouter, Depends, Query, status

from app.groups import services
from app.groups.models import CameraGroup
from app.groups.schemas import AssignIn, AssignOut, GroupCreate, GroupDetail, GroupOut, GroupUpdate
from utilities.pagination import Page, PageParams, paginate

router = APIRouter(prefix="/api/v1/groups", tags=["Groups"])


@router.get("", response_model=Page[GroupOut], summary="Direct sub-groups of a group, or the top level (paged)")
async def list_groups(
    page: PageParams = Depends(),
    parent_id: int | None = Query(default=None, description="Omit for the top-level groups"),
):
    if parent_id is not None:
        await services.get_group(parent_id)
    return await paginate(services.children_query(parent_id), page, services.groups_out)


@router.get("/search", response_model=Page[GroupOut], summary="Groups whose name contains `q`, anywhere in the tree")
async def search_groups(page: PageParams = Depends(), q: str = Query(min_length=1, max_length=128)):
    qs = CameraGroup.filter(name__icontains=q.strip()).order_by("name", "id")
    return await paginate(qs, page, services.groups_out)


@router.post("/assign", response_model=AssignOut, summary="Move cameras into a group (group_id null = no group)")
async def assign(body: AssignIn):
    return AssignOut(updated=await services.assign_cameras(body.camera_ids, body.group_id))


@router.post("", response_model=GroupDetail, status_code=status.HTTP_201_CREATED)
async def create_group(body: GroupCreate):
    group = await services.create_group(body.name, body.description, body.parent_id)
    return await services.group_detail(group)


@router.get("/{group_id}", response_model=GroupDetail)
async def get_group(group_id: int):
    return await services.group_detail(await services.get_group(group_id))


@router.patch("/{group_id}", response_model=GroupDetail, summary="Rename / describe / move (parent_id)")
async def update_group(group_id: int, body: GroupUpdate):
    group = await services.get_group(group_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("name") is None:
        data.pop("name", None)  # name: null = unchanged
    group = await services.update_group(group, data)
    return await services.group_detail(group)


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Delete a group (409 when not empty, unless move_children=parent)")
async def delete_group(group_id: int, move_children: str | None = Query(default=None, pattern="^parent$")):
    await services.delete_group(await services.get_group(group_id), move_children == "parent")
