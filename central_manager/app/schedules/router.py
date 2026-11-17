"""Recording schedules (docs/RECORDING_SCHEDULES_PLAN.md §4.3). The node evaluates them (it gets the blocks with its
assignments); these routes only manage them."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from tortoise.exceptions import IntegrityError
from tortoise.functions import Count

from app.auth import scope
from app.cameras.models import Camera
from app.groups.services import camera_scope
from app.schedules import services
from app.schedules.models import RecordingSchedule
from app.schedules.schemas import (ApplyIn, ApplyOut, PreviewOut, ScheduleIn, ScheduleOut, ScheduleUpdate,
                                   SiteTimeOut)
from utilities.common import utcnow

router = APIRouter(prefix="/api/v1/schedules", tags=["Recording schedules"])


async def _out(schedules: list[RecordingSchedule]) -> list[ScheduleOut]:
    ids = [s.id for s in schedules]
    counts = dict(await Camera.filter(recording_mode="schedule", recording_schedule_id__in=ids)
                  .annotate(n=Count("id")).group_by("recording_schedule_id")
                  .values_list("recording_schedule_id", "n")) if ids else {}
    now, out = utcnow(), []
    for s in schedules:
        on, nxt = services.schedule_state(s, now)
        out.append(ScheduleOut(id=s.id, name=s.name, description=s.description, blocks=s.blocks,
                               camera_count=counts.get(s.id, 0), recording_now=on, next_change=nxt,
                               created_at=s.created_at, updated_at=s.updated_at))
    return out


def _conflict_name(name: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, f"A schedule named '{name}' already exists")


@router.get("", response_model=list[ScheduleOut], summary="All recording schedules (a site has a handful)")
async def list_schedules():
    return await _out(await RecordingSchedule.all())


@router.get("/site-time", response_model=SiteTimeOut, summary="The site clock schedules run on")
async def site_time():
    return SiteTimeOut(timezone=services.site_timezone(), now=utcnow().astimezone(services.zone()))


@router.post("", response_model=ScheduleOut, status_code=status.HTTP_201_CREATED)
async def create_schedule(body: ScheduleIn):
    if await RecordingSchedule.filter(name=body.name).exists():
        raise _conflict_name(body.name)
    try:
        s = await RecordingSchedule.create(name=body.name, description=body.description,
                                           blocks=[b.model_dump() for b in body.blocks])
    except IntegrityError:
        raise _conflict_name(body.name) from None
    return (await _out([s]))[0]


@router.post("/apply", response_model=ApplyOut,
             summary="Set the recording mode of cameras and/or a group (with sub-groups); only visible cameras")
async def apply_schedule(body: ApplyIn):
    group_q = await camera_scope(body.group_id, False, body.include_subgroups) if body.group_id is not None else None
    updated = await services.apply(body.mode, body.schedule_id, body.camera_ids, group_q, await scope.camera_q())
    return ApplyOut(updated=updated)


@router.get("/{schedule_id}", response_model=ScheduleOut)
async def get_schedule(schedule_id: int):
    return (await _out([await services.get_schedule(schedule_id)]))[0]


@router.get("/{schedule_id}/preview", response_model=PreviewOut, summary="On/off spans, site wall clock")
async def preview_schedule(schedule_id: int, start: datetime | None = Query(default=None, alias="from"),
                           days: int = Query(default=7, ge=1, le=31)):
    s = await services.get_schedule(schedule_id)
    start = start or utcnow()
    if start.tzinfo is None:
        start = start.replace(tzinfo=services.zone())
    return PreviewOut(timezone=services.site_timezone(), spans=services.preview(s, start, days))


@router.put("/{schedule_id}", response_model=ScheduleOut)
async def update_schedule(schedule_id: int, body: ScheduleUpdate):
    s = await services.get_schedule(schedule_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("name") is None:
        data.pop("name", None)
    if data.get("blocks") is None:
        data.pop("blocks", None)
    if "name" in data and data["name"] != s.name and await RecordingSchedule.filter(name=data["name"]).exists():
        raise _conflict_name(data["name"])
    if data:
        await s.update_from_dict(data).save()
    return (await _out([s]))[0]


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Delete a schedule (409 while cameras use it)")
async def delete_schedule(schedule_id: int):
    s = await services.get_schedule(schedule_id)
    used = await Camera.filter(recording_schedule_id=s.id).count()
    if used:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"{used} camera(s) use this schedule. Move them to another schedule or mode first.")
    await s.delete()
