"""Provider-agnostic LLM gateway (decision D5).

Speaks the OpenAI-compatible Chat Completions protocol so OpenAI, Gemini's
OpenAI-compat endpoint, or a local Ollama can be selected via env vars alone
(PLATEOS_LLM_BASE_URL / PLATEOS_LLM_API_KEY / PLATEOS_LLM_MODEL).

Structured output strategy: JSON response mode + local Pydantic validation
with one corrective retry. This works uniformly across all three providers,
unlike provider-specific structured-output APIs.
"""

from typing import TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from app.config import get_settings

T = TypeVar("T", bound=BaseModel)

MAX_ATTEMPTS = 2

SCHEMA_PREAMBLE = (
    "\n\nRespond with a single JSON object and nothing else — no markdown "
    "fences, no commentary. Report numbers exactly as extracted; never "
    "perform arithmetic, scaling, or summation yourself."
)


class LLMError(RuntimeError):
    pass


class LLMService:
    def __init__(self) -> None:
        s = get_settings()
        self.model = s.llm_model
        self._client = AsyncOpenAI(base_url=s.llm_base_url, api_key=s.llm_api_key or "not-set")

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


_service: LLMService | None = None


def get_llm() -> LLMService:
    global _service
    if _service is None:
        _service = LLMService()
    return _service
