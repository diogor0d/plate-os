"""Runtime settings: file store, provider resolution, key tri-state, authz."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import get_settings
from app.services import runtime_settings
from app.services.llm import _clients, get_llm, reset_llm_cache


@pytest.fixture(autouse=True)
def isolated_settings_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "runtime-settings.json"
    monkeypatch.setattr(runtime_settings, "_settings_path", lambda: target)
    runtime_settings.clear_runtime_state()
    yield
    runtime_settings.clear_runtime_state()


def test_missing_or_corrupt_file_falls_back_to_env():
    assert runtime_settings.resolve_provider("text") == (
        get_settings().llm_base_url,
        get_settings().llm_model,
        get_settings().llm_api_key,
    )

    path = Path(get_settings().runtime_settings_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert runtime_settings.load_runtime_state().text.base_url is None


def test_text_override_and_vision_inheritance():
    state = runtime_settings.RuntimeState(
        text=runtime_settings.ProviderState(
            base_url="http://localhost:11434/v1",
            model="qwen2.5:7b",
        )
    )
    runtime_settings.save_runtime_state(state)

    base_url, model, api_key = runtime_settings.resolve_provider("text")
    assert (base_url, model) == ("http://localhost:11434/v1", "qwen2.5:7b")
    assert api_key is None

    v_url, v_model, v_key = runtime_settings.resolve_provider("vision")
    assert (v_url, v_model, v_key) == (base_url, model, api_key)

    state.vision.inherit_text = False
    state.vision.base_url = "https://api.openai.com/v1"
    state.vision.model = "gpt-4o-mini"
    state.vision.api_key = "sk-vision-only"
    runtime_settings.save_runtime_state(state)

    v_url, v_model, v_key = runtime_settings.resolve_provider("vision")
    assert (v_url, v_model, v_key) == (
        "https://api.openai.com/v1",
        "gpt-4o-mini",
        "sk-vision-only",
    )
    # Text task untouched by vision overrides.
    assert runtime_settings.resolve_provider("text")[2] is None


def test_vision_partial_overrides_inherit_remaining_fields():
    state = runtime_settings.RuntimeState(
        text=runtime_settings.ProviderState(model="coach-model"),
        vision=runtime_settings.VisionProviderState(inherit_text=False),
    )
    runtime_settings.save_runtime_state(state)
    base_url, model, _ = runtime_settings.resolve_provider("vision")
    assert base_url == get_settings().llm_base_url
    assert model == "coach-model"


def test_save_is_atomic_and_keeps_backup():
    first = runtime_settings.RuntimeState(text=runtime_settings.ProviderState(model="a"))
    runtime_settings.save_runtime_state(first)
    second = runtime_settings.RuntimeState(text=runtime_settings.ProviderState(model="b"))
    runtime_settings.save_runtime_state(second)

    path = Path(get_settings().runtime_settings_file)
    loaded = runtime_settings.load_runtime_state()
    assert loaded.text.model == "b"
    assert loaded.updated_at is not None and loaded.updated_at.tzinfo == UTC
    backup = path.with_suffix(path.suffix + ".bak")
    assert backup.exists()
    assert '"model": "a"' not in path.read_text(encoding="utf-8")


def test_client_cache_reset_on_provider_change():
    reset_llm_cache()
    get_llm("text")
    keys_before = set(_clients)
    assert keys_before
    reset_llm_cache()
    assert not _clients


def test_off_base_url_resolution():
    assert (
        runtime_settings.resolve_openfoodfacts_base_url()
        == get_settings().openfoodfacts_base_url
    )
    runtime_settings.save_runtime_state(
        runtime_settings.RuntimeState(openfoodfacts_base_url="http://mirror.internal/api/v2")
    )
    assert (
        runtime_settings.resolve_openfoodfacts_base_url() == "http://mirror.internal/api/v2"
    )


def test_state_model_bounds():
    with pytest.raises(ValidationError):
        runtime_settings.ProviderState(base_url="x" * 3000)
    with pytest.raises(ValidationError):
        runtime_settings.ProviderState(api_key="k" * 5000)


def test_updated_at_written_by_save_not_loader():
    state = runtime_settings.RuntimeState(updated_at=datetime(2020, 1, 1, tzinfo=UTC))
    runtime_settings.save_runtime_state(state)
    loaded = runtime_settings.load_runtime_state()
    assert loaded.updated_at is not None
    assert loaded.updated_at.year >= 2026
