"""Local user administration (decision D36).

Admin-only listing/creation/resets; every account can change its own password
with the current one. No email flows: administration happens on the server.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_cookie_profile, require_admin
from app.db import get_session
from app.models import UserProfile
from app.schemas.api import (
    PasswordChange,
    PasswordReset,
    UserCreate,
    UserOut,
)
from app.services.accounts import (
    AccountError,
    hash_password,
    validate_password,
    validate_username,
    verify_password,
)

router = APIRouter(prefix="/api/users", tags=["users"])


def _apply_credentials(user: UserProfile, password: str) -> None:
    try:
        validate_password(password)
    except AccountError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    user.password_hash = hash_password(password)


@router.get("", response_model=list[UserOut])
async def list_users(_admin: UserProfile = Depends(require_admin),
                     session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(UserProfile).order_by(UserProfile.created_at)
    )
    return result.scalars().all()


@router.post("", response_model=UserOut, status_code=201)
async def create_user(
    body: UserCreate,
    _admin: UserProfile = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    try:
        validate_username(body.username)
        validate_password(body.password)
    except AccountError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    exists = await session.scalar(
        select(UserProfile.id).where(UserProfile.username == body.username)
    )
    if exists is not None:
        raise HTTPException(status_code=409, detail="Username already taken")

    user = UserProfile(
        username=body.username,
        password_hash=hash_password(body.password),
        is_admin=False,
        weight_kg=75,
        height_cm=178,
        timezone=body.timezone,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@router.patch("/me/password")
async def change_own_password(
    body: PasswordChange,
    profile: UserProfile = Depends(get_cookie_profile),
    session: AsyncSession = Depends(get_session),
):
    if not verify_password(body.current_password, profile.password_hash):
        raise HTTPException(status_code=403, detail="Current password is incorrect")
    _apply_credentials(profile, body.new_password)
    await session.commit()
    return {"ok": True}


@router.patch("/{user_id}/password")
async def reset_password(
    user_id: uuid.UUID,
    body: PasswordReset,
    admin: UserProfile = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    if user_id == admin.id:
        raise HTTPException(
            status_code=400,
            detail="Use change-password with your current password for your own account",
        )
    user = await session.get(UserProfile, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    _apply_credentials(user, body.new_password)
    await session.commit()
    return {"ok": True}
