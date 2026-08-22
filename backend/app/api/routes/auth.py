import hmac

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    SESSION_COOKIE,
    SESSION_TTL_SECONDS,
    get_default_profile,
    issue_session_token,
)
from app.config import get_settings
from app.db import get_session
from app.schemas.api import LoginRequest

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
async def login(
    body: LoginRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    if not hmac.compare_digest(body.password, get_settings().app_password):
        raise HTTPException(status_code=401, detail="Invalid password")
    profile = await get_default_profile(session)
    if profile is None:
        raise HTTPException(status_code=500, detail="No profile seeded")
    response.set_cookie(
        key=SESSION_COOKIE,
        value=issue_session_token(profile.id),
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="strict",
        secure=get_settings().cookie_secure,
        path="/",
    )
    return {"ok": True}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}
