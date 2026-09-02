"""Provider-agnostic LLM gateway (decisions D5, D34, D35).

Speaks the OpenAI-compatible Chat Completions protocol so OpenAI, Gemini's
OpenAI-compat endpoint, or a local Ollama can serve each task. The "text"
task (coach chat) and the "vision" task (label parsing) resolve their
provider independently: Settings-screen overrides first, then env defaults,
with vision inheriting the text provider unless explicitly overridden.

Structured output strategy: JSON response mode + local Pydantic validation
with one corrective retry. This works uniformly across all three providers,
unlike provider-specific structured-output APIs.
"""

import json
from typing import TypeVar

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    NotFoundError,
    OpenAIError,
    RateLimitError,
)
from pydantic import BaseModel, ValidationError

from app.services.runtime_settings import LlmTask, resolve_provider

T = TypeVar("T", bound=BaseModel)

MAX_ATTEMPTS = 2

SCHEMA_PREAMBLE = (
    "\n\nRespond with a single JSON object and nothing else — no markdown "
    "fences, no commentary. For nutrition proposals, report reference values "
    "per 100 g and quantity separately; never scale or sum nutrients yourself."
)


class LLMError(RuntimeError):
    pass


def describe_llm_error(
    exc: LLMError | OpenAIError,
    *,
    task_label: str,
    model: str,
) -> tuple[int, str]:
    """Map provider failures to safe, actionable API feedback."""
    settings_hint = f"Check the {task_label.lower()} provider in Settings and run its connection test."
    if isinstance(exc, AuthenticationError):
        return 502, f"The {task_label.lower()} provider rejected its credentials. {settings_hint}"
    if isinstance(exc, NotFoundError):
        return 502, (
            f"The configured {task_label.lower()} model '{model}' was not found or is no longer "
            f"available. Select a supported model in Settings and run its connection test."
        )
    if isinstance(exc, RateLimitError):
        return 429, f"The {task_label.lower()} provider is rate limited. Wait and try again."
    if isinstance(exc, APITimeoutError):
        return 504, f"The {task_label.lower()} provider timed out. Try again or {settings_hint.lower()}"
    if isinstance(exc, APIConnectionError):
        return 502, f"PlateOS could not reach the {task_label.lower()} provider. {settings_hint}"
    if isinstance(exc, APIStatusError):
        return 502, (
            f"The {task_label.lower()} provider returned HTTP {exc.status_code}. {settings_hint}"
        )
    return 502, (
        f"The {task_label.lower()} provider returned data PlateOS could not validate. "
        "Try a clearer image or test another model in Settings."
    )


_clients: dict[tuple[str, str], AsyncOpenAI] = {}


def _client_for(base_url: str, api_key: str | None) -> AsyncOpenAI:
    key = api_key or ""
    cached = _clients.get((base_url, key))
    if cached is None:
        cached = AsyncOpenAI(base_url=base_url, api_key=key or "not-set", timeout=60.0)
        _clients[(base_url, key)] = cached
    return cached


def reset_llm_cache() -> None:
    """Drop pooled clients after provider settings change."""
    _clients.clear()


class LLMService:
    def __init__(self, client: AsyncOpenAI, model: str) -> None:
        self._client = client
        self.model = model

    @staticmethod
    def _content(prompt: str, image_data_urls: list[str] | None) -> str | list[dict]:
        if not image_data_urls:
            return prompt
        blocks: list[dict] = [
            {"type": "image_url", "image_url": {"url": url}} for url in image_data_urls
        ]
        blocks.append({"type": "text", "text": prompt})
        return blocks

    async def extract_json(
        self,
        *,
        system: str,
        prompt: str,
        schema: type[T],
        image_data_urls: list[str] | None = None,
    ) -> T:
        schema_json = json.dumps(schema.model_json_schema(), separators=(",", ":"))
        messages: list[dict] = [
            {
                "role": "system",
                "content": system + SCHEMA_PREAMBLE + "\n\nRequired JSON Schema:\n" + schema_json,
            },
            {"role": "user", "content": self._content(prompt, image_data_urls)},
        ]
        last_error: Exception | None = None
        for _ in range(MAX_ATTEMPTS):
            resp = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,  # type: ignore[arg-type]
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=2000,
            )
            raw = resp.choices[0].message.content or ""
            try:
                return schema.model_validate_json(raw)
            except ValidationError as exc:
                last_error = exc
                messages.append({"role": "assistant", "content": raw})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"Your JSON failed validation with: {str(exc)[:1500]}. "
                            "Respond again with a corrected JSON object only."
                        ),
                    }
                )
        raise LLMError(
            f"LLM output failed {schema.__name__} validation after "
            f"{MAX_ATTEMPTS} attempts: {last_error}"
        )

    async def probe(self) -> str:
        """Minimal round-trip used by the Settings screen's Test action."""
        resp = await self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": "Reply with the single word OK."}],
            max_tokens=5,
            temperature=0,
            timeout=20,
        )
        return (resp.choices[0].message.content or "").strip()


def get_llm(task: LlmTask) -> LLMService:
    base_url, model, api_key = resolve_provider(task)
    return LLMService(_client_for(base_url, api_key), model)
