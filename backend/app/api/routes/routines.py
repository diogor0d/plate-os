"""Thin HTTP surface for D41 routines, schedules, agenda, and occurrences."""

import uuid
from datetime import date, datetime, timedelta
from typing import Annotated, Awaitable, Callable, TypeVar
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_profile
from app.db import get_session
from app.models import UserProfile
from app.schemas.routines import (
    AgendaOut,
    OccurrenceComplete,
    OccurrenceOut,
    OccurrenceSkip,
    RoutineArchive,
    RoutineOut,
    RoutineWrite,
    ScheduleCreate,
    ScheduleOut,
    ScheduleStateChange,
)
from app.services import routines

router = APIRouter(prefix="/api", tags=["routines"])
T = TypeVar("T")


async def _domain(call: Callable[[], Awaitable[T]]) -> T:
    try:
        return await call()
    except routines.RoutineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/routines", response_model=list[RoutineOut])
async def list_routines(
    include_archived: bool = False,
    profile: UserProfile = Depends(get_current_profile),
    session: AsyncSession = Depends(get_session),
):
    return await _domain(
        lambda: routines.list_routines(session, profile.id, include_archived=include_archived)
    )


@router.post("/routines", response_model=RoutineOut, status_code=201)
async def create_routine(
    body: RoutineWrite,
    profile: UserProfile = Depends(get_current_profile),
    session: AsyncSession = Depends(get_session),
):
    return await _domain(lambda: routines.create_routine(session, profile.id, body))


@router.get("/routines/{routine_id}", response_model=RoutineOut)
async def get_routine(
    routine_id: uuid.UUID,
    profile: UserProfile = Depends(get_current_profile),
    session: AsyncSession = Depends(get_session),
):
    return await _domain(lambda: routines.get_routine(session, profile.id, routine_id))


@router.put("/routines/{routine_id}", response_model=RoutineOut)
async def update_routine(
    routine_id: uuid.UUID,
    body: RoutineWrite,
    profile: UserProfile = Depends(get_current_profile),
    session: AsyncSession = Depends(get_session),
):
    return await _domain(lambda: routines.update_routine(session, profile.id, routine_id, body))


@router.post("/routines/{routine_id}/archive", response_model=RoutineOut)
async def archive_routine(
    routine_id: uuid.UUID,
    body: RoutineArchive,
    profile: UserProfile = Depends(get_current_profile),
    session: AsyncSession = Depends(get_session),
):
    return await _domain(lambda: routines.archive_routine(session, profile.id, routine_id, body))


@router.get("/routines/{routine_id}/schedules", response_model=list[ScheduleOut])
async def list_schedules(
    routine_id: uuid.UUID,
    profile: UserProfile = Depends(get_current_profile),
    session: AsyncSession = Depends(get_session),
):
    return await _domain(lambda: routines.list_schedules(session, profile.id, routine_id))


@router.post("/routines/{routine_id}/schedules", response_model=ScheduleOut, status_code=201)
async def create_schedule(
    routine_id: uuid.UUID,
    body: ScheduleCreate,
    profile: UserProfile = Depends(get_current_profile),
    session: AsyncSession = Depends(get_session),
):
    return await _domain(lambda: routines.create_schedule(session, profile.id, routine_id, body))


@router.patch("/schedules/{schedule_id}", response_model=ScheduleOut)
async def change_schedule_state(
    schedule_id: uuid.UUID,
    body: ScheduleStateChange,
    profile: UserProfile = Depends(get_current_profile),
    session: AsyncSession = Depends(get_session),
):
    return await _domain(
        lambda: routines.change_schedule_state(session, profile.id, schedule_id, body)
    )


@router.post("/agenda/refresh", response_model=AgendaOut)
async def agenda(
    start: date | None = None,
    end: date | None = None,
    days: Annotated[int, Query(ge=1, le=31)] = 7,
    profile: UserProfile = Depends(get_current_profile),
    session: AsyncSession = Depends(get_session),
):
    today = datetime.now(ZoneInfo(profile.timezone)).date()
    resolved_start = start or today
    if end is not None and start is None:
        raise HTTPException(status_code=422, detail="start is required when end is provided")
    resolved_end = end or (resolved_start + timedelta(days=days - 1))
    return await _domain(
        lambda: routines.get_agenda(
            session, profile, start=resolved_start, end=resolved_end
        )
    )


@router.post("/occurrences/{occurrence_id}/complete", response_model=OccurrenceOut)
async def complete_occurrence(
    occurrence_id: uuid.UUID,
    body: OccurrenceComplete,
    profile: UserProfile = Depends(get_current_profile),
    session: AsyncSession = Depends(get_session),
):
    return await _domain(
        lambda: routines.complete_occurrence(session, profile.id, occurrence_id, body)
    )


@router.post("/occurrences/{occurrence_id}/skip", response_model=OccurrenceOut)
async def skip_occurrence(
    occurrence_id: uuid.UUID,
    body: OccurrenceSkip,
    profile: UserProfile = Depends(get_current_profile),
    session: AsyncSession = Depends(get_session),
):
    return await _domain(lambda: routines.skip_occurrence(session, profile.id, occurrence_id, body))
