"""Unit tests for the LLM gateway's JSON-mode + validation + retry loop,
using a stubbed OpenAI-compatible client (no network)."""

import pytest
from httpx import Request, Response
from openai import AuthenticationError, NotFoundError, RateLimitError

from app.schemas.llm_contracts import NutritionLabelExtraction, Per100Values
from app.services import llm
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


@pytest.mark.asyncio
async def test_official_deepseek_text_uses_adaptive_reasoning_and_nonthinking_probe(monkeypatch):
    service = make_service([VALID_EXTRACTION, "OK"])
    monkeypatch.setattr(llm, "resolve_provider", lambda _task: (
        "https://api.deepseek.com", "deepseek-v4-flash", "key"
    ))
    monkeypatch.setattr(llm, "_client_for", lambda _url, _key: service._client)

    resolved = llm.get_llm("text")
    await resolved.extract_json(
        system="sys", prompt="extract", schema=NutritionLabelExtraction
    )
    assert await resolved.probe() == "OK"

    calls = service._client.chat.completions.calls
    assert calls[0]["extra_body"] == {"thinking": {"type": "enabled"}}
    assert calls[0]["reasoning_effort"] == "high"
    assert calls[0]["max_tokens"] == 16000
    assert "temperature" not in calls[0]
    assert calls[1]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert calls[1]["max_tokens"] == 32


@pytest.mark.asyncio
async def test_deepseek_reasoning_only_response_retries_with_larger_budget(monkeypatch):
    service = make_service(["", VALID_EXTRACTION])
    monkeypatch.setattr(llm, "resolve_provider", lambda _task: (
        "https://api.deepseek.com", "deepseek-v4-flash", "key"
    ))
    monkeypatch.setattr(llm, "_client_for", lambda _url, _key: service._client)

    result = await llm.get_llm("text").extract_json(
        system="sys", prompt="extract", schema=NutritionLabelExtraction
    )

    assert result.product_name == "Oats"
    calls = service._client.chat.completions.calls
    assert calls[0]["max_tokens"] == 16000
    assert calls[1]["max_tokens"] == 32000
    assert len(calls[1]["messages"]) == 2


def test_custom_deepseek_model_does_not_receive_hosted_provider_options(monkeypatch):
    service = make_service(["OK"])
    monkeypatch.setattr(llm, "resolve_provider", lambda _task: (
        "http://ollama.internal/v1", "deepseek-r1", None
    ))
    monkeypatch.setattr(llm, "_client_for", lambda _url, _key: service._client)

    resolved = llm.get_llm("text")

    assert resolved._contract_options(0) == {"max_tokens": 2000}
    assert resolved._probe_options() == {}


def test_official_deepseek_vision_disables_thinking(monkeypatch):
    service = make_service([VALID_EXTRACTION])
    monkeypatch.setattr(llm, "resolve_provider", lambda _task: (
        "https://api.deepseek.com", "deepseek-v4-flash-vision-exp", "key"
    ))
    monkeypatch.setattr(llm, "_client_for", lambda _url, _key: service._client)

    resolved = llm.get_llm("vision")

    assert resolved._contract_options(0) == {
        "max_tokens": 2000,
        "extra_body": {"thinking": {"type": "disabled"}},
    }


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
