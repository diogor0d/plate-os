from datetime import UTC, date

import pytest
from pydantic import ValidationError

from app.api.routes.meals import day_bounds
from app.config import Settings
from app.schemas.api import MealLogCreate, MealLogPatch, UserProfileUpdate
from app.schemas.llm_contracts import FoodItemProposal, Per100Values


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
