"""Rolling-window analytics for the Stats view (Phase 4).

One grouped query computes per-day totals in the USER's timezone via
Postgres' timezone() function (timestamptz -> local timestamp), then missing
days are zero-filled so the client always receives a contiguous series.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_profile
from app.api.routes.meals import day_bounds
from app.db import get_session
from app.models import MealLog, UserProfile
from app.schemas.api import AnalyticsResponse, DayTotals

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/daily", response_model=AnalyticsResponse)
async def daily_history(
    days: int = Query(default=14, ge=1, le=90),
    profile: UserProfile = Depends(get_current_profile),
    session: AsyncSession = Depends(get_session),
):
    tz_name = profile.timezone
    today = datetime.now(ZoneInfo(tz_name)).date()
    first_day = today - timedelta(days=days - 1)
    start, _ = day_bounds(first_day, tz_name)

    local_day = func.to_char(func.timezone(tz_name, MealLog.logged_at), "YYYY-MM-DD")
    stmt = select(
        local_day.label("day"),
        func.coalesce(func.sum(MealLog.calculated_calories), 0.0),
        func.coalesce(func.sum(MealLog.calculated_protein), 0.0),
        func.coalesce(func.sum(MealLog.calculated_carbs), 0.0),
        func.coalesce(func.sum(MealLog.calculated_fat), 0.0),
        func.coalesce(func.sum(MealLog.calculated_fiber), 0.0),
    ).where(MealLog.user_id == profile.id, MealLog.logged_at >= start).group_by(local_day)
    rows = (await session.execute(stmt)).all()
    by_day = {row[0]: [float(v) for v in row[1:]] for row in rows}

    history: list[DayTotals] = []
    for offset in range(days):
        day = (first_day + timedelta(days=offset)).isoformat()
        vals = by_day.get(day, [0.0] * 5)
        history.append(
            DayTotals(
                date=day,
                calories=vals[0],
                protein_g=vals[1],
                carbs_g=vals[2],
                fat_g=vals[3],
                fiber_g=vals[4],
            )
        )

    window = history[-7:]
    rolling = round(sum(d.calories for d in window) / len(window)) if window else 0.0

    return AnalyticsResponse(
        timezone=tz_name,
        days=days,
        targets={
            "calories": profile.target_calories,
            "protein_g": profile.target_protein_g,
            "carbs_g": profile.target_carbs_g,
            "fat_g": profile.target_fat_g,
        },
        history=history,
        rolling_avg_calories_7d=rolling,
    )
