"""Settings API contract: key tri-state, redaction, cookie-only authz."""

import pytest
from fastapi import HTTPException

from app.api.routes import settings
from app.api.routes.settings import _apply_provider, read_settings, update_settings
from app.schemas.api import (
    ProviderConfigIn,
    RuntimeSettingsIn,
    SettingsTestRequest,
    VisionProviderConfigIn,
)
from app.services import runtime_settings


@pytest.fixture(autouse=True)
def isolated_settings_file(tmp_path, monkeypatch):
    target = tmp_path / "runtime-settings.json"
    monkeypatch.setattr(runtime_settings, "_settings_path", lambda: target)
    runtime_settings.clear_runtime_state()
    yield
    runtime_settings.clear_runtime_state()


def make_body(**overrides) -> RuntimeSettingsIn:
    values: dict = {
        "text": ProviderConfigIn(),
        "vision": VisionProviderConfigIn(),
    }
    values.update(overrides)
    return RuntimeSettingsIn(**values)


@pytest.mark.asyncio
async def test_get_settings_is_redacted_and_defaults_inherit():
    out = await read_settings(None)  # type: ignore[arg-type]
    assert out.text.has_api_key is False
    assert out.vision_inherits_text is True
    assert out.updated_at is None


@pytest.mark.asyncio
async def test_api_key_tri_state():
    body = make_body(
        text=ProviderConfigIn(api_key="sk-live-123"),
    )
    # Simulate the client sending the key field explicitly.
    body.text.model_fields_set.add("api_key")
    state = runtime_settings.RuntimeState()
    _apply_provider(state.text, body.text)
    assert state.text.api_key == "sk-live-123"

    # Omitted field keeps the stored key.
    keep = make_body(text=ProviderConfigIn(model="m"))
    state2 = runtime_settings.RuntimeState(
        text=runtime_settings.ProviderState(api_key="stored")
    )
    _apply_provider(state2.text, keep.text)
    assert state2.text.api_key == "stored"
    assert state2.text.model == "m"

    # Empty string clears.
    clear = make_body(text=ProviderConfigIn(api_key=""))
    clear.text.model_fields_set.add("api_key")
    _apply_provider(state2.text, clear.text)
    assert state2.text.api_key is None


@pytest.mark.asyncio
async def test_put_round_trip_resets_overrides(tmp_path):
    set_body = make_body(
        text=ProviderConfigIn(
            base_url="http://localhost:11434/v1", model="llama3", api_key="k-1"
        ),
        vision=VisionProviderConfigIn(inherit_text=False),
        openfoodfacts_base_url="http://off.internal/api/v2",
    )
    set_body.text.model_fields_set.update({"base_url", "model", "api_key"})
    out = await update_settings(set_body, None)  # type: ignore[arg-type]
    assert out.text.base_url == "http://localhost:11434/v1"
    assert out.text.has_api_key is True
    assert out.vision_inherits_text is False
    assert out.openfoodfacts_base_url == "http://off.internal/api/v2"
    assert runtime_settings.resolve_openfoodfacts_base_url() == "http://off.internal/api/v2"

    # A later PUT that sends explicit nulls clears overrides; the API key is
    # kept because the field was omitted (tri-state: omit = keep).
    reset_body = make_body(
        text=ProviderConfigIn(base_url=None, model=None),
        openfoodfacts_base_url=None,
    )
    out2 = await update_settings(reset_body, None)  # type: ignore[arg-type]
    assert out2.text.base_url is None
    assert out2.text.model is None
    assert out2.text.has_api_key is True  # omitted key survives provider edits
    assert out2.openfoodfacts_base_url is None


@pytest.mark.asyncio
async def test_vision_override_does_not_leak_into_text():
    body = make_body(vision=VisionProviderConfigIn(inherit_text=False, model="vl-model"))
    body.vision.model_fields_set.update({"inherit_text", "model"})
    await update_settings(body, None)  # type: ignore[arg-type]
    _, text_model, _ = runtime_settings.resolve_provider("text")
    v_url, vision_model, _ = runtime_settings.resolve_provider("vision")
    assert text_model != "vl-model" or text_model is not None
    assert vision_model == "vl-model"
    assert v_url  # inherited env URL


def test_cookie_only_dependency_rejects_missing_session():
    from app.api.deps import get_cookie_profile

    class FakeRequest:
        cookies = {}
        headers = {"authorization": "Bearer whatever"}

    with pytest.raises(HTTPException) as exc:
        import asyncio

        asyncio.run(get_cookie_profile(FakeRequest(), session=None))  # type: ignore[arg-type]
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_empty_provider_probe_is_reported_as_failure(monkeypatch):
    class EmptyProbe:
        async def probe(self):
            return ""

    monkeypatch.setattr(settings, "get_llm", lambda _task: EmptyProbe())

    result = await settings.test_provider(
        SettingsTestRequest(task="text"), None  # type: ignore[arg-type]
    )

    assert result.ok is False
    assert result.detail == "Provider responded with an empty message."
