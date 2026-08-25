from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_profile
from app.db import get_session
from app.models import FoodItem, UserProfile
from app.schemas.api import FoodItemCreate, FoodItemOut
from app.services.openfoodfacts import fetch_product_by_barcode

router = APIRouter(prefix="/api/food-items", tags=["food"])


@router.get("", response_model=list[FoodItemOut])
async def list_food_items(
    q: Annotated[str, Query(max_length=255)] = "",
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    _profile: UserProfile = Depends(get_current_profile),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(FoodItem)
    if q:
        stmt = stmt.where(FoodItem.name.ilike(f"%{q}%"))
    stmt = stmt.order_by(FoodItem.name).limit(limit)
    return (await session.execute(stmt)).scalars().all()


@router.post("", response_model=FoodItemOut, status_code=201)
async def create_food_item(
    body: FoodItemCreate,
    _profile: UserProfile = Depends(get_current_profile),
    session: AsyncSession = Depends(get_session),
):
    item = FoodItem(
        barcode=body.barcode,
        name=body.name,
        brand=body.brand,
        serving_unit=body.serving_unit,
        calories_per_100=body.per100.calories,
        protein_per_100=body.per100.protein_g,
        carbs_per_100=body.per100.carbs_g,
        fat_per_100=body.per100.fat_g,
        fiber_per_100=body.per100.fiber_g,
        is_verified=True,  # user-entered data is considered verified
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


@router.get("/barcode/{code}", response_model=FoodItemOut)
async def get_food_item_by_barcode(
    code: Annotated[str, Path(min_length=1, max_length=64)],
    _profile: UserProfile = Depends(get_current_profile),
    session: AsyncSession = Depends(get_session),
):
    """Local cache first; on miss, look up Open Food Facts and cache the row."""
    cached = (
        await session.execute(select(FoodItem).where(FoodItem.barcode == code))
    ).scalar_one_or_none()
    if cached is not None:
        return cached

    off = await fetch_product_by_barcode(code)
    if off is None:
        raise HTTPException(status_code=404, detail=f"No product found for barcode {code}")

    item = FoodItem(
        barcode=code,
        name=off.name[:255],
        brand=off.brand[:255] if off.brand else None,
        calories_per_100=off.per100.calories,
        protein_per_100=off.per100.protein_g,
        carbs_per_100=off.per100.carbs_g,
        fat_per_100=off.per100.fat_g,
        fiber_per_100=off.per100.fiber_g,
        is_verified=False,  # crowd-sourced, unreviewed
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item
