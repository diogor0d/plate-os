from datetime import UTC, date, datetime

import pytest

from app.schemas.api import DayTotals
from app.services.analytics import resolve_range, summarize


def test_resolve_range_defaults_to_thirty_local_days():
    result = resolve_range(
        "Europe/Lisbon",
        days=None,
        start=None,
        end=None,
        now=datetime(2026, 8, 31, 12, tzinfo=UTC),
    )
    assert result.start == date(2026, 8, 2)
    assert result.end == date(2026, 8, 31)
    assert result.days == 30


def test_resolve_range_accepts_presets_and_custom_dates():
    preset = resolve_range(
        "Europe/Lisbon",
        days=7,
        start=None,
        end=None,
        now=datetime(2026, 8, 31, 12, tzinfo=UTC),
    )
    custom = resolve_range(
        "Europe/Lisbon",
        days=None,
        start=date(2026, 7, 1),
        end=date(2026, 8, 31),
    )
    assert (preset.start, preset.end) == (date(2026, 8, 25), date(2026, 8, 31))
    assert custom.days == 62


@pytest.mark.parametrize(
    "kwargs",
    [
        {"days": 7, "start": date(2026, 8, 1), "end": date(2026, 8, 2)},
        {"days": None, "start": date(2026, 8, 1), "end": None},
        {"days": None, "start": date(2026, 8, 2), "end": date(2026, 8, 1)},
        {"days": None, "start": date(2025, 1, 1), "end": date(2026, 8, 31)},
    ],
)
def test_resolve_range_rejects_ambiguous_or_invalid_ranges(kwargs):
    with pytest.raises(ValueError):
        resolve_range("Europe/Lisbon", **kwargs)


def test_summarize_distinguishes_calendar_and_active_days():
    history = [
        DayTotals(
            date="2026-08-29",
            meal_count=2,
            calories=1800,
            protein_g=120,
            carbs_g=200,
            fat_g=60,
            fiber_g=25,
        ),
        DayTotals(
            date="2026-08-30",
            meal_count=0,
            calories=0,
            protein_g=0,
            carbs_g=0,
            fat_g=0,
            fiber_g=0,
        ),
        DayTotals(
            date="2026-08-31",
            meal_count=1,
            calories=1200,
            protein_g=90,
            carbs_g=100,
            fat_g=40,
            fiber_g=20,
        ),
    ]
    result = summarize(history)
    assert result.meal_count == 3
    assert result.active_days == 2
    assert result.avg_meals_per_active_day == 1.5
    assert result.avg_calories_per_day == 1000
    assert result.avg_calories_per_active_day == 1500
    assert result.avg_protein_g_per_day == 70
    assert result.avg_fiber_g_per_day == 15


def test_summarize_handles_empty_history():
    result = summarize([])
    assert result.meal_count == 0
    assert result.avg_calories_per_day == 0
    assert result.avg_meals_per_active_day == 0
