"""Authenticated same-origin Web Push subscription management."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_cookie_profile
from app.config import get_settings
from app.db import get_session
from app.models import PushSubscription, UserProfile
from app.schemas.push import (
    PushConfigOut,
    PushSubscriptionCreate,
    PushSubscriptionDelete,
    PushSubscriptionOut,
)
from app.services import web_push

router = APIRouter(prefix="/api/push", tags=["push"])


def _out(value: PushSubscription) -> PushSubscriptionOut:
    return PushSubscriptionOut(
        id=value.id,
        device_name=value.device_name,
        created_at=value.created_at,
        updated_at=value.updated_at,
        last_success_at=value.last_success_at,
        enabled=value.disabled_at is None,
    )


def _enabled_key() -> tuple[bool, str | None, str | None]:
    settings = get_settings()
    return (
        settings.web_push_api_enabled,
        settings.web_push_public_key,
        settings.web_push_subscription_key_value,
    )


@router.get("", response_model=PushConfigOut)
async def push_status(
    profile: UserProfile = Depends(get_cookie_profile),
    session: AsyncSession = Depends(get_session),
) -> PushConfigOut:
    enabled, public_key, _ = _enabled_key()
    subscriptions = await web_push.list_subscriptions(session, profile.id) if enabled else []
    return PushConfigOut(
        enabled=enabled,
        application_server_key=public_key if enabled else None,
        subscriptions=[_out(value) for value in subscriptions],
    )


@router.put("", response_model=PushSubscriptionOut)
async def subscribe(
    body: PushSubscriptionCreate,
    profile: UserProfile = Depends(get_cookie_profile),
    session: AsyncSession = Depends(get_session),
) -> PushSubscriptionOut:
    enabled, _, encryption_key = _enabled_key()
    if not enabled or encryption_key is None:
        raise HTTPException(status_code=503, detail="Web Push is not configured")
    try:
        value = await web_push.upsert_subscription(session, profile.id, body, encryption_key)
    except web_push.PushError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return _out(value)


@router.delete("", status_code=204)
async def unsubscribe(
    body: PushSubscriptionDelete,
    profile: UserProfile = Depends(get_cookie_profile),
    session: AsyncSession = Depends(get_session),
) -> None:
    try:
        await web_push.unsubscribe(session, profile.id, str(body.endpoint))
    except web_push.PushError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
