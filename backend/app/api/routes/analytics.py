"""Filtered, timezone-correct analytics for the Stats view."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_profile
from app.db import get_session
from app.models import UserProfile
from app.schemas.api import AnalyticsResponse, SourceType
from app.services.analytics import get_analytics, resolve_range

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/daily", response_model=AnalyticsResponse)
async def daily_history(
    days: Annotated[int | None, Query(ge=1, le=366)] = None,
    start: date | None = None,
    end: date | None = None,
    source_type: Annotated[list[SourceType] | None, Query()] = None,
    q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    profile: UserProfile = Depends(get_current_profile),
    session: AsyncSession = Depends(get_session),
):
    try:
        analytics_range = resolve_range(
            profile.timezone, days=days, start=start, end=end
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await get_analytics(
        session,
        profile,
        analytics_range,
        list(source_type or []),
        q.strip() if q else None,
    )
