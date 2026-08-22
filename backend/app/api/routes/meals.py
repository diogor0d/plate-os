"""Meal log CRUD + timezone-correct daily rollups.

INVARIANT (decision D14): daily budgets group by the user's LOCAL midnight in
their profile timezone (IANA name), never by UTC date_trunc. Bounds are
computed with zoneinfo and compared against timestamptz instants.
"""

import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_profile
from app.db import get_session
from app.models import FoodItem, MealLog, UserProfile
from app.schemas.api import DailySummary, MealLogCreate, MealLogOut, MealLogPatch
from app.schemas.llm_contracts import Per100Values
from app.services.nutrition import MACRO_FIELDS, scale_to_quantity

router = APIRouter(prefix="/api", tags=["meals"])


def day_bounds(day: str, tz_name: str) -> tuple[datetime, datetime]:
    tz = ZoneInfo(tz_name)
    d = date.fromisoformat(day)
    start = datetime.combine(d, time.min, tzinfo=tz)
    return start, start + timedelta(days=1)


def _today(tz_name: str) -> str:
    return datetime.now(ZoneInfo(tz_name)).date().isoformat()


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
    session: AsyncSession, profile: UserProfile, day: str
) -> dict[str, float]:
    start, end = day_bounds(day, profile.timezone)
    return await _consumed_between(session, profile.id, start, end)


@router.get("/meal-logs", response_model=list[MealLogOut])
async def list_meal_logs(
    day: str | None = None,
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


@router.post("/meal-logs", response_model=MealLogOut, status_code=201)
async def create_meal_log(
    body: MealLogCreate,
    profile: UserProfile = Depends(get_current_profile),
    session: AsyncSession = Depends(get_session),
):
    """Persist a (confirmed) meal entry. Totals are computed HERE from the
    per-100g density; client-sent totals are never accepted."""

    if body.food_item_id is not None:
        item = await session.get(FoodItem, body.food_item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="food_item not found")
        per100 = Per100Values(
            calories=float(item.calories_per_100),
            protein_g=float(item.protein_per_100),
            carbs_g=float(item.carbs_per_100),
            fat_g=float(item.fat_per_100),
            fiber_g=float(item.fiber_per_100),
        )
    elif body.per100 is not None:
        per100 = body.per100
    else:
        raise HTTPException(
            status_code=422,
            detail="Provide food_item_id or per100 values for a custom item",
        )

    totals = scale_to_quantity(per100, body.quantity_g)
    log = MealLog(
        user_id=profile.id,
        food_item_id=body.food_item_id,
        custom_name=body.custom_name,
        logged_at=body.logged_at or datetime.now(timezone.utc),
        quantity_g=body.quantity_g,
        calculated_calories=totals["calories"],
        calculated_protein=totals["protein_g"],
        calculated_carbs=totals["carbs_g"],
        calculated_fat=totals["fat_g"],
        calculated_fiber=totals["fiber_g"],
        source_type=body.source_type,
    )
    session.add(log)
    await session.commit()
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
        # Rescale proportionally from the stored totals (density-consistent).
        factor = body.quantity_g / float(log.quantity_g) if float(log.quantity_g) else 0.0
        log.calculated_calories = round(float(log.calculated_calories) * factor, 1)
        log.calculated_protein = round(float(log.calculated_protein) * factor, 1)
        log.calculated_carbs = round(float(log.calculated_carbs) * factor, 1)
        log.calculated_fat = round(float(log.calculated_fat) * factor, 1)
        log.calculated_fiber = round(float(log.calculated_fiber) * factor, 1)
        log.quantity_g = body.quantity_g

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
    result = await session.execute(
        delete(MealLog).where(MealLog.id == log_id, MealLog.user_id == profile.id)
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="meal log not found")
    await session.commit()


@router.get("/daily-summary", response_model=DailySummary)
async def daily_summary(
    day: str | None = None,
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
        date=day,
        timezone=profile.timezone,
        targets=targets,
        consumed=consumed,
        remaining=remaining,
    )
