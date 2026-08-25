"""Runtime-editable operational settings (decisions D34/D35).

The Settings screen edits LLM provider configuration for the two tasks
("text" = coach chat, "vision" = label parsing) plus the Open Food Facts
base URL. State lives in a single JSON file OUTSIDE the database by design:

- API keys never enter meal data or encrypted pg_dump backups; a restore
  drill does not silently carry provider credentials (re-enter them after
  disaster recovery).
- Env vars remain bootstrap defaults; each file field overrides its env
  counterpart only when set.
- Writes are atomic (temp file + os.replace) and keep one .bak copy of the
  previous version; a missing or corrupt file falls back to env defaults.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.config import get_settings

LlmTask = Literal["text", "vision"]

SETTINGS_VERSION = 1


class ProviderState(BaseModel):
    """Runtime overrides for one task's provider. None = use inherited/env."""

    base_url: str | None = Field(default=None, max_length=2048)
    model: str | None = Field(default=None, min_length=1, max_length=200)
    api_key: str | None = Field(default=None, max_length=4096)


class VisionProviderState(ProviderState):
    inherit_text: bool = True


class RuntimeState(BaseModel):
    version: int = SETTINGS_VERSION
    text: ProviderState = Field(default_factory=ProviderState)
    vision: VisionProviderState = Field(default_factory=VisionProviderState)
    openfoodfacts_base_url: str | None = Field(default=None, max_length=2048)
    updated_at: datetime | None = None


def _settings_path() -> Path:
    return Path(get_settings().runtime_settings_file)


def load_runtime_state() -> RuntimeState:
    try:
        raw = _settings_path().read_text(encoding="utf-8")
        state = RuntimeState.model_validate_json(raw)
    except (OSError, ValueError):
        return RuntimeState()
    if state.version != SETTINGS_VERSION:
        return RuntimeState()
    return state


def save_runtime_state(state: RuntimeState) -> None:
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    state.version = SETTINGS_VERSION
    state.updated_at = datetime.now(UTC)
    payload = state.model_dump_json(indent=2, exclude_none=True)
    backup = path.with_suffix(path.suffix + ".bak")
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    if path.exists():
        os.replace(path, backup)
    tmp.write_text(payload + "\n", encoding="utf-8")
    # The file holds provider API keys: owner-only even inside the volume.
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def clear_runtime_state() -> None:
    """Remove overrides entirely (used by tests)."""
    try:
        _settings_path().unlink(missing_ok=True)
    except OSError:
        pass


def _overlay(base: ProviderState | None, fallback_base_url: str, fallback_model: str,
             fallback_api_key: str | None) -> tuple[str, str | None]:
    base_url = (base.base_url if base and base.base_url else fallback_base_url)
    model = (base.model if base and base.model else fallback_model)
    api_key = (base.api_key if base and base.api_key else fallback_api_key)
    return base_url, model or "", api_key


def resolve_provider(task: LlmTask) -> tuple[str, str, str | None]:
    """Resolve (base_url, model, api_key) for a task.

    Text falls back per-field to env. Vision first inherits the resolved text
    values when inherit_text is set, then applies any explicit vision
    overrides per-field.
    """
    s = get_settings()
    state = load_runtime_state()

    text_url, text_model, text_key = _overlay(
        state.text, s.llm_base_url, s.llm_model, s.llm_api_key
    )
    if task == "text":
        return text_url, text_model, text_key

    vision = state.vision
    if vision.inherit_text:
        return text_url, text_model, text_key
    return _overlay(vision, text_url, text_model, text_key)


def resolve_openfoodfacts_base_url() -> str:
    state = load_runtime_state()
    return state.openfoodfacts_base_url or get_settings().openfoodfacts_base_url
