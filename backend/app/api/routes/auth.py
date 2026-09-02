from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    SESSION_COOKIE,
    SESSION_TTL_SECONDS,
    get_current_profile,
    issue_session_token,
)
from app.config import get_settings
from app.db import get_session
from app.models import UserProfile
from app.schemas.api import LoginRequest, MeOut
from app.services.accounts import verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


async def _authenticate(
    session: AsyncSession, body: LoginRequest
) -> UserProfile:
    if body.username is not None:
        result = await session.execute(
            select(UserProfile).where(UserProfile.username == body.username)
        )
        user = result.scalar_one_or_none()
        if user is None or not verify_password(body.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        return user

    # Username omitted (Shortcuts / single-user convenience): only acceptable
    # while exactly one account exists.
    count = await session.scalar(select(func.count()).select_from(UserProfile))
    if count != 1:
        raise HTTPException(
            status_code=400, detail="Username is required when multiple accounts exist"
        )
    user = (
        await session.execute(select(UserProfile).limit(1))
    ).scalar_one()
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return user


@router.post("/login")
async def login(
    body: LoginRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    user = await _authenticate(session, body)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=issue_session_token(user.id),
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="strict",
        secure=get_settings().cookie_secure,
        path="/",
    )
    return {"ok": True}


@router.get("/me", response_model=MeOut)
async def me(profile: UserProfile = Depends(get_current_profile)):
    return MeOut(id=profile.id, username=profile.username or "unknown", is_admin=profile.is_admin)


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}
