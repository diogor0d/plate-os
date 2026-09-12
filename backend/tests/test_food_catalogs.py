"""Versioned official catalogue search and candidate proof tests."""

import uuid

import pytest

from app.api.routes import food
from app.models import UserProfile
from app.services.food_catalogs import load_catalog, search_catalog
from app.services.product_candidates import verify_candidate_proof


@pytest.mark.parametrize(
    ("source", "expected_version", "expected_count"),
    [
        ("ciqual", "2025-11-19", 2855),
        ("swedish_food_agency", "2026-07-01", 2605),
    ],
)
def test_catalogues_are_pinned_and_all_records_fit_plateos_contract(
    source, expected_version, expected_count
):
    catalog = load_catalog(source)

    assert catalog.version == expected_version
    assert len(catalog.foods) == expected_count
    assert all(item.per100 for item in catalog.foods)


def test_catalog_search_is_accent_insensitive_and_deterministic():
    exact = search_catalog("ciqual", "acerola juice, fresh", 5)
    accented = search_catalog("ciqual", "acerola", 5)

    assert exact[0].id == "2040"
    assert accented[0].id == "2040"
    assert exact[0].per100.calories == 22.9
    assert search_catalog("ciqual", "not-an-official-food-record", 10) == []


def test_swedish_catalog_uses_english_and_swedish_names():
    english = search_catalog("swedish_food_agency", "beef tallow", 5)
    swedish = search_catalog("swedish_food_agency", "nöt talg", 5)

    assert english[0].id == "1"
    assert swedish[0].id == "1"
    assert english[0].per100.fat_g == 100


@pytest.mark.asyncio
async def test_search_returns_ephemeral_account_bound_candidates():
    profile = UserProfile(id=uuid.uuid4())

    candidates = await food.search_food_candidates(
        q="acerola", source="ciqual", limit=2, profile=profile
    )

    assert candidates
    candidate = candidates[0]
    assert candidate.source == "ciqual"
    assert candidate.source_id == "2040"
    assert candidate.source_version == "2025-11-19"
    assert candidate.barcode is None
    assert candidate.acceptance_proof
    verify_candidate_proof(
        candidate.acceptance_proof,
        user_id=profile.id,
        source=candidate.source,
        source_id=candidate.source_id,
        source_version=candidate.source_version,
        barcode=candidate.barcode,
        name=candidate.name,
        brand=candidate.brand,
        serving_unit=candidate.serving_unit,
        per100=candidate.per100,
    )
