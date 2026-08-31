"""Build bounded, typed-by-construction facts for the assistant harness."""

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.meals import consumed_for_day
from app.models import FoodItem, MealLog, UserProfile
from app.schemas.api import ChatRequest
from app.services.analytics import get_analytics, resolve_range


async def build_assistant_context(
    session: AsyncSession, profile: UserProfile, request: ChatRequest
) -> dict:
    now = datetime.now(ZoneInfo(profile.timezone))
    consumed = await consumed_for_day(session, profile, now.date())
    targets = {
        "target_calories": profile.target_calories,
        "target_protein_g": profile.target_protein_g,
        "target_carbs_g": profile.target_carbs_g,
        "target_fat_g": profile.target_fat_g,
    }
    remaining = {
        "calories": profile.target_calories - consumed["calories"],
        "protein_g": profile.target_protein_g - consumed["protein_g"],
        "carbs_g": profile.target_carbs_g - consumed["carbs_g"],
        "fat_g": profile.target_fat_g - consumed["fat_g"],
    }

    context = {
        "schema_version": "1",
        "mode": request.mode,
        "surface": request.surface,
        "local_now": now.isoformat(),
        "timezone": profile.timezone,
        "current_targets": targets,
        "today": {
            "consumed": consumed,
            "remaining": remaining,
        },
        "limitations": ["current_targets_are_not_historical"],
    }

    if request.mode == "coach":
        recent_stmt = (
            select(MealLog, FoodItem.name)
            .outerjoin(FoodItem, MealLog.food_item_id == FoodItem.id)
            .where(MealLog.user_id == profile.id)
            .order_by(MealLog.logged_at.desc())
            .limit(8)
        )
        recent_rows = (await session.execute(recent_stmt)).all()
        context["recent_meals"] = [
            {
                "name": meal.custom_name or library_name or "Unknown food",
                "quantity_g": float(meal.quantity_g),
                "per100": {
                    "calories": float(meal.calories_per_100),
                    "protein_g": float(meal.protein_per_100),
                    "carbs_g": float(meal.carbs_per_100),
                    "fat_g": float(meal.fat_per_100),
                    "fiber_g": float(meal.fiber_per_100),
                },
                "local_logged_at": meal.logged_at.astimezone(ZoneInfo(profile.timezone)).isoformat(),
            }
            for meal, library_name in recent_rows
        ]

    if request.mode in {"goals", "analytics"}:
        days = None if request.analytics_start else (request.analytics_days or 30)
        analytics_range = resolve_range(
            profile.timezone,
            days=days,
            start=request.analytics_start,
            end=request.analytics_end,
            now=now,
        )
        analytics = await get_analytics(
            session,
            profile,
            analytics_range,
            list(request.analytics_sources),
            request.analytics_food_query,
        )
        context["selected_period"] = {
            "start": analytics.start_date.isoformat(),
            "end": analytics.end_date.isoformat(),
            "metric": request.analytics_metric or "calories",
            "summary": analytics.summary.model_dump(),
            "source_breakdown": [item.model_dump() for item in analytics.source_breakdown],
            "top_foods": [item.model_dump() for item in analytics.top_foods[:5]],
        }
        context["limitations"].extend(["no_weight_history"])
        if analytics.summary.active_days < analytics.summary.calendar_days:
            context["limitations"].append(
                "missing_logging_days_make_intake_averages_incomplete"
            )
    if request.mode == "goals":
        context["body"] = {
            "weight_kg": float(profile.weight_kg),
            "height_cm": float(profile.height_cm),
        }
    return context
