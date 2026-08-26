"""Auth and DB dependencies.

Single-user model (decision D11): exactly one profile row, one password from
env, one HMAC-signed HttpOnly session cookie (decision D6). No JWTs — a
long-lived signed cookie is the right amount of machinery for a self-hosted
single-user PWA and keeps tokens out of JS-reachable storage.
"""

import hashlib
import hmac
import time
import uuid

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.models import UserProfile

SESSION_COOKIE = "plateos_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 365  # 1 year; standalone PWA stays logged in


def _sign(payload: str) -> str:
    return hmac.new(
        get_settings().session_secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()


def issue_session_token(user_id: uuid.UUID) -> str:
    expires = int(time.time()) + SESSION_TTL_SECONDS
    payload = f"{user_id}:{expires}"
    return f"{payload}:{_sign(payload)}"


def verify_session_token(token: str) -> uuid.UUID | None:
    try:
        uid_s, exp_s, sig = token.rsplit(":", 2)
        payload = f"{uid_s}:{exp_s}"
        if not hmac.compare_digest(sig, _sign(payload)):
            return None
        if int(exp_s) < time.time():
            return None
        return uuid.UUID(uid_s)
    except (ValueError, TypeError):
        return None


async def get_admin_profile(session: AsyncSession) -> UserProfile | None:
    """Primary admin account: the D19 bearer token acts as this user."""
    result = await session.execute(
        select(UserProfile)
        .where(UserProfile.is_admin.is_(True))
        .order_by(UserProfile.created_at)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_cookie_profile(
    request: Request, session: AsyncSession = Depends(get_session)
) -> UserProfile:
    """Profile auth restricted to the session cookie (decision D35).

    Settings endpoints deliberately do not accept the D19 bearer token: a
    leaked automation token must not be able to redirect LLM traffic toward
    an attacker endpoint (prompt/image exfiltration) or rewrite provider
    credentials.
    """
    token = request.cookies.get(SESSION_COOKIE)
    user_id = verify_session_token(token) if token else None
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    profile = await session.get(UserProfile, user_id)
    if profile is None:
        raise HTTPException(status_code=401, detail="Profile not found")
    return profile


async def require_admin(
    profile: UserProfile = Depends(get_cookie_profile),
) -> UserProfile:
    """Gate for user administration and runtime provider settings."""
    if not profile.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return profile


async def get_current_profile(
    request: Request, session: AsyncSession = Depends(get_session)
) -> UserProfile:
    token = request.cookies.get(SESSION_COOKIE)
    user_id = verify_session_token(token) if token else None

    # Apple Shortcuts / external automation: static bearer token (decision D19).
    if user_id is None:
        header = request.headers.get("authorization", "")
        api_token = get_settings().api_token
        if api_token and header.startswith("Bearer ") and hmac.compare_digest(header[7:], api_token):
            profile = await get_admin_profile(session)
            if profile is not None:
                return profile
            raise HTTPException(status_code=500, detail="No profile seeded")

    if user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    profile = await session.get(UserProfile, user_id)
    if profile is None:
        raise HTTPException(status_code=401, detail="Profile not found")
    return profile
