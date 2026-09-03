import asyncio
import uuid
from datetime import date

import pytest
from pydantic import ValidationError

from app.api.routes import chat
from app.api.routes.chat import MEAL_PLAN_POLICY
from app.models import UserProfile
from app.schemas.api import ChatRequest
from app.schemas.llm_contracts import AssistantHarnessResponse, FoodItemProposal


MEAL = {
    "type": "meal_proposal",
    "title": "Dinner idea",
    "items": [
        {
            "name": "Chicken and rice",
            "basis": "per_100g",
            "estimated_weight_g": 350,
            "confidence": "medium",
            "reasoning": "Cooked mixed meal estimate",
            "per100": {
                "calories": 155,
                "protein_g": 12,
                "carbs_g": 18,
                "fat_g": 4,
                "fiber_g": 1.5,
            },
        }
    ],
    "requires_user_confirmation": True,
}


def test_harness_accepts_allowlisted_blocks():
    response = AssistantHarnessResponse.model_validate(
        {
            "schema_version": "1",
            "assistant_message": "Here is a practical option.",
            "blocks": [
                MEAL,
                {
                    "type": "analytics_navigation",
                    "label": "View protein consistency",
                    "description": "Open the 90-day protein trend.",
                    "query": {"days": 90, "metric": "protein_g"},
                },
                {
                    "type": "evidence_insight",
                    "title": "Logging coverage",
                    "interpretation": "Missing days make averages less reliable.",
                    "tone": "warning",
                },
            ],
        }
    )
    assert [block.type for block in response.blocks] == [
        "meal_proposal",
        "analytics_navigation",
        "evidence_insight",
    ]


def test_meal_contract_rejects_llm_scaled_totals():
    item = dict(MEAL["items"][0], calories=500)
    with pytest.raises(ValidationError):
        FoodItemProposal.model_validate(item)


def test_confirmation_cannot_be_disabled():
    block = dict(MEAL, requires_user_confirmation=False)
    with pytest.raises(ValidationError):
        AssistantHarnessResponse.model_validate(
            {"assistant_message": "Draft", "blocks": [block]}
        )


@pytest.mark.asyncio
async def test_chat_stream_sends_heartbeats_while_reasoning(monkeypatch):
    release = asyncio.Event()

    async def slow_assistant(*_args):
        await release.wait()
        return AssistantHarnessResponse(assistant_message="Ready", blocks=[])

    class Session:
        def add(self, _value):
            pass

        async def commit(self):
            pass

        async def rollback(self):
            pass

    monkeypatch.setattr(chat, "run_assistant", slow_assistant)
    monkeypatch.setattr(chat, "HEARTBEAT_SECONDS", 0.001)
    response = await chat.chat_stream(
        ChatRequest(message="Plan today"), UserProfile(id=uuid.uuid4()), Session()
    )
    iterator = response.body_iterator

    assert "event: meta" in await anext(iterator)
    first_progress = await anext(iterator)
    assert "event: progress" in first_progress
    assert "Reasoning over today's nutrition context" in first_progress
    second_progress = await anext(iterator)
    assert "event: progress" in second_progress
    assert "intermediate thoughts stay private" in second_progress

    release.set()
    remaining = [chunk async for chunk in iterator]
    assert any("event: done" in chunk for chunk in remaining)


@pytest.mark.asyncio
async def test_chat_stream_waits_for_reasoning_task_cleanup(monkeypatch):
    started = asyncio.Event()
    cleaned = asyncio.Event()

    async def slow_assistant(*_args):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    class Session:
        async def rollback(self):
            pass

    monkeypatch.setattr(chat, "run_assistant", slow_assistant)
    response = await chat.chat_stream(
        ChatRequest(message="Plan today"), UserProfile(id=uuid.uuid4()), Session()
    )
    iterator = response.body_iterator
    await anext(iterator)
    await anext(iterator)
    await started.wait()
    pending_read = asyncio.create_task(anext(iterator))
    await asyncio.sleep(0)

    pending_read.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending_read

    assert cleaned.is_set()


def test_meal_plan_draft_accepts_rough_routine_and_weekly_schedule():
    response = AssistantHarnessResponse.model_validate(
        {
            "assistant_message": "Review this reusable meal idea.",
            "blocks": [{
                "type": "meal_plan_draft",
                "title": "Weekday lunch",
                "rough_text": "A protein, a whole grain, and two vegetables.",
                "schedule": {
                    "local_time": "12:30",
                    "timezone": "Europe/Lisbon",
                    "frequency": "weekly",
                    "interval": 1,
                    "iso_weekdays": [1, 3, 5],
                    "start_date": "2026-09-07",
                    "end_date": "2026-12-18",
                    "reminder_minutes": 30,
                },
                "requires_user_confirmation": True,
            }],
        }
    )
    block = response.blocks[0]
    assert block.type == "meal_plan_draft"
    assert block.schedule is not None
    assert block.schedule.iso_weekdays == [1, 3, 5]


@pytest.mark.parametrize(
    "schedule",
    [
        {"frequency": "daily", "iso_weekdays": [1]},
        {"frequency": "weekly", "iso_weekdays": []},
        {"frequency": "weekly", "iso_weekdays": [1, 1]},
        {"frequency": "weekly", "iso_weekdays": [0]},
        {"frequency": "daily", "iso_weekdays": [], "interval": 5},
        {"frequency": "daily", "iso_weekdays": [], "reminder_minutes": 1441},
        {"frequency": "daily", "iso_weekdays": [], "timezone": "Not/AZone"},
        {"frequency": "daily", "iso_weekdays": [], "start_date": "2026-02-30"},
        {"frequency": "daily", "iso_weekdays": [], "start_date": "2026-09-07T00:00:00"},
        {"frequency": "daily", "iso_weekdays": [], "local_time": "12:30:00.5"},
        {"frequency": "daily", "iso_weekdays": [], "end_date": "2026-09-01"},
    ],
)
def test_meal_plan_draft_rejects_invalid_schedule(schedule):
    valid = {
        "local_time": "12:30",
        "timezone": "Europe/Lisbon",
        "frequency": "daily",
        "interval": 1,
        "iso_weekdays": [],
        "start_date": "2026-09-07",
        "end_date": None,
        "reminder_minutes": None,
    }
    with pytest.raises(ValidationError):
        AssistantHarnessResponse.model_validate({
            "assistant_message": "Draft",
            "blocks": [{
                "type": "meal_plan_draft",
                "title": "Lunch",
                "rough_text": "A balanced lunch.",
                "schedule": {**valid, **schedule},
                "requires_user_confirmation": True,
            }],
        })


@pytest.mark.parametrize("confirmation", [False, None])
def test_meal_plan_draft_requires_literal_confirmation(confirmation):
    confirmation_field = {} if confirmation is None else {
        "requires_user_confirmation": confirmation
    }
    with pytest.raises(ValidationError):
        AssistantHarnessResponse.model_validate({
            "assistant_message": "Draft",
            "blocks": [{
                "type": "meal_plan_draft",
                "title": "Lunch",
                "rough_text": "A balanced lunch.",
                "schedule": None,
                **confirmation_field,
            }],
        })


def test_meal_plan_prompt_preserves_confirmation_and_computation_boundaries():
    assert "PlateOS computes" in MEAL_PLAN_POLICY
    assert "explicitly confirm" in MEAL_PLAN_POLICY
    assert "create meal logs" in MEAL_PLAN_POLICY


@pytest.mark.parametrize(
    "query",
    [
        {"days": 30, "start": date(2026, 8, 1), "end": date(2026, 8, 31)},
        {"start": date(2026, 8, 1)},
        {"start": date(2026, 9, 1), "end": date(2026, 8, 1)},
        {"days": 30, "source_types": ["manual", "manual"]},
    ],
)
def test_analytics_actions_reject_invalid_ranges(query):
    with pytest.raises(ValidationError):
        AssistantHarnessResponse.model_validate(
            {
                "assistant_message": "Open stats.",
                "blocks": [
                    {
                        "type": "analytics_navigation",
                        "label": "Open",
                        "description": "Open filtered stats.",
                        "query": query,
                    }
                ],
            }
        )


def test_goal_draft_contains_complete_target_set():
    with pytest.raises(ValidationError):
        AssistantHarnessResponse.model_validate(
            {
                "assistant_message": "Draft goals.",
                "blocks": [
                    {
                        "type": "goal_draft",
                        "proposed_targets": {"target_calories": 2200},
                        "rationale": "Protein consistency could improve.",
                        "requires_user_confirmation": True,
                    }
                ],
            }
        )


def test_goal_draft_rejects_unsafe_target_extremes():
    with pytest.raises(ValidationError):
        AssistantHarnessResponse.model_validate(
            {
                "assistant_message": "Draft goals.",
                "blocks": [
                    {
                        "type": "goal_draft",
                        "proposed_targets": {
                            "target_calories": 0,
                            "target_protein_g": 0,
                            "target_carbs_g": 0,
                            "target_fat_g": 0,
                        },
                        "rationale": "Unsafe draft",
                        "requires_user_confirmation": True,
                    }
                ],
            }
        )


def test_goal_draft_rejects_oversized_caveat():
    with pytest.raises(ValidationError):
        AssistantHarnessResponse.model_validate(
            {
                "assistant_message": "Draft goals.",
                "blocks": [
                    {
                        "type": "goal_draft",
                        "proposed_targets": {
                            "target_calories": 2200,
                            "target_protein_g": 140,
                            "target_carbs_g": 250,
                            "target_fat_g": 70,
                        },
                        "rationale": "Draft",
                        "caveats": ["x" * 301],
                        "requires_user_confirmation": True,
                    }
                ],
            }
        )


def test_chat_context_accepts_custom_stats_range():
    request = ChatRequest(
        message="Explain this view",
        mode="analytics",
        surface="stats",
        analytics_start="2026-08-01",
        analytics_end="2026-08-31",
        analytics_metric="protein_g",
    )
    assert request.analytics_start == date(2026, 8, 1)


def test_chat_context_rejects_mixed_ranges():
    with pytest.raises(ValidationError):
        ChatRequest(
            message="Explain this view",
            analytics_days=30,
            analytics_start="2026-08-01",
            analytics_end="2026-08-31",
        )
