from datetime import UTC, date

import pytest
from pydantic import ValidationError

from app.api.routes import meals
from app.api.routes.meals import day_bounds
from app.config import Settings
from app.models import UserProfile
from app.schemas.api import DailySummary, MealLogCreate, MealLogPatch, UserProfileUpdate
from app.schemas.llm_contracts import FoodItemProposal, MealPlanScheduleDraft, Per100Values


def custom_log(**overrides) -> MealLogCreate:
    values = {
        "custom_name": "Oats",
        "quantity_g": 100,
        "per100": {
            "calories": 379,
            "protein_g": 13.2,
            "carbs_g": 67.7,
            "fat_g": 6.5,
            "fiber_g": 10.1,
        },
        "source_type": "manual",
    }
    values.update(overrides)
    return MealLogCreate(**values)


def test_validates_iana_timezones():
    assert UserProfileUpdate(timezone="Europe/Lisbon").timezone == "Europe/Lisbon"
    with pytest.raises(ValidationError):
        UserProfileUpdate(timezone="Not/AZone")
    with pytest.raises(ValidationError):
        Settings(default_user_timezone="Not/AZone", _env_file=None)
    assert MealPlanScheduleDraft(
        local_time="08:00",
        timezone="Europe/Lisbon",
        frequency="daily",
        start_date="2026-09-02",
    ).timezone == "Europe/Lisbon"
    with pytest.raises(ValidationError):
        MealPlanScheduleDraft(
            local_time="08:00",
            timezone="Not/AZone",
            frequency="daily",
            start_date="2026-09-02",
        )


def test_validates_fiber_target():
    assert UserProfileUpdate(target_fiber_g=25).target_fiber_g == 25
    with pytest.raises(ValidationError):
        UserProfileUpdate(target_fiber_g=-1)
    with pytest.raises(ValidationError):
        UserProfileUpdate(target_fiber_g=1001)


@pytest.mark.asyncio
async def test_daily_summary_includes_fiber_target_and_remaining(monkeypatch):
    async def consumed_for_day(*_args):
        return {
            "calories": 1000.0,
            "protein_g": 80.0,
            "carbs_g": 120.0,
            "fat_g": 40.0,
            "fiber_g": 9.5,
        }

    profile = UserProfile(
        weight_kg=70,
        height_cm=175,
        target_calories=2200,
        target_protein_g=140,
        target_carbs_g=250,
        target_fat_g=70,
        target_fiber_g=25,
        timezone="Europe/Lisbon",
    )
    monkeypatch.setattr(meals, "consumed_for_day", consumed_for_day)

    summary = await meals.daily_summary(date(2026, 9, 11), profile, object())

    assert summary.targets.fiber_g == 25
    assert summary.consumed.fiber_g == 9.5
    assert summary.remaining.fiber_g == 15.5


def test_daily_summary_requires_all_five_nutrients():
    with pytest.raises(ValidationError):
        DailySummary(
            date="2026-09-11",
            timezone="Europe/Lisbon",
            targets={"calories": 2200, "protein_g": 140, "carbs_g": 250, "fat_g": 70},
            consumed={"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0, "fiber_g": 0},
            remaining={"calories": 2200, "protein_g": 140, "carbs_g": 250, "fat_g": 70, "fiber_g": 25},
        )


def test_requires_aware_meal_timestamps():
    with pytest.raises(ValidationError):
        custom_log(logged_at="2026-08-25T12:00:00")
    with pytest.raises(ValidationError):
        MealLogPatch(logged_at="2026-08-25T12:00:00")

    parsed = custom_log(logged_at="2026-08-25T12:00:00Z")
    assert parsed.logged_at is not None
    assert parsed.logged_at.utcoffset() is not None


def test_rejects_unrepresentable_or_ambiguous_meals():
    with pytest.raises(ValidationError):
        custom_log(quantity_g=0.001)
    with pytest.raises(ValidationError):
        custom_log(quantity_g=1.234)
    with pytest.raises(ValidationError):
        MealLogCreate(
            food_item_id="b02adf84-1320-4763-b86e-0690804e35a7",
            custom_name="Oats",
            quantity_g=100,
            per100=Per100Values(
                calories=379, protein_g=13.2, carbs_g=67.7, fat_g=6.5
            ),
            source_type="barcode",
        )


def test_rejects_nonfinite_and_impossible_density_values():
    with pytest.raises(ValidationError):
        Per100Values(calories=float("nan"), protein_g=0, carbs_g=0, fat_g=0)
    with pytest.raises(ValidationError):
        Per100Values(calories=1001, protein_g=0, carbs_g=0, fat_g=0)
    with pytest.raises(ValidationError):
        Per100Values(calories=100, protein_g=101, carbs_g=0, fat_g=0)


def test_day_bounds_follow_local_dst_midnight():
    start, end = day_bounds(date(2026, 3, 29), "Europe/Lisbon")
    elapsed = end.astimezone(UTC) - start.astimezone(UTC)
    assert elapsed.total_seconds() == 23 * 60 * 60


def test_proposal_weight_is_persistence_ready():
    proposal = FoodItemProposal(
        name="Oats",
        estimated_weight_g=12.345,
        confidence="high",
        reasoning="weighed",
        per100=Per100Values(calories=100, protein_g=1, carbs_g=1, fat_g=1),
    )
    assert proposal.estimated_weight_g == 12.35
