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

from typing import TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from app.services.runtime_settings import LlmTask, resolve_provider

T = TypeVar("T", bound=BaseModel)

MAX_ATTEMPTS = 2

SCHEMA_PREAMBLE = (
    "\n\nRespond with a single JSON object and nothing else — no markdown "
    "fences, no commentary. Report numbers exactly as extracted; never "
    "perform arithmetic, scaling, or summation yourself."
)


class LLMError(RuntimeError):
    pass


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
        messages: list[dict] = [
            {"role": "system", "content": system + SCHEMA_PREAMBLE},
            {"role": "user", "content": self._content(prompt, image_data_urls)},
        ]
        last_error: Exception | None = None
        for _ in range(MAX_ATTEMPTS):
            resp = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,  # type: ignore[arg-type]
                response_format={"type": "json_object"},
                temperature=0.1,
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
                            f"Your JSON failed validation with: {exc}. "
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
