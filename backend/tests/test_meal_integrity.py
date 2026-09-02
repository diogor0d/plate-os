import uuid
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from fastapi import HTTPException

from app.api.routes.meals import (
    _replay_mutation,
    _request_fingerprint,
    create_meal_log,
    delete_meal_log,
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


class DeleteSession:
    def __init__(self, linked_occurrence_id: uuid.UUID | None):
        self.linked_occurrence_id = linked_occurrence_id
        self.execute_called = False

    async def scalar(self, _statement):
        return self.linked_occurrence_id

    async def execute(self, _statement):
        self.execute_called = True
        raise AssertionError("linked meal must not reach DELETE")


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
        accepted_at=datetime.now(UTC),
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
async def test_create_rejects_archived_product():
    item = FoodItem(id=uuid.uuid4(), archived_at=datetime.now(UTC), accepted_at=datetime.now(UTC))
    with pytest.raises(HTTPException, match="Archived products") as exc_info:
        await create_meal_log(
            meal_request(food_item_id=item.id, per100=None),
            UserProfile(id=uuid.uuid4()),
            CreateSession(item),  # type: ignore[arg-type]
        )
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_delete_linked_meal_returns_conflict_before_foreign_key_failure():
    session = DeleteSession(uuid.uuid4())
    with pytest.raises(HTTPException, match="linked to a routine occurrence") as exc_info:
        await delete_meal_log(
            uuid.uuid4(), UserProfile(id=uuid.uuid4()), session  # type: ignore[arg-type]
        )
    assert exc_info.value.status_code == 409
    assert not session.execute_called


@pytest.mark.asyncio
async def test_create_rejects_mismatched_expected_owner_before_writing():
    authenticated_user_id = uuid.uuid4()
    queued_owner_id = uuid.uuid4()
    session = CreateSession(
        FoodItem(
            id=uuid.uuid4(),
            name="Unused",
            serving_unit="g",
            calories_per_100=Decimal("1"),
            protein_per_100=Decimal("1"),
            carbs_per_100=Decimal("1"),
            fat_per_100=Decimal("1"),
            fiber_per_100=Decimal("1"),
        )
    )

    with pytest.raises(HTTPException, match="queued meal owner") as mismatch:
        await create_meal_log(
            meal_request(),
            UserProfile(id=authenticated_user_id),
            session,  # type: ignore[arg-type]
            str(queued_owner_id),
        )

    assert mismatch.value.status_code == 409
    assert session.added == []


@pytest.mark.asyncio
async def test_create_still_supports_callers_without_expected_owner():
    user_id = uuid.uuid4()
    session = CreateSession(
        FoodItem(
            id=uuid.uuid4(),
            name="Unused",
            serving_unit="g",
            calories_per_100=Decimal("1"),
            protein_per_100=Decimal("1"),
            carbs_per_100=Decimal("1"),
            fat_per_100=Decimal("1"),
            fiber_per_100=Decimal("1"),
        )
    )

    created = await create_meal_log(
        meal_request(), UserProfile(id=user_id), session  # type: ignore[arg-type]
    )

    assert created.user_id == user_id


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
