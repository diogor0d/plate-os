"""User-owned meal routines, wall-clock recurrence, and occurrence lifecycle."""

import hashlib
import json
import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Iterable
from zoneinfo import ZoneInfo

from sqlalchemy import delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.models import (
    FoodItem,
    MealLog,
    MealLogMutation,
    MealOccurrence,
    MealOccurrenceLog,
    MealRoutine,
    MealRoutineItem,
    MealSchedule,
    MealScheduleWeekday,
    NotificationIntent,
    PlanningMutation,
    UserProfile,
)
from app.schemas.products import ProductOut
from app.schemas.routines import (
    AgendaOut,
    OccurrenceComplete,
    OccurrenceOut,
    OccurrenceSkip,
    RoutineArchive,
    RoutineItemOut,
    RoutineOut,
    RoutineWrite,
    ScheduleCreate,
    ScheduleOut,
    ScheduleStateChange,
)

MAX_AGENDA_DAYS = 31


class RoutineError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def mutation_fingerprint(body: BaseModel) -> str:
    payload = body.model_dump(mode="json", exclude={"client_mutation_id"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def resolve_wall_clock(
    local_date: date, local_time: time, timezone_name: str
) -> tuple[datetime, str]:
    """Resolve civil time to UTC, choosing the earlier fold and shifting gaps forward."""
    zone = ZoneInfo(timezone_name)
    naive = datetime.combine(local_date, local_time.replace(tzinfo=None))
    candidates: list[datetime] = []
    round_trips: list[datetime] = []
    for fold in (0, 1):
        aware = naive.replace(tzinfo=zone, fold=fold)
        instant = aware.astimezone(UTC)
        returned = instant.astimezone(zone)
        round_trips.append(returned)
        if returned.replace(tzinfo=None) == naive:
            candidates.append(instant)

    unique = sorted(set(candidates))
    if unique:
        return unique[0], "ambiguous-earlier" if len(unique) == 2 else "exact"

    shifted = min(
        returned for returned in round_trips if returned.replace(tzinfo=None) > naive
    )
    return shifted.astimezone(UTC), "nonexistent-shift-forward"


def recurrence_dates(
    *,
    frequency: str,
    interval: int,
    iso_weekdays: Iterable[int],
    start_date: date,
    end_date: date | None,
    range_start: date,
    range_end: date,
) -> list[date]:
    if interval < 1 or interval > 4:
        raise ValueError("interval must be between 1 and 4")
    if range_end < range_start:
        return []
    lower = max(start_date, range_start)
    upper = min(end_date or range_end, range_end)
    if upper < lower:
        return []

    result: list[date] = []
    current = lower
    weekdays = set(iso_weekdays)
    anchor_monday = start_date - timedelta(days=start_date.isoweekday() - 1)
    while current <= upper:
        if frequency == "daily":
            matches = (current - start_date).days % interval == 0
        elif frequency == "weekly":
            week = (current - anchor_monday).days // 7
            matches = week % interval == 0 and current.isoweekday() in weekdays
        else:
            raise ValueError("unsupported recurrence frequency")
        if matches:
            result.append(current)
        current += timedelta(days=1)
    return result


def occurrence_state(occurrence: MealOccurrence, now: datetime, schedule_timezone: str) -> str:
    if occurrence.status in {"completed", "skipped"}:
        return occurrence.status
    now = now.astimezone(UTC)
    scheduled_at = occurrence.scheduled_at.astimezone(UTC)
    if scheduled_at > now:
        return "upcoming"
    local_today = now.astimezone(ZoneInfo(schedule_timezone)).date()
    return "due" if occurrence.scheduled_local_date == local_today else "missed"


async def _replay(
    session: AsyncSession,
    user_id: uuid.UUID,
    client_mutation_id: uuid.UUID,
    operation: str,
    fingerprint: str,
) -> PlanningMutation | None:
    mutation = await session.get(
        PlanningMutation,
        {"user_id": user_id, "client_mutation_id": client_mutation_id},
    )
    if mutation is None:
        return None
    if mutation.operation != operation or mutation.request_fingerprint != fingerprint:
        raise RoutineError(
            409,
            "client_mutation_id was already used with a different operation or payload",
        )
    if mutation.resource_id is None:
        raise RoutineError(409, "idempotency record is inconsistent")
    return mutation


async def _commit_mutation(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    client_mutation_id: uuid.UUID,
    operation: str,
    fingerprint: str,
    resource_id: uuid.UUID,
) -> uuid.UUID:
    session.add(
        PlanningMutation(
            user_id=user_id,
            client_mutation_id=client_mutation_id,
            operation=operation,
            request_fingerprint=fingerprint,
            resource_id=resource_id,
        )
    )
    try:
        await session.commit()
        return resource_id
    except IntegrityError:
        await session.rollback()
        replay = await _replay(session, user_id, client_mutation_id, operation, fingerprint)
        if replay is None or replay.resource_id is None:
            raise
        return replay.resource_id


async def _owned_routine(
    session: AsyncSession, user_id: uuid.UUID, routine_id: uuid.UUID, *, active: bool = False
) -> MealRoutine:
    routine = await session.get(MealRoutine, routine_id)
    if (
        routine is None
        or routine.user_id != user_id
        or (active and routine.archived_at is not None)
    ):
        raise RoutineError(404, "routine not found")
    return routine


async def _routine_out(session: AsyncSession, routine: MealRoutine) -> RoutineOut:
    rows = (
        await session.execute(
            select(MealRoutineItem, FoodItem)
            .join(FoodItem, FoodItem.id == MealRoutineItem.food_item_id)
            .where(MealRoutineItem.routine_id == routine.id)
            .order_by(MealRoutineItem.position)
        )
    ).all()
    return RoutineOut(
        id=routine.id,
        title=routine.title,
        mode=routine.mode,
        rough_text=routine.rough_text,
        version=routine.version,
        archived_at=routine.archived_at,
        created_at=routine.created_at,
        updated_at=routine.updated_at,
        items=[
            RoutineItemOut(
                position=item.position,
                quantity_g=float(item.quantity_g),
                product=ProductOut.model_validate(product),
            )
            for item, product in rows
        ],
    )


async def _validated_products(
    session: AsyncSession, product_ids: list[uuid.UUID]
) -> dict[uuid.UUID, FoodItem]:
    if not product_ids:
        return {}
    products = (
        await session.execute(
            select(FoodItem)
            .where(FoodItem.id.in_(product_ids), FoodItem.archived_at.is_(None))
            .with_for_update()
        )
    ).scalars().all()
    by_id = {product.id: product for product in products}
    if len(by_id) != len(product_ids):
        raise RoutineError(422, "defined routines require accepted, non-archived products")
    return by_id


async def list_routines(
    session: AsyncSession, user_id: uuid.UUID, *, include_archived: bool = False
) -> list[RoutineOut]:
    stmt = select(MealRoutine).where(MealRoutine.user_id == user_id)
    if not include_archived:
        stmt = stmt.where(MealRoutine.archived_at.is_(None))
    routines = (await session.execute(stmt.order_by(MealRoutine.updated_at.desc()))).scalars().all()
    return [await _routine_out(session, routine) for routine in routines]


async def get_routine(
    session: AsyncSession, user_id: uuid.UUID, routine_id: uuid.UUID
) -> RoutineOut:
    return await _routine_out(session, await _owned_routine(session, user_id, routine_id))


async def create_routine(
    session: AsyncSession, user_id: uuid.UUID, body: RoutineWrite
) -> RoutineOut:
    if body.expected_version is not None:
        raise RoutineError(422, "expected_version is not allowed when creating a routine")
    fingerprint = mutation_fingerprint(body)
    replay = await _replay(session, user_id, body.client_mutation_id, "routine_create", fingerprint)
    if replay is not None:
        assert replay.resource_id is not None
        return await get_routine(session, user_id, replay.resource_id)
    await _validated_products(session, [item.food_item_id for item in body.items])
    routine = MealRoutine(
        id=uuid.uuid4(),
        user_id=user_id,
        title=body.title,
        mode=body.mode,
        rough_text=body.rough_text,
    )
    session.add(routine)
    for position, item in enumerate(body.items):
        session.add(
            MealRoutineItem(
                routine_id=routine.id,
                position=position,
                food_item_id=item.food_item_id,
                quantity_g=item.quantity_g,
            )
        )
    resource_id = await _commit_mutation(
        session,
        user_id=user_id,
        client_mutation_id=body.client_mutation_id,
        operation="routine_create",
        fingerprint=fingerprint,
        resource_id=routine.id,
    )
    return await get_routine(session, user_id, resource_id)


async def update_routine(
    session: AsyncSession, user_id: uuid.UUID, routine_id: uuid.UUID, body: RoutineWrite
) -> RoutineOut:
    if body.expected_version is None:
        raise RoutineError(422, "expected_version is required when updating a routine")
    fingerprint = mutation_fingerprint(body)
    replay = await _replay(session, user_id, body.client_mutation_id, "routine_update", fingerprint)
    if replay is not None:
        if replay.resource_id != routine_id:
            raise RoutineError(409, "client_mutation_id belongs to another routine")
        return await get_routine(session, user_id, routine_id)
    await _owned_routine(session, user_id, routine_id, active=True)
    await _validated_products(session, [item.food_item_id for item in body.items])
    changed = await session.execute(
        update(MealRoutine)
        .where(
            MealRoutine.id == routine_id,
            MealRoutine.user_id == user_id,
            MealRoutine.archived_at.is_(None),
            MealRoutine.version == body.expected_version,
        )
        .values(
            title=body.title,
            mode=body.mode,
            rough_text=body.rough_text,
            version=MealRoutine.version + 1,
            updated_at=datetime.now(UTC),
        )
    )
    if changed.rowcount != 1:
        await session.rollback()
        replay = await _replay(
            session, user_id, body.client_mutation_id, "routine_update", fingerprint
        )
        if replay is not None and replay.resource_id == routine_id:
            return await get_routine(session, user_id, routine_id)
        raise RoutineError(409, "routine version conflict")
    await session.execute(delete(MealRoutineItem).where(MealRoutineItem.routine_id == routine_id))
    for position, item in enumerate(body.items):
        session.add(
            MealRoutineItem(
                routine_id=routine_id,
                position=position,
                food_item_id=item.food_item_id,
                quantity_g=item.quantity_g,
            )
        )
    resource_id = await _commit_mutation(
        session,
        user_id=user_id,
        client_mutation_id=body.client_mutation_id,
        operation="routine_update",
        fingerprint=fingerprint,
        resource_id=routine_id,
    )
    return await get_routine(session, user_id, resource_id)


async def archive_routine(
    session: AsyncSession, user_id: uuid.UUID, routine_id: uuid.UUID, body: RoutineArchive
) -> RoutineOut:
    fingerprint = mutation_fingerprint(body)
    replay = await _replay(
        session, user_id, body.client_mutation_id, "routine_archive", fingerprint
    )
    if replay is not None:
        if replay.resource_id != routine_id:
            raise RoutineError(409, "client_mutation_id belongs to another routine")
        return await get_routine(session, user_id, routine_id)
    await _owned_routine(session, user_id, routine_id, active=True)
    now = datetime.now(UTC)
    changed = await session.execute(
        update(MealRoutine)
        .where(
            MealRoutine.id == routine_id,
            MealRoutine.user_id == user_id,
            MealRoutine.archived_at.is_(None),
            MealRoutine.version == body.expected_version,
        )
        .values(archived_at=now, version=MealRoutine.version + 1, updated_at=now)
    )
    if changed.rowcount != 1:
        await session.rollback()
        replay = await _replay(
            session, user_id, body.client_mutation_id, "routine_archive", fingerprint
        )
        if replay is not None and replay.resource_id == routine_id:
            return await get_routine(session, user_id, routine_id)
        raise RoutineError(409, "routine version conflict")
    schedule_ids = select(MealSchedule.id).where(
        MealSchedule.routine_id == routine_id, MealSchedule.user_id == user_id
    )
    await session.execute(
        update(MealSchedule)
        .where(MealSchedule.id.in_(schedule_ids))
        .values(enabled=False, version=MealSchedule.version + 1, updated_at=now)
    )
    occurrence_ids = select(MealOccurrence.id).where(MealOccurrence.schedule_id.in_(schedule_ids))
    await session.execute(
        update(NotificationIntent)
        .where(
            NotificationIntent.occurrence_id.in_(occurrence_ids),
            NotificationIntent.cancelled_at.is_(None),
        )
        .values(cancelled_at=now)
    )
    await _commit_mutation(
        session,
        user_id=user_id,
        client_mutation_id=body.client_mutation_id,
        operation="routine_archive",
        fingerprint=fingerprint,
        resource_id=routine_id,
    )
    return await get_routine(session, user_id, routine_id)


async def _schedule_out(session: AsyncSession, schedule: MealSchedule) -> ScheduleOut:
    weekdays = (
        await session.execute(
            select(MealScheduleWeekday.iso_weekday)
            .where(MealScheduleWeekday.schedule_id == schedule.id)
            .order_by(MealScheduleWeekday.iso_weekday)
        )
    ).scalars().all()
    return ScheduleOut(
        id=schedule.id,
        routine_id=schedule.routine_id,
        local_time=schedule.local_time,
        timezone=schedule.timezone,
        frequency=schedule.frequency,
        interval=schedule.interval,
        iso_weekdays=list(weekdays),
        start_date=schedule.start_date,
        end_date=schedule.end_date,
        reminder_minutes=schedule.reminder_minutes,
        enabled=schedule.enabled,
        version=schedule.version,
    )


async def create_schedule(
    session: AsyncSession,
    user_id: uuid.UUID,
    routine_id: uuid.UUID,
    body: ScheduleCreate,
) -> ScheduleOut:
    fingerprint = mutation_fingerprint(body)
    replay = await _replay(
        session, user_id, body.client_mutation_id, "schedule_create", fingerprint
    )
    if replay is not None:
        schedule = await session.get(MealSchedule, replay.resource_id)
        if schedule is None or schedule.user_id != user_id or schedule.routine_id != routine_id:
            raise RoutineError(409, "idempotency record is inconsistent")
        return await _schedule_out(session, schedule)
    await _owned_routine(session, user_id, routine_id, active=True)
    schedule = MealSchedule(
        id=uuid.uuid4(),
        user_id=user_id,
        routine_id=routine_id,
        local_time=body.local_time.replace(tzinfo=None),
        timezone=body.timezone,
        frequency=body.frequency,
        interval=body.interval,
        start_date=body.start_date,
        end_date=body.end_date,
        reminder_minutes=body.reminder_minutes,
        enabled=True,
    )
    session.add(schedule)
    for weekday in body.iso_weekdays:
        session.add(MealScheduleWeekday(schedule_id=schedule.id, iso_weekday=weekday))
    resource_id = await _commit_mutation(
        session,
        user_id=user_id,
        client_mutation_id=body.client_mutation_id,
        operation="schedule_create",
        fingerprint=fingerprint,
        resource_id=schedule.id,
    )
    created = await session.get(MealSchedule, resource_id)
    if created is None:
        raise RoutineError(409, "idempotency record is inconsistent")
    return await _schedule_out(session, created)


async def list_schedules(
    session: AsyncSession, user_id: uuid.UUID, routine_id: uuid.UUID
) -> list[ScheduleOut]:
    await _owned_routine(session, user_id, routine_id)
    schedules = (
        await session.execute(
            select(MealSchedule)
            .where(MealSchedule.user_id == user_id, MealSchedule.routine_id == routine_id)
            .order_by(MealSchedule.created_at, MealSchedule.id)
        )
    ).scalars().all()
    return [await _schedule_out(session, schedule) for schedule in schedules]


async def change_schedule_state(
    session: AsyncSession, user_id: uuid.UUID, schedule_id: uuid.UUID, body: ScheduleStateChange
) -> ScheduleOut:
    fingerprint = mutation_fingerprint(body)
    replay = await _replay(session, user_id, body.client_mutation_id, "schedule_state", fingerprint)
    if replay is not None:
        if replay.resource_id != schedule_id:
            raise RoutineError(409, "client_mutation_id belongs to another schedule")
        schedule = await session.get(MealSchedule, schedule_id)
        if schedule is None or schedule.user_id != user_id:
            raise RoutineError(404, "schedule not found")
        return await _schedule_out(session, schedule)
    schedule = await session.get(MealSchedule, schedule_id)
    if schedule is None or schedule.user_id != user_id:
        raise RoutineError(404, "schedule not found")
    now = datetime.now(UTC)
    changed = await session.execute(
        update(MealSchedule)
        .where(
            MealSchedule.id == schedule_id,
            MealSchedule.user_id == user_id,
            MealSchedule.version == body.expected_version,
        )
        .values(enabled=body.enabled, version=MealSchedule.version + 1, updated_at=now)
    )
    if changed.rowcount != 1:
        await session.rollback()
        replay = await _replay(
            session, user_id, body.client_mutation_id, "schedule_state", fingerprint
        )
        if replay is not None and replay.resource_id == schedule_id:
            current = await session.get(MealSchedule, schedule_id)
            if current is not None and current.user_id == user_id:
                return await _schedule_out(session, current)
        raise RoutineError(409, "schedule version conflict")
    if body.enabled:
        occurrence_ids = select(MealOccurrence.id).where(
            MealOccurrence.schedule_id == schedule_id,
            MealOccurrence.user_id == user_id,
            MealOccurrence.status == "scheduled",
        )
        await session.execute(
            update(NotificationIntent)
            .where(
                NotificationIntent.occurrence_id.in_(occurrence_ids),
                NotificationIntent.scheduled_for > now,
                NotificationIntent.expires_at > now,
                NotificationIntent.user_id == user_id,
            )
            .values(cancelled_at=None)
        )
    else:
        occurrence_ids = select(MealOccurrence.id).where(
            MealOccurrence.schedule_id == schedule_id,
            MealOccurrence.user_id == user_id,
        )
        await session.execute(
            update(NotificationIntent)
            .where(
                NotificationIntent.occurrence_id.in_(occurrence_ids),
                NotificationIntent.user_id == user_id,
                NotificationIntent.cancelled_at.is_(None),
            )
            .values(cancelled_at=now)
        )
    resource_id = await _commit_mutation(
        session,
        user_id=user_id,
        client_mutation_id=body.client_mutation_id,
        operation="schedule_state",
        fingerprint=fingerprint,
        resource_id=schedule_id,
    )
    result = await session.get(MealSchedule, resource_id)
    if result is None:
        raise RoutineError(409, "idempotency record is inconsistent")
    return await _schedule_out(session, result)


async def _generate_occurrences(
    session: AsyncSession,
    user_id: uuid.UUID,
    display_timezone: str,
    start: date,
    end: date,
) -> tuple[datetime, datetime]:
    display_zone = ZoneInfo(display_timezone)
    range_start = datetime.combine(start, time.min, tzinfo=display_zone).astimezone(UTC)
    range_end = datetime.combine(
        end + timedelta(days=1), time.min, tzinfo=display_zone
    ).astimezone(UTC)
    schedules = (
        await session.execute(
            select(MealSchedule)
            .join(MealRoutine, MealRoutine.id == MealSchedule.routine_id)
            .where(
                MealSchedule.user_id == user_id,
                MealSchedule.enabled.is_(True),
                MealRoutine.archived_at.is_(None),
            )
        )
    ).scalars().all()
    if not schedules:
        return range_start, range_end
    schedule_ids = [schedule.id for schedule in schedules]
    weekday_rows = (
        await session.execute(
            select(MealScheduleWeekday.schedule_id, MealScheduleWeekday.iso_weekday).where(
                MealScheduleWeekday.schedule_id.in_(schedule_ids)
            )
        )
    ).all()
    weekdays: dict[uuid.UUID, list[int]] = {schedule_id: [] for schedule_id in schedule_ids}
    for schedule_id, weekday in weekday_rows:
        weekdays[schedule_id].append(weekday)
    existing = set(
        (
            await session.execute(
                select(MealOccurrence.schedule_id, MealOccurrence.scheduled_local_date).where(
                    MealOccurrence.schedule_id.in_(schedule_ids),
                    MealOccurrence.scheduled_local_date >= start - timedelta(days=2),
                    MealOccurrence.scheduled_local_date <= end + timedelta(days=2),
                )
            )
        ).all()
    )
    for schedule in schedules:
        schedule_zone = ZoneInfo(schedule.timezone)
        local_start = (range_start.astimezone(schedule_zone) - timedelta(days=1)).date()
        local_end = (range_end.astimezone(schedule_zone) + timedelta(days=1)).date()
        dates = recurrence_dates(
            frequency=schedule.frequency,
            interval=schedule.interval,
            iso_weekdays=weekdays[schedule.id],
            start_date=schedule.start_date,
            end_date=schedule.end_date,
            range_start=local_start,
            range_end=local_end,
        )
        for local_date in dates:
            if (schedule.id, local_date) in existing:
                continue
            scheduled_at, resolution = resolve_wall_clock(
                local_date, schedule.local_time, schedule.timezone
            )
            if not range_start <= scheduled_at < range_end:
                continue
            occurrence_id = uuid.uuid4()
            inserted_id = (
                await session.execute(
                    pg_insert(MealOccurrence)
                    .values(
                        id=occurrence_id,
                        user_id=user_id,
                        schedule_id=schedule.id,
                        scheduled_local_date=local_date,
                        scheduled_at=scheduled_at,
                        time_resolution=resolution,
                        status="scheduled",
                    )
                    .on_conflict_do_nothing(
                        constraint="uq_occurrence_schedule_day"
                    )
                    .returning(MealOccurrence.id)
                )
            ).scalar_one_or_none()
            if inserted_id is not None and schedule.reminder_minutes is not None:
                session.add(
                    NotificationIntent(
                        user_id=user_id,
                        occurrence_id=inserted_id,
                        kind="meal_reminder",
                        scheduled_for=scheduled_at - timedelta(minutes=schedule.reminder_minutes),
                        expires_at=scheduled_at + timedelta(days=1),
                    )
                )
    await session.commit()
    return range_start, range_end


async def generate_notification_horizon(
    session: AsyncSession,
    *,
    now: datetime,
    days: int = 2,
) -> None:
    """Materialize reminders without relying on a user opening the agenda."""
    profiles = (
        await session.execute(
            select(UserProfile)
            .join(MealSchedule, MealSchedule.user_id == UserProfile.id)
            .join(MealRoutine, MealRoutine.id == MealSchedule.routine_id)
            .where(
                MealSchedule.enabled.is_(True),
                MealSchedule.reminder_minutes.is_not(None),
                MealRoutine.archived_at.is_(None),
            )
            .distinct()
        )
    ).scalars().all()
    for profile in profiles:
        local_today = now.astimezone(ZoneInfo(profile.timezone)).date()
        await _generate_occurrences(
            session,
            profile.id,
            profile.timezone,
            local_today,
            local_today + timedelta(days=days),
        )


async def get_agenda(
    session: AsyncSession,
    profile: UserProfile,
    *,
    start: date,
    end: date,
    now: datetime | None = None,
) -> AgendaOut:
    if end < start:
        raise RoutineError(422, "end must be on or after start")
    if (end - start).days + 1 > MAX_AGENDA_DAYS:
        raise RoutineError(422, f"agenda ranges are limited to {MAX_AGENDA_DAYS} days")
    server_now = (now or datetime.now(UTC)).astimezone(UTC)
    range_start, range_end = await _generate_occurrences(
        session, profile.id, profile.timezone, start, end
    )
    rows = (
        await session.execute(
            select(MealOccurrence, MealSchedule, MealRoutine)
            .join(MealSchedule, MealSchedule.id == MealOccurrence.schedule_id)
            .join(MealRoutine, MealRoutine.id == MealSchedule.routine_id)
            .where(
                MealSchedule.user_id == profile.id,
                MealOccurrence.scheduled_at >= range_start,
                MealOccurrence.scheduled_at < range_end,
                or_(MealSchedule.enabled.is_(True), MealOccurrence.status != "scheduled"),
            )
            .order_by(MealOccurrence.scheduled_at, MealOccurrence.id)
        )
    ).all()
    occurrences: list[OccurrenceOut] = []
    next_due_at: datetime | None = None
    for occurrence, schedule, routine in rows:
        state = occurrence_state(occurrence, server_now, schedule.timezone)
        occurrences.append(
            OccurrenceOut(
                id=occurrence.id,
                routine=await _routine_out(session, routine),
                schedule_id=schedule.id,
                scheduled_at=occurrence.scheduled_at,
                scheduled_local_date=occurrence.scheduled_local_date,
                schedule_timezone=schedule.timezone,
                time_resolution=occurrence.time_resolution,
                status=occurrence.status,
                state=state,
            )
        )
        if state in {"due", "upcoming"} and next_due_at is None:
            next_due_at = occurrence.scheduled_at
    countdown = (
        None
        if next_due_at is None
        else max(0, int((next_due_at - server_now).total_seconds()))
    )
    return AgendaOut(
        server_now=server_now,
        display_timezone=profile.timezone,
        occurrences=occurrences,
        next_due_at=next_due_at,
        countdown_seconds=countdown,
    )


async def _owned_occurrence(
    session: AsyncSession, user_id: uuid.UUID, occurrence_id: uuid.UUID
) -> MealOccurrence:
    occurrence = (
        await session.execute(
            select(MealOccurrence)
            .where(MealOccurrence.id == occurrence_id, MealOccurrence.user_id == user_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if occurrence is None:
        raise RoutineError(404, "occurrence not found")
    return occurrence


async def _occurrence_out(
    session: AsyncSession, user_id: uuid.UUID, occurrence_id: uuid.UUID, now: datetime
) -> OccurrenceOut:
    row = (
        await session.execute(
            select(MealOccurrence, MealSchedule, MealRoutine)
            .join(MealSchedule, MealSchedule.id == MealOccurrence.schedule_id)
            .join(MealRoutine, MealRoutine.id == MealSchedule.routine_id)
            .where(MealOccurrence.id == occurrence_id, MealSchedule.user_id == user_id)
        )
    ).one_or_none()
    if row is None:
        raise RoutineError(404, "occurrence not found")
    occurrence, schedule, routine = row
    return OccurrenceOut(
        id=occurrence.id,
        routine=await _routine_out(session, routine),
        schedule_id=schedule.id,
        scheduled_at=occurrence.scheduled_at,
        scheduled_local_date=occurrence.scheduled_local_date,
        schedule_timezone=schedule.timezone,
        time_resolution=occurrence.time_resolution,
        status=occurrence.status,
        state=occurrence_state(occurrence, now, schedule.timezone),
    )


async def complete_occurrence(
    session: AsyncSession,
    user_id: uuid.UUID,
    occurrence_id: uuid.UUID,
    body: OccurrenceComplete,
) -> OccurrenceOut:
    fingerprint = mutation_fingerprint(body)
    replay = await _replay(
        session, user_id, body.client_mutation_id, "occurrence_complete", fingerprint
    )
    if replay is not None:
        if replay.resource_id != occurrence_id:
            raise RoutineError(409, "client_mutation_id belongs to another occurrence")
        return await _occurrence_out(session, user_id, occurrence_id, datetime.now(UTC))
    occurrence = await _owned_occurrence(session, user_id, occurrence_id)
    if occurrence.status != "scheduled":
        replay = await _replay(
            session, user_id, body.client_mutation_id, "occurrence_complete", fingerprint
        )
        if replay is not None and replay.resource_id == occurrence_id:
            return await _occurrence_out(session, user_id, occurrence_id, datetime.now(UTC))
        raise RoutineError(409, f"occurrence is already {occurrence.status}")
    mutations = (
        await session.execute(
            select(MealLogMutation, MealLog)
            .join(MealLog, MealLog.id == MealLogMutation.meal_log_id)
            .where(
                MealLogMutation.user_id == user_id,
                MealLogMutation.client_mutation_id.in_(body.meal_log_client_mutation_ids),
                MealLog.user_id == user_id,
            )
        )
    ).all()
    by_mutation = {mutation.client_mutation_id: log for mutation, log in mutations}
    if len(by_mutation) != len(body.meal_log_client_mutation_ids):
        raise RoutineError(422, "all meal mutation IDs must resolve to current-user meal logs")
    linked = (
        await session.execute(
            select(MealOccurrenceLog.meal_log_id).where(
                MealOccurrenceLog.meal_log_id.in_([log.id for log in by_mutation.values()])
            )
        )
    ).scalars().first()
    if linked is not None:
        raise RoutineError(409, "a meal log is already linked to an occurrence")
    for position, mutation_id in enumerate(body.meal_log_client_mutation_ids):
        session.add(
            MealOccurrenceLog(
                occurrence_id=occurrence.id,
                meal_log_id=by_mutation[mutation_id].id,
                user_id=user_id,
                position=position,
            )
        )
    occurrence.status = "completed"
    occurrence.acted_at = body.confirmed_at.astimezone(UTC)
    await session.execute(
        update(NotificationIntent)
        .where(
            NotificationIntent.occurrence_id == occurrence.id,
            NotificationIntent.cancelled_at.is_(None),
        )
        .values(cancelled_at=datetime.now(UTC))
    )
    await _commit_mutation(
        session,
        user_id=user_id,
        client_mutation_id=body.client_mutation_id,
        operation="occurrence_complete",
        fingerprint=fingerprint,
        resource_id=occurrence.id,
    )
    return await _occurrence_out(session, user_id, occurrence_id, datetime.now(UTC))


async def skip_occurrence(
    session: AsyncSession,
    user_id: uuid.UUID,
    occurrence_id: uuid.UUID,
    body: OccurrenceSkip,
) -> OccurrenceOut:
    fingerprint = mutation_fingerprint(body)
    replay = await _replay(
        session, user_id, body.client_mutation_id, "occurrence_skip", fingerprint
    )
    if replay is not None:
        if replay.resource_id != occurrence_id:
            raise RoutineError(409, "client_mutation_id belongs to another occurrence")
        return await _occurrence_out(session, user_id, occurrence_id, datetime.now(UTC))
    occurrence = await _owned_occurrence(session, user_id, occurrence_id)
    if occurrence.status != "scheduled":
        replay = await _replay(
            session, user_id, body.client_mutation_id, "occurrence_skip", fingerprint
        )
        if replay is not None and replay.resource_id == occurrence_id:
            return await _occurrence_out(session, user_id, occurrence_id, datetime.now(UTC))
        raise RoutineError(409, f"occurrence is already {occurrence.status}")
    occurrence.status = "skipped"
    occurrence.acted_at = body.acted_at.astimezone(UTC)
    await session.execute(
        update(NotificationIntent)
        .where(
            NotificationIntent.occurrence_id == occurrence.id,
            NotificationIntent.cancelled_at.is_(None),
        )
        .values(cancelled_at=datetime.now(UTC))
    )
    await _commit_mutation(
        session,
        user_id=user_id,
        client_mutation_id=body.client_mutation_id,
        operation="occurrence_skip",
        fingerprint=fingerprint,
        resource_id=occurrence.id,
    )
    return await _occurrence_out(session, user_id, occurrence_id, datetime.now(UTC))
