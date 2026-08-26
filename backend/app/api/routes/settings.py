"""Settings screen API (decisions D34/D35).

Read/mutate runtime provider configuration and probe providers. All routes
are admin-only and cookie-session-only (see require_admin). API keys are write-only:
they are never returned to any client, only a has_api_key boolean.
"""

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import require_admin
from app.models import UserProfile
from app.schemas.api import (
    ProviderConfigOut,
    RuntimeSettingsIn,
    RuntimeSettingsOut,
    SettingsTestRequest,
    SettingsTestResponse,
)
from app.services import runtime_settings
from app.services.llm import get_llm, reset_llm_cache

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _provider_out(state: runtime_settings.ProviderState) -> ProviderConfigOut:
    return ProviderConfigOut(
        base_url=state.base_url,
        model=state.model,
        has_api_key=bool(state.api_key),
    )


def _to_out(state: runtime_settings.RuntimeState) -> RuntimeSettingsOut:
    vision = state.vision
    return RuntimeSettingsOut(
        text=_provider_out(state.text),
        vision=_provider_out(vision),
        vision_inherits_text=vision.inherit_text,
        openfoodfacts_base_url=state.openfoodfacts_base_url,
        updated_at=state.updated_at,
    )


def _apply_provider(
    target: runtime_settings.ProviderState,
    incoming: Any,
    *,
    is_vision: bool = False,
) -> None:
    fields = getattr(incoming, "model_fields_set", set())
    if "base_url" in fields:
        target.base_url = str(incoming.base_url) if incoming.base_url else None
    if "model" in fields:
        target.model = incoming.model
    # api_key tri-state: omitted keeps the stored key; "" clears; value sets.
    if "api_key" in fields:
        target.api_key = incoming.api_key or None
    if is_vision:
        assert isinstance(target, runtime_settings.VisionProviderState)
        if "inherit_text" in fields:
            target.inherit_text = incoming.inherit_text


@router.get("", response_model=RuntimeSettingsOut)
async def read_settings(
    _profile: UserProfile = Depends(require_admin),
):
    return _to_out(runtime_settings.load_runtime_state())


@router.put("", response_model=RuntimeSettingsOut)
async def update_settings(
    body: RuntimeSettingsIn,
    _profile: UserProfile = Depends(require_admin),
):
    state = runtime_settings.load_runtime_state()
    _apply_provider(state.text, body.text)
    _apply_provider(state.vision, body.vision, is_vision=True)

    if "openfoodfacts_base_url" in body.model_fields_set:
        state.openfoodfacts_base_url = (
            str(body.openfoodfacts_base_url) if body.openfoodfacts_base_url else None
        )

    runtime_settings.save_runtime_state(state)
    reset_llm_cache()
    return _to_out(runtime_settings.load_runtime_state())


@router.post("/test", response_model=SettingsTestResponse)
async def test_provider(
    body: SettingsTestRequest,
    _profile: UserProfile = Depends(require_admin),
):
    try:
        reply = await get_llm(body.task).probe()
        detail = reply or "Provider responded with an empty message."
        return SettingsTestResponse(ok=True, detail=detail[:200])
    except Exception as exc:  # noqa: BLE001 - surfaced verbatim for diagnosis
        return SettingsTestResponse(ok=False, detail=str(exc)[:500])
