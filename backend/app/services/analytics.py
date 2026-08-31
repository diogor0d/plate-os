"""Timezone-correct, user-scoped analytics aggregation."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.meals import day_bounds
from app.models import FoodItem, MealLog, UserProfile
from app.schemas.api import (
    AnalyticsFoodBreakdown,
    AnalyticsResponse,
    AnalyticsSourceBreakdown,
    AnalyticsSummary,
    AnalyticsTargets,
    DayTotals,
)

MAX_ANALYTICS_DAYS = 366


@dataclass(frozen=True)
class AnalyticsRange:
    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def resolve_range(
    tz_name: str,
    *,
    days: int | None,
    start: date | None,
    end: date | None,
    now: datetime | None = None,
) -> AnalyticsRange:
    if days is not None and (start is not None or end is not None):
        raise ValueError("Choose a preset range or custom dates, not both")
    if (start is None) != (end is None):
        raise ValueError("Both start and end dates are required")

    if start is not None and end is not None:
        if end < start:
            raise ValueError("End date must be on or after start date")
        result = AnalyticsRange(start, end)
    else:
        effective_days = days or 30
        today = (now or datetime.now(ZoneInfo(tz_name))).astimezone(ZoneInfo(tz_name)).date()
        result = AnalyticsRange(today - timedelta(days=effective_days - 1), today)

    if result.days > MAX_ANALYTICS_DAYS:
        raise ValueError(f"Analytics ranges are limited to {MAX_ANALYTICS_DAYS} days")
    return result


def summarize(history: list[DayTotals]) -> AnalyticsSummary:
    calendar_days = len(history)
    active_days = sum(day.meal_count > 0 for day in history)
    meal_count = sum(day.meal_count for day in history)
    calories = sum(day.calories for day in history)
    protein = sum(day.protein_g for day in history)
    fiber = sum(day.fiber_g for day in history)

    def average(value: float, denominator: int) -> float:
        return round(value / denominator, 1) if denominator else 0.0

    return AnalyticsSummary(
        meal_count=meal_count,
        active_days=active_days,
        calendar_days=calendar_days,
        avg_meals_per_active_day=average(meal_count, active_days),
        avg_calories_per_day=average(calories, calendar_days),
        avg_calories_per_active_day=average(calories, active_days),
        avg_protein_g_per_day=average(protein, calendar_days),
        avg_fiber_g_per_day=average(fiber, calendar_days),
    )


def _with_food_filter(stmt: Select, food_query: str | None) -> Select:
    if not food_query:
        return stmt
    escaped = food_query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return stmt.where(
        or_(
            MealLog.custom_name.ilike(f"%{escaped}%", escape="\\"),
            FoodItem.name.ilike(f"%{escaped}%", escape="\\"),
        )
    )


async def get_analytics(
    session: AsyncSession,
    profile: UserProfile,
    analytics_range: AnalyticsRange,
    source_types: list[str],
    food_query: str | None,
) -> AnalyticsResponse:
    tz_name = profile.timezone
    start_instant, _ = day_bounds(analytics_range.start, tz_name)
    _, end_exclusive = day_bounds(analytics_range.end, tz_name)
    base_filters = [
        MealLog.user_id == profile.id,
        MealLog.logged_at >= start_instant,
        MealLog.logged_at < end_exclusive,
    ]
    if source_types:
        base_filters.append(MealLog.source_type.in_(source_types))

    local_day = func.to_char(func.timezone(tz_name, MealLog.logged_at), "YYYY-MM-DD")
    daily_stmt = (
        select(
            local_day.label("day"),
            func.count(MealLog.id),
            func.coalesce(func.sum(MealLog.calculated_calories), 0.0),
            func.coalesce(func.sum(MealLog.calculated_protein), 0.0),
            func.coalesce(func.sum(MealLog.calculated_carbs), 0.0),
            func.coalesce(func.sum(MealLog.calculated_fat), 0.0),
            func.coalesce(func.sum(MealLog.calculated_fiber), 0.0),
        )
        .select_from(MealLog)
        .outerjoin(FoodItem, MealLog.food_item_id == FoodItem.id)
        .where(*base_filters)
        .group_by(local_day)
    )
    daily_stmt = _with_food_filter(daily_stmt, food_query)
    daily_rows = (await session.execute(daily_stmt)).all()
    by_day = {row[0]: [int(row[1]), *(float(value) for value in row[2:])] for row in daily_rows}

    history: list[DayTotals] = []
    for offset in range(analytics_range.days):
        day = (analytics_range.start + timedelta(days=offset)).isoformat()
        values = by_day.get(day, [0, 0.0, 0.0, 0.0, 0.0, 0.0])
        history.append(
            DayTotals(
                date=day,
                meal_count=values[0],
                calories=values[1],
                protein_g=values[2],
                carbs_g=values[3],
                fat_g=values[4],
                fiber_g=values[5],
            )
        )

    source_stmt = (
        select(
            MealLog.source_type,
            func.count(MealLog.id),
            func.coalesce(func.sum(MealLog.calculated_calories), 0.0),
        )
        .select_from(MealLog)
        .outerjoin(FoodItem, MealLog.food_item_id == FoodItem.id)
        .where(*base_filters)
        .group_by(MealLog.source_type)
        .order_by(func.count(MealLog.id).desc(), MealLog.source_type)
    )
    source_stmt = _with_food_filter(source_stmt, food_query)
    source_rows = (await session.execute(source_stmt)).all()

    display_name = func.coalesce(MealLog.custom_name, FoodItem.name, "Unknown food")
    food_stmt = (
        select(
            display_name.label("name"),
            func.count(MealLog.id),
            func.coalesce(func.sum(MealLog.quantity_g), 0.0),
            func.coalesce(func.sum(MealLog.calculated_calories), 0.0),
            func.coalesce(func.sum(MealLog.calculated_protein), 0.0),
        )
        .select_from(MealLog)
        .outerjoin(FoodItem, MealLog.food_item_id == FoodItem.id)
        .where(*base_filters)
        .group_by(display_name)
        .order_by(func.sum(MealLog.calculated_calories).desc(), display_name)
        .limit(10)
    )
    food_stmt = _with_food_filter(food_stmt, food_query)
    food_rows = (await session.execute(food_stmt)).all()

    window = history[-7:]
    rolling = round(sum(day.calories for day in window) / len(window), 1) if window else 0.0
    return AnalyticsResponse(
        timezone=tz_name,
        start_date=analytics_range.start,
        end_date=analytics_range.end,
        days=analytics_range.days,
        targets=AnalyticsTargets(
            calories=profile.target_calories,
            protein_g=profile.target_protein_g,
            carbs_g=profile.target_carbs_g,
            fat_g=profile.target_fat_g,
        ),
        summary=summarize(history),
        history=history,
        source_breakdown=[
            AnalyticsSourceBreakdown(
                source_type=row[0], meal_count=int(row[1]), calories=float(row[2])
            )
            for row in source_rows
        ],
        top_foods=[
            AnalyticsFoodBreakdown(
                name=row[0],
                meal_count=int(row[1]),
                quantity_g=float(row[2]),
                calories=float(row[3]),
                protein_g=float(row[4]),
            )
            for row in food_rows
        ],
        rolling_avg_calories_7d=rolling,
    )
