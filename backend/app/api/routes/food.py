import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel
from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_profile
from app.db import get_session
from app.models import FoodItem, FoodItemMutation, MealRoutine, MealRoutineItem, UserProfile
from app.schemas.products import (
    AcceptedResolution,
    BarcodeResolution,
    CandidateResolution,
    NotFoundResolution,
    ProductArchive,
    ProductCandidate,
    ProductCreate,
    ProductOut,
    ProductUpdate,
)
from app.services.openfoodfacts import OFFUpstreamError, fetch_product_by_barcode
from app.services.product_candidates import (
    CandidateProofError,
    issue_candidate_proof,
    verify_candidate_proof,
)

router = APIRouter(prefix="/api/food-items", tags=["food"])


def _fingerprint(operation: str, resource_id: uuid.UUID | None, body: BaseModel) -> str:
    payload = body.model_dump(mode="json", exclude={"client_mutation_id"})
    canonical = json.dumps(
        {"operation": operation, "resource_id": str(resource_id) if resource_id else None, "body": payload},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


async def _replay(
    session: AsyncSession,
    profile: UserProfile,
    mutation_id: uuid.UUID,
    operation: str,
    fingerprint: str,
) -> FoodItem | None:
    mutation = await session.get(
        FoodItemMutation,
        {"user_id": profile.id, "client_mutation_id": mutation_id},
    )
    if mutation is None:
        return None
    if mutation.operation != operation or mutation.request_fingerprint != fingerprint:
        raise HTTPException(
            status_code=409,
            detail="client_mutation_id was already used with a different mutation",
        )
    if mutation.food_item_id is None:
        raise HTTPException(status_code=409, detail="Product mutation record is inconsistent")
    item = await session.get(FoodItem, mutation.food_item_id)
    if item is None:
        raise HTTPException(status_code=409, detail="Product mutation record is inconsistent")
    return item


async def _commit_mutation(
    session: AsyncSession,
    profile: UserProfile,
    mutation_id: uuid.UUID,
    operation: str,
    fingerprint: str,
    item: FoodItem,
) -> None:
    session.add(
        FoodItemMutation(
            user_id=profile.id,
            client_mutation_id=mutation_id,
            operation=operation,
            request_fingerprint=fingerprint,
            food_item_id=item.id,
        )
    )
    await session.commit()


@router.get("", response_model=list[ProductOut])
async def list_food_items(
    q: Annotated[str, Query(max_length=255)] = "",
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    include_archived: bool = False,
    _profile: UserProfile = Depends(get_current_profile),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(FoodItem).where(FoodItem.accepted_at.is_not(None))
    if not include_archived:
        stmt = stmt.where(FoodItem.archived_at.is_(None))
    if q:
        stmt = stmt.where(FoodItem.name.ilike(f"%{q}%"))
    stmt = stmt.order_by(FoodItem.name).limit(limit)
    return (await session.execute(stmt)).scalars().all()


@router.post("", response_model=ProductOut, status_code=201)
async def create_food_item(
    body: ProductCreate,
    profile: UserProfile = Depends(get_current_profile),
    session: AsyncSession = Depends(get_session),
):
    fingerprint = _fingerprint("create", None, body)
    replay = await _replay(session, profile, body.client_mutation_id, "create", fingerprint)
    if replay is not None:
        return replay

    if body.nutrition_source == "manual":
        if body.acceptance_proof is not None:
            raise HTTPException(status_code=422, detail="Manual products cannot use candidate proof")
    else:
        if body.acceptance_proof is None:
            raise HTTPException(status_code=422, detail="External candidates require acceptance proof")
        try:
            verify_candidate_proof(
                body.acceptance_proof,
                user_id=profile.id,
                source=body.nutrition_source,
                barcode=body.barcode,
                name=body.name,
                brand=body.brand,
                serving_unit=body.serving_unit,
                per100=body.per100,
            )
        except CandidateProofError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    now = datetime.now(timezone.utc)
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
        nutrition_source=body.nutrition_source,
        accepted_by_user_id=profile.id,
        accepted_at=now,
        updated_at=now,
        version=1,
    )
    try:
        session.add(item)
        await session.flush()
        await _commit_mutation(
            session, profile, body.client_mutation_id, "create", fingerprint, item
        )
    except IntegrityError:
        await session.rollback()
        replay = await _replay(
            session, profile, body.client_mutation_id, "create", fingerprint
        )
        if replay is not None:
            return replay
        raise HTTPException(status_code=409, detail="Barcode is already assigned") from None
    await session.refresh(item)
    return item


@router.patch("/{product_id}", response_model=ProductOut)
async def update_food_item(
    product_id: uuid.UUID,
    body: ProductUpdate,
    profile: UserProfile = Depends(get_current_profile),
    session: AsyncSession = Depends(get_session),
):
    fingerprint = _fingerprint("update", product_id, body)
    replay = await _replay(session, profile, body.client_mutation_id, "update", fingerprint)
    if replay is not None:
        return replay

    item = (
        await session.execute(
            select(FoodItem).where(FoodItem.id == product_id).with_for_update()
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Product not found")
    if item.archived_at is not None:
        raise HTTPException(status_code=409, detail="Archived products cannot be updated")
    if item.version != body.expected_version:
        raise HTTPException(status_code=409, detail="Product version is stale")

    item.name = body.name
    item.brand = body.brand
    item.serving_unit = body.serving_unit
    item.calories_per_100 = body.per100.calories
    item.protein_per_100 = body.per100.protein_g
    item.carbs_per_100 = body.per100.carbs_g
    item.fat_per_100 = body.per100.fat_g
    item.fiber_per_100 = body.per100.fiber_g
    item.updated_at = datetime.now(timezone.utc)
    item.version += 1
    try:
        await _commit_mutation(
            session, profile, body.client_mutation_id, "update", fingerprint, item
        )
    except IntegrityError:
        await session.rollback()
        replay = await _replay(
            session, profile, body.client_mutation_id, "update", fingerprint
        )
        if replay is not None:
            return replay
        raise HTTPException(status_code=409, detail="Product update conflicted") from None
    await session.refresh(item)
    return item


@router.post("/{product_id}/archive", response_model=ProductOut)
async def archive_food_item(
    product_id: uuid.UUID,
    body: ProductArchive,
    profile: UserProfile = Depends(get_current_profile),
    session: AsyncSession = Depends(get_session),
):
    fingerprint = _fingerprint("archive", product_id, body)
    replay = await _replay(session, profile, body.client_mutation_id, "archive", fingerprint)
    if replay is not None:
        return replay

    item = (
        await session.execute(
            select(FoodItem).where(FoodItem.id == product_id).with_for_update()
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Product not found")
    if item.archived_at is not None or item.version != body.expected_version:
        raise HTTPException(status_code=409, detail="Product version is stale")
    used_by_active_routine = await session.scalar(
        select(
            exists().where(
                MealRoutineItem.food_item_id == item.id,
                MealRoutine.id == MealRoutineItem.routine_id,
                MealRoutine.mode == "defined",
                MealRoutine.archived_at.is_(None),
            )
        )
    )
    if used_by_active_routine:
        raise HTTPException(
            status_code=409,
            detail="Product is used by an active defined routine",
        )
    now = datetime.now(timezone.utc)
    item.archived_at = now
    item.updated_at = now
    item.version += 1
    try:
        await _commit_mutation(
            session, profile, body.client_mutation_id, "archive", fingerprint, item
        )
    except IntegrityError:
        await session.rollback()
        replay = await _replay(
            session, profile, body.client_mutation_id, "archive", fingerprint
        )
        if replay is not None:
            return replay
        raise HTTPException(status_code=409, detail="Product archive conflicted") from None
    await session.refresh(item)
    return item


@router.get("/barcode/{code}", response_model=BarcodeResolution)
async def get_food_item_by_barcode(
    code: Annotated[str, Path(min_length=1, max_length=64)],
    _profile: UserProfile = Depends(get_current_profile),
    session: AsyncSession = Depends(get_session),
):
    accepted = (
        await session.execute(
            select(FoodItem).where(
                FoodItem.barcode == code,
                FoodItem.accepted_at.is_not(None),
                FoodItem.archived_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if accepted is not None:
        return AcceptedResolution(kind="accepted", product=ProductOut.model_validate(accepted))

    try:
        off = await fetch_product_by_barcode(code)
    except OFFUpstreamError as exc:
        raise HTTPException(status_code=502, detail="Open Food Facts lookup failed") from exc
    if off is None:
        return NotFoundResolution(kind="not_found", barcode=code)
    retrieved_at = datetime.now(timezone.utc)
    candidate = ProductCandidate(
        source="open_food_facts",
        barcode=code,
        name=off.name,
        brand=off.brand,
        per100=off.per100,
        retrieved_at=retrieved_at,
        issues=off.issues,
        acceptance_proof="pending",
    )
    candidate.acceptance_proof = issue_candidate_proof(
        user_id=_profile.id,
        source=candidate.source,
        barcode=candidate.barcode,
        name=candidate.name,
        brand=candidate.brand,
        serving_unit=candidate.serving_unit,
        per100=candidate.per100,
        now=retrieved_at,
    )
    return CandidateResolution(kind="candidate", candidate=candidate)
