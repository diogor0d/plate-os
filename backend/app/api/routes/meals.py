"""Meal log CRUD + timezone-correct daily rollups.

INVARIANT (decision D14): daily budgets group by the user's LOCAL midnight in
their profile timezone (IANA name), never by UTC date_trunc. Bounds are
computed with zoneinfo and compared against timestamptz instants.
"""

import hashlib
import json
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_profile
from app.db import get_session
from app.models import FoodItem, MealLog, MealLogMutation, MealOccurrenceLog, UserProfile
from app.schemas.api import DailySummary, MealLogCreate, MealLogOut, MealLogPatch
from app.services.nutrition import (
    MACRO_FIELDS,
    canonical_density_values,
    canonical_quantity,
    scale_density_values,
)

router = APIRouter(prefix="/api", tags=["meals"])


def day_bounds(day: date, tz_name: str) -> tuple[datetime, datetime]:
    tz = ZoneInfo(tz_name)
    start = datetime.combine(day, time.min, tzinfo=tz)
    return start, start + timedelta(days=1)


def _today(tz_name: str) -> date:
    return datetime.now(ZoneInfo(tz_name)).date()


async def _consumed_between(
    session: AsyncSession, user_id: uuid.UUID, start: datetime, end: datetime
) -> dict[str, float]:
    stmt = select(
        func.coalesce(func.sum(MealLog.calculated_calories), 0.0),
        func.coalesce(func.sum(MealLog.calculated_protein), 0.0),
        func.coalesce(func.sum(MealLog.calculated_carbs), 0.0),
        func.coalesce(func.sum(MealLog.calculated_fat), 0.0),
        func.coalesce(func.sum(MealLog.calculated_fiber), 0.0),
    ).where(MealLog.user_id == user_id, MealLog.logged_at >= start, MealLog.logged_at < end)
    row = (await session.execute(stmt)).one()
    return dict(zip(MACRO_FIELDS, (float(v) for v in row)))


async def consumed_for_day(
    session: AsyncSession, profile: UserProfile, day: date
) -> dict[str, float]:
    start, end = day_bounds(day, profile.timezone)
    return await _consumed_between(session, profile.id, start, end)


@router.get("/meal-logs", response_model=list[MealLogOut])
async def list_meal_logs(
    day: date | None = None,
    profile: UserProfile = Depends(get_current_profile),
    session: AsyncSession = Depends(get_session),
):
    day = day or _today(profile.timezone)
    start, end = day_bounds(day, profile.timezone)
    stmt = (
        select(MealLog)
        .where(MealLog.user_id == profile.id, MealLog.logged_at >= start, MealLog.logged_at < end)
        .order_by(MealLog.logged_at.desc())
    )
    return (await session.execute(stmt)).scalars().all()


def _request_fingerprint(body: MealLogCreate) -> str:
    payload = body.model_dump(mode="json", exclude={"client_mutation_id"})
    if body.logged_at is not None:
        payload["logged_at"] = body.logged_at.astimezone(timezone.utc).isoformat()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


async def _replay_mutation(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    client_mutation_id: uuid.UUID,
    request_fingerprint: str,
) -> MealLog | None:
    mutation = await session.get(
        MealLogMutation,
        {"user_id": user_id, "client_mutation_id": client_mutation_id},
    )
    if mutation is None:
        return None
    if mutation.request_fingerprint != request_fingerprint:
        raise HTTPException(
            status_code=409,
            detail="client_mutation_id was already used with a different payload",
        )
    if mutation.meal_log_id is None:
        raise HTTPException(
            status_code=409,
            detail="client_mutation_id belongs to a meal log that was deleted",
        )
    log = await session.get(MealLog, mutation.meal_log_id)
    if log is None:
        raise HTTPException(status_code=409, detail="Idempotency record is inconsistent")
    return log


@router.post("/meal-logs", response_model=MealLogOut, status_code=201)
async def create_meal_log(
    body: MealLogCreate,
    profile: UserProfile = Depends(get_current_profile),
    session: AsyncSession = Depends(get_session),
    expected_owner_user_id: Annotated[
        str | None, Header(alias="X-PlateOS-Expected-User-ID")
    ] = None,
):
    """Persist a (confirmed) meal entry. Totals are computed HERE from the
    per-100g density; client-sent totals are never accepted."""

    if expected_owner_user_id is not None and expected_owner_user_id != str(profile.id):
        raise HTTPException(
            status_code=409,
            detail="Authenticated account does not match queued meal owner",
        )

    fingerprint: str | None = None
    if body.client_mutation_id is not None:
        fingerprint = _request_fingerprint(body)
        replay = await _replay_mutation(
            session,
            user_id=profile.id,
            client_mutation_id=body.client_mutation_id,
            request_fingerprint=fingerprint,
        )
        if replay is not None:
            return replay

    if body.food_item_id is not None:
        item = await session.get(FoodItem, body.food_item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="food_item not found")
        if item.archived_at is not None or item.accepted_at is None:
            raise HTTPException(status_code=409, detail="Archived products cannot be logged")
        density = {
            "calories": item.calories_per_100,
            "protein_g": item.protein_per_100,
            "carbs_g": item.carbs_per_100,
            "fat_g": item.fat_per_100,
            "fiber_g": item.fiber_per_100,
        }
    elif body.per100 is not None:
        density = canonical_density_values(body.per100)
    else:
        raise HTTPException(
            status_code=422,
            detail="Provide food_item_id or per100 values for a custom item",
        )

    quantity = canonical_quantity(body.quantity_g)
    totals = scale_density_values(density, quantity)
    log = MealLog(
        user_id=profile.id,
        food_item_id=body.food_item_id,
        custom_name=body.custom_name,
        logged_at=body.logged_at or datetime.now(timezone.utc),
        quantity_g=quantity,
        calories_per_100=density["calories"],
        protein_per_100=density["protein_g"],
        carbs_per_100=density["carbs_g"],
        fat_per_100=density["fat_g"],
        fiber_per_100=density["fiber_g"],
        calculated_calories=totals["calories"],
        calculated_protein=totals["protein_g"],
        calculated_carbs=totals["carbs_g"],
        calculated_fat=totals["fat_g"],
        calculated_fiber=totals["fiber_g"],
        source_type=body.source_type,
    )
    try:
        session.add(log)
        await session.flush()
        if body.client_mutation_id is not None and fingerprint is not None:
            session.add(
                MealLogMutation(
                    user_id=profile.id,
                    client_mutation_id=body.client_mutation_id,
                    request_fingerprint=fingerprint,
                    meal_log_id=log.id,
                )
            )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        if body.client_mutation_id is not None and fingerprint is not None:
            replay = await _replay_mutation(
                session,
                user_id=profile.id,
                client_mutation_id=body.client_mutation_id,
                request_fingerprint=fingerprint,
            )
            if replay is not None:
                return replay
        raise
    await session.refresh(log)
    return log


@router.patch("/meal-logs/{log_id}", response_model=MealLogOut)
async def update_meal_log(
    log_id: uuid.UUID,
    body: MealLogPatch,
    profile: UserProfile = Depends(get_current_profile),
    session: AsyncSession = Depends(get_session),
):
    log = await session.get(MealLog, log_id)
    if log is None or log.user_id != profile.id:
        raise HTTPException(status_code=404, detail="meal log not found")

    if body.logged_at is not None:
        log.logged_at = body.logged_at
    if body.quantity_g is not None:
        quantity = canonical_quantity(body.quantity_g)
        totals = scale_density_values(
            {
                "calories": log.calories_per_100,
                "protein_g": log.protein_per_100,
                "carbs_g": log.carbs_per_100,
                "fat_g": log.fat_per_100,
                "fiber_g": log.fiber_per_100,
            },
            quantity,
        )
        log.calculated_calories = totals["calories"]
        log.calculated_protein = totals["protein_g"]
        log.calculated_carbs = totals["carbs_g"]
        log.calculated_fat = totals["fat_g"]
        log.calculated_fiber = totals["fiber_g"]
        log.quantity_g = quantity

    session.add(log)
    await session.commit()
    await session.refresh(log)
    return log


@router.delete("/meal-logs/{log_id}", status_code=204)
async def delete_meal_log(
    log_id: uuid.UUID,
    profile: UserProfile = Depends(get_current_profile),
    session: AsyncSession = Depends(get_session),
):
    linked = await session.scalar(
        select(MealOccurrenceLog.occurrence_id).where(
            MealOccurrenceLog.meal_log_id == log_id,
            MealOccurrenceLog.user_id == profile.id,
        )
    )
    if linked is not None:
        raise HTTPException(status_code=409, detail="Meal log is linked to a routine occurrence")
    try:
        result = await session.execute(
            delete(MealLog).where(MealLog.id == log_id, MealLog.user_id == profile.id)
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="meal log not found")
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="Meal log is linked to a routine occurrence"
        ) from None


@router.get("/daily-summary", response_model=DailySummary)
async def daily_summary(
    day: date | None = None,
    profile: UserProfile = Depends(get_current_profile),
    session: AsyncSession = Depends(get_session),
):
    day = day or _today(profile.timezone)
    consumed = await consumed_for_day(session, profile, day)
    targets = {
        "calories": profile.target_calories,
        "protein_g": profile.target_protein_g,
        "carbs_g": profile.target_carbs_g,
        "fat_g": profile.target_fat_g,
    }
    remaining = {k: round(targets[k] - consumed[k], 1) for k in targets}
    return DailySummary(
        date=day.isoformat(),
        timezone=profile.timezone,
        targets=targets,
        consumed=consumed,
        remaining=remaining,
    )
