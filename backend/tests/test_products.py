"""Reviewed-product mutation and vision candidate behavior."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api.routes import food, vision
from app.models import FoodItem, FoodItemMutation, UserProfile
from app.schemas.api import VisionParseRequest
from app.schemas.llm_contracts import NutritionLabelExtraction, Per100Values
from app.schemas.products import ProductArchive, ProductCreate, ProductUpdate
from app.services.llm import LLMError
from app.services.product_candidates import (
    CandidateProofError,
    issue_candidate_proof,
    verify_candidate_proof,
)


class ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class MutationSession:
    def __init__(self, selected=None, scalar=False):
        self.selected = selected
        self.scalar_value = scalar
        self.items: dict[uuid.UUID, FoodItem] = {}
        self.mutations: dict[tuple[uuid.UUID, uuid.UUID], FoodItemMutation] = {}
        self.pending: list[object] = []
        self.execute = AsyncMock(side_effect=lambda _stmt: ScalarResult(self.selected))
        self.commit = AsyncMock(side_effect=self._commit)
        self.rollback = AsyncMock()
        self.refresh = AsyncMock()

    async def get(self, model, key):
        if model is FoodItemMutation:
            return self.mutations.get((key["user_id"], key["client_mutation_id"]))
        if model is FoodItem:
            return self.items.get(key)
        raise AssertionError(f"Unexpected model {model}")

    async def scalar(self, _stmt):
        return self.scalar_value

    def add(self, value):
        self.pending.append(value)

    async def flush(self):
        for value in self.pending:
            if isinstance(value, FoodItem) and value.id is None:
                value.id = uuid.uuid4()

    async def _commit(self):
        await self.flush()
        for value in self.pending:
            if isinstance(value, FoodItem):
                self.items[value.id] = value
            elif isinstance(value, FoodItemMutation):
                self.mutations[(value.user_id, value.client_mutation_id)] = value
        self.pending.clear()


def profile() -> UserProfile:
    return UserProfile(id=uuid.uuid4())


def per100() -> Per100Values:
    return Per100Values(calories=100, protein_g=10, carbs_g=20, fat_g=5, fiber_g=2)


def product(**overrides) -> FoodItem:
    now = datetime.now(timezone.utc)
    values = {
        "id": uuid.uuid4(),
        "barcode": "123",
        "name": "Product",
        "brand": None,
        "serving_unit": "g",
        "calories_per_100": 100,
        "protein_per_100": 10,
        "carbs_per_100": 20,
        "fat_per_100": 5,
        "fiber_per_100": 2,
        "nutrition_source": "manual",
        "accepted_at": now,
        "updated_at": now,
        "version": 1,
        "archived_at": None,
    }
    values.update(overrides)
    return FoodItem(**values)


@pytest.mark.asyncio
async def test_create_is_explicit_audited_and_records_replay_ledger():
    user = profile()
    session = MutationSession()
    proof = issue_candidate_proof(
        user_id=user.id,
        source="open_food_facts",
        barcode="123",
        name="Accepted candidate",
        brand=None,
        serving_unit="g",
        per100=per100(),
    )
    body = ProductCreate(
        client_mutation_id=uuid.uuid4(),
        barcode="123",
        name="Accepted candidate",
        per100=per100(),
        nutrition_source="open_food_facts",
        acceptance_proof=proof,
    )

    result = await food.create_food_item(body, user, session)

    assert result.accepted_by_user_id == user.id
    assert result.nutrition_source == "open_food_facts"
    assert result.version == 1
    mutation = session.mutations[(user.id, body.client_mutation_id)]
    assert mutation.operation == "create"
    assert mutation.food_item_id == result.id


@pytest.mark.asyncio
async def test_same_mutation_replays_but_changed_payload_conflicts():
    user = profile()
    session = MutationSession()
    mutation_id = uuid.uuid4()
    original = ProductCreate(
        client_mutation_id=mutation_id,
        name="Original",
        per100=per100(),
        nutrition_source="manual",
    )
    created = await food.create_food_item(original, user, session)

    assert await food.create_food_item(original, user, session) is created
    changed = original.model_copy(update={"name": "Changed"})
    with pytest.raises(HTTPException) as exc_info:
        await food.create_food_item(changed, user, session)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_external_create_requires_matching_candidate_proof():
    user = profile()
    body = ProductCreate(
        client_mutation_id=uuid.uuid4(),
        name="Unproven",
        per100=per100(),
        nutrition_source="vision_label",
    )
    with pytest.raises(HTTPException, match="require acceptance proof") as exc_info:
        await food.create_food_item(body, user, MutationSession())
    assert exc_info.value.status_code == 422

    manual = body.model_copy(
        update={"nutrition_source": "manual", "acceptance_proof": "client-asserted"}
    )
    with pytest.raises(HTTPException, match="Manual products cannot"):
        await food.create_food_item(manual, user, MutationSession())


@pytest.mark.asyncio
async def test_update_requires_current_version_and_preserves_provenance():
    user = profile()
    item = product(version=3, nutrition_source="vision_label")
    stale_session = MutationSession(selected=item)
    stale = ProductUpdate(
        client_mutation_id=uuid.uuid4(), expected_version=2, name="Edit", per100=per100()
    )

    with pytest.raises(HTTPException) as exc_info:
        await food.update_food_item(item.id, stale, user, stale_session)
    assert exc_info.value.status_code == 409

    body = stale.model_copy(update={"client_mutation_id": uuid.uuid4(), "expected_version": 3})
    result = await food.update_food_item(item.id, body, user, MutationSession(selected=item))
    assert result.version == 4
    assert result.nutrition_source == "vision_label"


@pytest.mark.asyncio
async def test_archive_versions_without_deleting_product():
    user = profile()
    item = product(version=2)
    session = MutationSession(selected=item)
    body = ProductArchive(client_mutation_id=uuid.uuid4(), expected_version=2)

    result = await food.archive_food_item(item.id, body, user, session)

    assert result.archived_at is not None
    assert result.version == 3
    assert item.id in session.items or session.selected is item


@pytest.mark.asyncio
async def test_archive_rejects_product_used_by_active_defined_routine():
    user = profile()
    item = product(version=2)
    with pytest.raises(HTTPException, match="active defined routine") as exc_info:
        await food.archive_food_item(
            item.id,
            ProductArchive(client_mutation_id=uuid.uuid4(), expected_version=2),
            user,
            MutationSession(selected=item, scalar=True),
        )
    assert exc_info.value.status_code == 409


def test_candidate_proof_rejects_tampering_expiry_and_source_mismatch():
    user_id = uuid.uuid4()
    issued_at = datetime(2026, 9, 2, 12, tzinfo=timezone.utc)
    proof = issue_candidate_proof(
        user_id=user_id,
        source="open_food_facts",
        barcode="123",
        name="Product",
        brand=None,
        serving_unit="g",
        per100=per100(),
        now=issued_at,
    )
    common = {
        "proof": proof,
        "user_id": user_id,
        "source": "open_food_facts",
        "barcode": "123",
        "name": "Product",
        "brand": None,
        "serving_unit": "g",
        "per100": per100(),
        "now": issued_at,
    }
    verify_candidate_proof(**common)
    with pytest.raises(CandidateProofError, match="does not match"):
        verify_candidate_proof(**{**common, "name": "Tampered"})
    with pytest.raises(CandidateProofError, match="does not match"):
        verify_candidate_proof(**{**common, "source": "vision_label"})
    with pytest.raises(CandidateProofError, match="expired"):
        verify_candidate_proof(
            **{**common, "now": datetime(2026, 9, 2, 12, 11, tzinfo=timezone.utc)}
        )


class FakeLLM:
    model = "test-vision-model"

    async def extract_json(self, **_kwargs):
        return NutritionLabelExtraction(
            product_name=None,
            basis="per_100g",
            calories=100,
            protein_g=0,
            carbs_g=20,
            fat_g=5,
            fiber_g=0,
            confidence_score=0.8,
        )


@pytest.mark.asyncio
async def test_vision_is_stateless_candidate_and_only_echoes_scanner_barcode(monkeypatch):
    monkeypatch.setattr(vision, "get_llm", lambda _task: FakeLLM())

    result = await vision.parse_label(
        VisionParseRequest(image_base64="abc"), "scanner-code", profile()
    )

    assert result.source == "vision_label"
    assert result.barcode == "scanner-code"
    assert result.name == "Barcode scanner-code"
    assert result.issues == ["missing_name", "missing_protein", "missing_fiber"]
    assert result.acceptance_proof


class FailingLLM:
    model = "retired-model"

    async def extract_json(self, **_kwargs):
        raise LLMError("invalid provider output")


@pytest.mark.asyncio
async def test_vision_returns_actionable_provider_failure(monkeypatch):
    monkeypatch.setattr(vision, "get_llm", lambda _task: FailingLLM())

    with pytest.raises(HTTPException) as exc_info:
        await vision.parse_label(VisionParseRequest(image_base64="abc"), None, profile())

    assert exc_info.value.status_code == 502
    assert "could not validate" in exc_info.value.detail
