from datetime import date

import pytest
from pydantic import ValidationError

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
