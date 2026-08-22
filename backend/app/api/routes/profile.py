from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_profile
from app.db import get_session
from app.models import UserProfile
from app.schemas.api import UserProfileOut, UserProfileUpdate

router = APIRouter(prefix="/api/profile", tags=["profile"])


@router.get("", response_model=UserProfileOut)
async def get_profile(profile: UserProfile = Depends(get_current_profile)):
    return profile


@router.put("", response_model=UserProfileOut)
async def update_profile(
    body: UserProfileUpdate,
    profile: UserProfile = Depends(get_current_profile),
    session: AsyncSession = Depends(get_session),
):
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(profile, key, value)
    session.add(profile)
    await session.commit()
    await session.refresh(profile)
    return profile
