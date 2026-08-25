import uuid
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from fastapi import HTTPException

from app.api.routes.meals import (
    _replay_mutation,
    _request_fingerprint,
    create_meal_log,
    update_meal_log,
)
from app.models import FoodItem, MealLog, MealLogMutation, UserProfile
from app.schemas.api import MealLogCreate, MealLogPatch


def meal_request(**overrides) -> MealLogCreate:
    values = {
        "client_mutation_id": uuid.uuid4(),
        "logged_at": "2026-08-25T12:00:00Z",
        "custom_name": "Test",
        "quantity_g": 5,
        "per100": {
            "calories": 209,
            "protein_g": 0,
            "carbs_g": 0,
            "fat_g": 0,
            "fiber_g": 0,
        },
        "source_type": "manual",
    }
    values.update(overrides)
    return MealLogCreate(**values)


def test_fingerprint_ignores_key_and_normalizes_timestamp_offset():
    first = meal_request(client_mutation_id=uuid.uuid4())
    second = meal_request(
        client_mutation_id=uuid.uuid4(),
        logged_at=datetime(
            2026, 8, 25, 13, tzinfo=timezone(timedelta(hours=1))
        ),
    )
    assert _request_fingerprint(first) == _request_fingerprint(second)
    assert _request_fingerprint(first) != _request_fingerprint(
        meal_request(quantity_g=6)
    )


def test_fingerprint_normalizes_signed_density_zero():
    positive = meal_request(
        per100={"calories": 1, "protein_g": 0.0, "carbs_g": 0, "fat_g": 0}
    )
    negative = meal_request(
        per100={"calories": 1, "protein_g": -0.0, "carbs_g": 0, "fat_g": 0}
    )
    assert _request_fingerprint(positive) == _request_fingerprint(negative)


class FakeSession:
    def __init__(self, log: MealLog):
        self.log = log

    async def get(self, _model, _key):
        return self.log

    def add(self, _value):
        return None

    async def commit(self):
        return None

    async def refresh(self, _value):
        return None


class CreateSession:
    def __init__(self, item: FoodItem):
        self.item = item
        self.added: list[object] = []

    async def get(self, model, _key):
        return self.item if model is FoodItem else None

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None

    async def commit(self):
        return None

    async def rollback(self):
        return None

    async def refresh(self, _value):
        return None


class ReplaySession:
    def __init__(self, mutation: MealLogMutation, log: MealLog | None):
        self.mutation = mutation
        self.log = log

    async def get(self, model, _key):
        if model is MealLogMutation:
            return self.mutation
        if model is MealLog:
            return self.log
        return None


@pytest.mark.asyncio
async def test_replay_returns_original_log_for_matching_fingerprint():
    user_id = uuid.uuid4()
    mutation_id = uuid.uuid4()
    log = MealLog(id=uuid.uuid4(), user_id=user_id)
    mutation = MealLogMutation(
        user_id=user_id,
        client_mutation_id=mutation_id,
        request_fingerprint="same",
        meal_log_id=log.id,
    )
    replay = await _replay_mutation(
        ReplaySession(mutation, log),  # type: ignore[arg-type]
        user_id=user_id,
        client_mutation_id=mutation_id,
        request_fingerprint="same",
    )
    assert replay is log


@pytest.mark.asyncio
async def test_replay_rejects_changed_payload_or_deleted_original():
    user_id = uuid.uuid4()
    mutation_id = uuid.uuid4()
    mutation = MealLogMutation(
        user_id=user_id,
        client_mutation_id=mutation_id,
        request_fingerprint="original",
        meal_log_id=uuid.uuid4(),
    )
    with pytest.raises(HTTPException, match="different payload") as changed:
        await _replay_mutation(
            ReplaySession(mutation, None),  # type: ignore[arg-type]
            user_id=user_id,
            client_mutation_id=mutation_id,
            request_fingerprint="changed",
        )
    assert changed.value.status_code == 409

    mutation.meal_log_id = None
    with pytest.raises(HTTPException, match="was deleted") as deleted:
        await _replay_mutation(
            ReplaySession(mutation, None),  # type: ignore[arg-type]
            user_id=user_id,
            client_mutation_id=mutation_id,
            request_fingerprint="original",
        )
    assert deleted.value.status_code == 409


@pytest.mark.asyncio
async def test_create_preserves_valid_legacy_food_density():
    user_id = uuid.uuid4()
    food_id = uuid.uuid4()
    item = FoodItem(
        id=food_id,
        name="Legacy",
        serving_unit="g",
        calories_per_100=Decimal("100"),
        protein_per_100=Decimal("100.01"),
        carbs_per_100=Decimal("0"),
        fat_per_100=Decimal("0"),
        fiber_per_100=Decimal("0"),
        is_verified=True,
    )
    session = CreateSession(item)
    created = await create_meal_log(
        MealLogCreate(
            food_item_id=food_id,
            custom_name="Legacy",
            quantity_g=100,
            source_type="barcode",
        ),
        UserProfile(id=user_id),
        session,  # type: ignore[arg-type]
    )
    assert float(created.calculated_protein) == 100.0
    assert created.protein_per_100 == Decimal("100.01")


@pytest.mark.asyncio
async def test_patch_recomputes_from_density_snapshot_not_rounded_total():
    user_id = uuid.uuid4()
    log = MealLog(
        id=uuid.uuid4(),
        user_id=user_id,
        food_item_id=None,
        custom_name="Low-density item",
        logged_at=datetime.now(UTC),
        quantity_g=Decimal("1.00"),
        calories_per_100=Decimal("1.0000"),
        protein_per_100=Decimal("0"),
        carbs_per_100=Decimal("0"),
        fat_per_100=Decimal("0"),
        fiber_per_100=Decimal("0"),
        calculated_calories=Decimal("0.0"),
        calculated_protein=Decimal("0"),
        calculated_carbs=Decimal("0"),
        calculated_fat=Decimal("0"),
        calculated_fiber=Decimal("0"),
        source_type="manual",
    )
    profile = UserProfile(id=user_id)
    session = FakeSession(log)

    updated = await update_meal_log(
        log.id, MealLogPatch(quantity_g=100), profile, session  # type: ignore[arg-type]
    )
    assert float(updated.calculated_calories) == 1.0

    await update_meal_log(
        log.id, MealLogPatch(quantity_g=1), profile, session  # type: ignore[arg-type]
    )
    updated_again = await update_meal_log(
        log.id, MealLogPatch(quantity_g=100), profile, session  # type: ignore[arg-type]
    )
    assert float(updated_again.calculated_calories) == 1.0
