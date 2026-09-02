"""Deterministic Open Food Facts service and barcode resolution tests."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

from app.api.routes import food
from app.models import FoodItem, UserProfile
from app.schemas.llm_contracts import Per100Values
from app.services import openfoodfacts
from app.services.openfoodfacts import OFFResult, OFFUpstreamError


class FakeResponse:
    def __init__(self, status_code: int, payload: object):
        self.status_code = status_code
        self.payload = payload

    def json(self) -> object:
        if isinstance(self.payload, ValueError):
            raise self.payload
        return self.payload


class FakeHttpClient:
    def __init__(self, response: FakeResponse | None = None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.requested_url: str | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def get(self, url: str) -> FakeResponse:
        self.requested_url = url
        if self.error:
            raise self.error
        assert self.response is not None
        return self.response


def install_http_client(
    monkeypatch, status_code: int = 200, payload: object = None, error: Exception | None = None
) -> FakeHttpClient:
    client = FakeHttpClient(FakeResponse(status_code, payload), error)

    def make_client(*, timeout, headers):
        assert timeout == 10
        assert headers == {"User-Agent": openfoodfacts.USER_AGENT}
        return client

    monkeypatch.setattr(openfoodfacts.httpx, "AsyncClient", make_client)
    monkeypatch.setattr(
        openfoodfacts, "resolve_openfoodfacts_base_url", lambda: "https://off.test/api/v2"
    )
    return client


@pytest.mark.asyncio
async def test_off_success_preserves_missing_fields_as_candidate_issues(monkeypatch):
    client = install_http_client(
        monkeypatch,
        payload={
            "product": {
                "product_name": "Greek Yogurt",
                "brands": " Example Foods, Other Brand ",
                "nutriments": {
                    "energy-kcal_100g": 123.456,
                    "proteins_100g": 8.2,
                    "fat_100g": 7,
                },
            }
        },
    )

    result = await openfoodfacts.fetch_product_by_barcode("5601234567890")

    assert client.requested_url == "https://off.test/api/v2/product/5601234567890.json"
    assert result == OFFResult(
        name="Greek Yogurt",
        brand="Example Foods",
        per100=Per100Values(
            calories=123.46, protein_g=8.2, carbs_g=0, fat_g=7, fiber_g=0
        ),
        issues=["missing_carbs", "missing_fiber"],
    )


@pytest.mark.asyncio
async def test_off_converts_kilojoules_and_marks_missing_name(monkeypatch):
    install_http_client(
        monkeypatch,
        payload={
            "product": {
                "nutriments": {
                    "energy_100g": 418.4,
                    "proteins_100g": 1,
                    "carbohydrates_100g": 2,
                    "fat_100g": 3,
                    "fiber_100g": 0,
                }
            }
        },
    )

    result = await openfoodfacts.fetch_product_by_barcode("123")

    assert result is not None
    assert result.name == "Barcode 123"
    assert result.per100.calories == 100
    assert result.issues == ["missing_name"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "payload"),
    [(404, {}), (200, {"status": 0, "product": None})],
)
async def test_off_authoritative_not_found_returns_none(monkeypatch, status_code, payload):
    install_http_client(monkeypatch, status_code, payload)
    assert await openfoodfacts.fetch_product_by_barcode("missing") is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "payload"),
    [(503, {}), (200, {}), (200, ValueError("bad json"))],
)
async def test_off_upstream_failures_are_not_reported_as_not_found(
    monkeypatch, status_code, payload
):
    install_http_client(monkeypatch, status_code, payload)
    with pytest.raises(OFFUpstreamError):
        await openfoodfacts.fetch_product_by_barcode("unknown")


@pytest.mark.asyncio
async def test_off_network_failure_is_upstream_error(monkeypatch):
    request = httpx.Request("GET", "https://off.test")
    install_http_client(monkeypatch, error=httpx.ConnectError("offline", request=request))
    with pytest.raises(OFFUpstreamError):
        await openfoodfacts.fetch_product_by_barcode("unknown")


@pytest.mark.asyncio
async def test_off_invalid_nutrition_is_upstream_error(monkeypatch):
    install_http_client(
        monkeypatch,
        payload={
            "product": {
                "product_name": "Invalid",
                "nutriments": {"energy-kcal_100g": -1},
            }
        },
    )
    with pytest.raises(OFFUpstreamError):
        await openfoodfacts.fetch_product_by_barcode("invalid")


class FakeScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class LookupSession:
    def __init__(self, accepted=None):
        self.execute = AsyncMock(return_value=FakeScalarResult(accepted))
        self.add = AsyncMock()
        self.commit = AsyncMock()


def make_food_item(**overrides) -> FoodItem:
    now = datetime.now(timezone.utc)
    values = {
        "id": uuid.uuid4(),
        "barcode": "cached-code",
        "name": "Cached Food",
        "brand": "Local Brand",
        "serving_unit": "g",
        "calories_per_100": Decimal("101.00"),
        "protein_per_100": Decimal("2.00"),
        "carbs_per_100": Decimal("3.00"),
        "fat_per_100": Decimal("4.00"),
        "fiber_per_100": Decimal("5.00"),
        "nutrition_source": "manual",
        "accepted_at": now,
        "updated_at": now,
        "version": 1,
        "archived_at": None,
    }
    values.update(overrides)
    return FoodItem(**values)


@pytest.mark.asyncio
async def test_barcode_local_accepted_hit_avoids_openfoodfacts(monkeypatch):
    accepted = make_food_item()
    session = LookupSession(accepted)
    fetch = AsyncMock()
    monkeypatch.setattr(food, "fetch_product_by_barcode", fetch)

    result = await food.get_food_item_by_barcode("cached-code", None, session)

    assert result.kind == "accepted"
    assert result.product.id == accepted.id
    fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_barcode_remote_hit_is_ephemeral_candidate(monkeypatch):
    session = LookupSession()
    fetch = AsyncMock(
        return_value=OFFResult(
            name="Candidate",
            brand=None,
            per100=Per100Values(
                calories=200, protein_g=10, carbs_g=20, fat_g=5, fiber_g=0
            ),
            issues=["missing_fiber"],
        )
    )
    monkeypatch.setattr(food, "fetch_product_by_barcode", fetch)

    result = await food.get_food_item_by_barcode(
        "remote-code", UserProfile(id=uuid.uuid4()), session
    )

    assert result.kind == "candidate"
    assert result.candidate.barcode == "remote-code"
    assert result.candidate.issues == ["missing_fiber"]
    assert result.candidate.acceptance_proof
    session.add.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_barcode_authoritative_miss_returns_discriminated_not_found(monkeypatch):
    session = LookupSession()
    monkeypatch.setattr(food, "fetch_product_by_barcode", AsyncMock(return_value=None))

    result = await food.get_food_item_by_barcode("unknown-code", None, session)

    assert result.kind == "not_found"
    assert result.barcode == "unknown-code"


@pytest.mark.asyncio
async def test_barcode_upstream_failure_returns_502(monkeypatch):
    session = LookupSession()
    monkeypatch.setattr(
        food, "fetch_product_by_barcode", AsyncMock(side_effect=OFFUpstreamError())
    )

    with pytest.raises(HTTPException) as exc_info:
        await food.get_food_item_by_barcode("unknown-code", None, session)

    assert exc_info.value.status_code == 502
