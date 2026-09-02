"""Unit tests for the LLM gateway's JSON-mode + validation + retry loop,
using a stubbed OpenAI-compatible client (no network)."""

import pytest
from httpx import Request, Response
from openai import AuthenticationError, NotFoundError, RateLimitError

from app.schemas.llm_contracts import NutritionLabelExtraction, Per100Values
from app.services.llm import LLMError, LLMService, describe_llm_error

VALID_EXTRACTION = """
{"product_name": "Oats", "basis": "per_100g", "serving_size_g": null,
 "calories": 379, "protein_g": 13.2, "carbs_g": 67.7, "fat_g": 6.5,
 "fiber_g": 10.1, "confidence_score": 0.93}
"""

INVALID_EXTRACTION = '{"product_name": "Oats", "basis": "per_serving", "calories": 45}'


class FakeResponse:
    def __init__(self, content: str):
        message = type("M", (), {"content": content})()
        choice = type("C", (), {"message": message})()
        self.choices = [choice]


class FakeCompletions:
    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return FakeResponse(self.responses.pop(0))


def make_service(responses: list[str]) -> LLMService:
    client = type("Client", (), {})()
    client.chat = type("Chat", (), {})()
    client.chat.completions = FakeCompletions(responses)
    return LLMService(client, model="test-model")


@pytest.mark.asyncio
async def test_valid_json_validates_first_try():
    svc = make_service([VALID_EXTRACTION])
    result = await svc.extract_json(
        system="sys", prompt="extract", schema=NutritionLabelExtraction
    )
    assert result.product_name == "Oats"
    assert result.calories == 379
    assert len(svc._client.chat.completions.calls) == 1


@pytest.mark.asyncio
async def test_validation_error_triggers_corrective_retry():
    svc = make_service([INVALID_EXTRACTION, VALID_EXTRACTION])
    result = await svc.extract_json(
        system="sys", prompt="extract", schema=NutritionLabelExtraction
    )
    assert result.calories == 379
    calls = svc._client.chat.completions.calls
    assert len(calls) == 2
    retry_messages = calls[1]["messages"]
    assert any("failed validation" in str(m) for m in retry_messages)


@pytest.mark.asyncio
async def test_gives_up_after_max_attempts():
    svc = make_service([INVALID_EXTRACTION, INVALID_EXTRACTION])
    with pytest.raises(LLMError):
        await svc.extract_json(system="sys", prompt="x", schema=NutritionLabelExtraction)


@pytest.mark.asyncio
async def test_schema_preamble_forbids_arithmetic():
    svc = make_service([VALID_EXTRACTION])
    await svc.extract_json(
        system="sys", prompt="x", schema=NutritionLabelExtraction, image_data_urls=["data:image/webp;base64,AAAA"]
    )
    call = svc._client.chat.completions.calls[0]
    system_content = call["messages"][0]["content"]
    assert "never" in system_content and "scale or sum nutrients" in system_content
    assert "Required JSON Schema" in system_content
    assert call["max_tokens"] == 2000
    user_content = call["messages"][1]["content"]
    assert isinstance(user_content, list)  # multimodal blocks
    assert user_content[0]["image_url"]["url"].startswith("data:image/webp")


@pytest.mark.parametrize(
    ("exception_type", "expected_status", "expected_text"),
    [
        (AuthenticationError, 502, "rejected its credentials"),
        (NotFoundError, 502, "'retired-model' was not found"),
        (RateLimitError, 429, "rate limited"),
    ],
)
def test_provider_errors_are_actionable_without_raw_upstream_details(
    exception_type, expected_status, expected_text
):
    response = Response(404, request=Request("POST", "https://provider.invalid/chat"))
    exc = exception_type(
        "raw upstream detail that should not be exposed",
        response=response,
        body={"error": {"message": "provider internals"}},
    )

    status, detail = describe_llm_error(
        exc,
        task_label="Label scanning",
        model="retired-model",
    )

    assert status == expected_status
    assert expected_text in detail
    assert "raw upstream" not in detail
    assert "provider internals" not in detail
