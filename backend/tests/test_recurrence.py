from datetime import UTC, date, datetime, time

import pytest

from app.models import MealOccurrence
from app.services.routines import occurrence_state, recurrence_dates, resolve_wall_clock


def test_daily_recurrence_uses_start_date_as_interval_anchor():
    assert recurrence_dates(
        frequency="daily",
        interval=3,
        iso_weekdays=[],
        start_date=date(2026, 9, 2),
        end_date=None,
        range_start=date(2026, 9, 1),
        range_end=date(2026, 9, 10),
    ) == [date(2026, 9, 2), date(2026, 9, 5), date(2026, 9, 8)]


def test_weekly_recurrence_uses_start_dates_iso_week_as_anchor():
    assert recurrence_dates(
        frequency="weekly",
        interval=2,
        iso_weekdays=[1, 5],
        start_date=date(2026, 9, 2),  # Wednesday; Monday before start is excluded.
        end_date=date(2026, 9, 30),
        range_start=date(2026, 9, 1),
        range_end=date(2026, 9, 30),
    ) == [
        date(2026, 9, 4),
        date(2026, 9, 14),
        date(2026, 9, 18),
        date(2026, 9, 28),
    ]


def test_recurrence_honors_bounded_schedule_and_range():
    assert recurrence_dates(
        frequency="daily",
        interval=1,
        iso_weekdays=[],
        start_date=date(2026, 9, 5),
        end_date=date(2026, 9, 7),
        range_start=date(2026, 9, 1),
        range_end=date(2026, 9, 30),
    ) == [date(2026, 9, 5), date(2026, 9, 6), date(2026, 9, 7)]


@pytest.mark.parametrize("interval", [0, 5])
def test_recurrence_rejects_interval_outside_domain_bounds(interval):
    with pytest.raises(ValueError, match="between 1 and 4"):
        recurrence_dates(
            frequency="daily",
            interval=interval,
            iso_weekdays=[],
            start_date=date(2026, 9, 2),
            end_date=None,
            range_start=date(2026, 9, 2),
            range_end=date(2026, 9, 2),
        )


def test_wall_clock_exact_time_is_preserved():
    instant, resolution = resolve_wall_clock(
        date(2026, 2, 1), time(8, 15), "Europe/Lisbon"
    )
    assert instant == datetime(2026, 2, 1, 8, 15, tzinfo=UTC)
    assert resolution == "exact"


def test_ambiguous_wall_clock_chooses_earlier_instant():
    instant, resolution = resolve_wall_clock(
        date(2026, 11, 1), time(1, 30), "America/New_York"
    )
    assert instant == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
    assert resolution == "ambiguous-earlier"


def test_nonexistent_wall_clock_shifts_forward_by_dst_gap():
    instant, resolution = resolve_wall_clock(
        date(2026, 3, 8), time(2, 30), "America/New_York"
    )
    assert instant == datetime(2026, 3, 8, 7, 30, tzinfo=UTC)
    assert resolution == "nonexistent-shift-forward"


def test_occurrence_state_is_server_derived_in_schedule_timezone():
    occurrence = MealOccurrence(
        scheduled_local_date=date(2026, 9, 2),
        scheduled_at=datetime(2026, 9, 2, 11, tzinfo=UTC),
        status="scheduled",
    )
    assert (
        occurrence_state(
            occurrence, datetime(2026, 9, 2, 10, tzinfo=UTC), "Europe/Lisbon"
        )
        == "upcoming"
    )
    assert (
        occurrence_state(
            occurrence, datetime(2026, 9, 2, 12, tzinfo=UTC), "Europe/Lisbon"
        )
        == "due"
    )
    assert (
        occurrence_state(
            occurrence, datetime(2026, 9, 3, 12, tzinfo=UTC), "Europe/Lisbon"
        )
        == "missed"
    )
    occurrence.status = "skipped"
    assert (
        occurrence_state(
            occurrence, datetime(2026, 9, 3, 12, tzinfo=UTC), "Europe/Lisbon"
        )
        == "skipped"
    )
