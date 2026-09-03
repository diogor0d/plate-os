"""Open Food Facts barcode lookup mapped to an ephemeral product candidate."""

from typing import Any, Literal

import httpx
from pydantic import BaseModel, ValidationError

from app.schemas.llm_contracts import Per100Values
from app.services.runtime_settings import resolve_openfoodfacts_base_url

USER_AGENT = "PlateOS/0.1 (self-hosted nutrition tracker)"
PRODUCT_FIELDS = "product_name,brands,nutriments"

MissingIssue = Literal[
    "missing_name",
    "missing_calories",
    "missing_protein",
    "missing_carbs",
    "missing_fat",
    "missing_fiber",
]


class OFFUpstreamError(Exception):
    """OFF could not provide an authoritative product response."""


class OFFResult(BaseModel):
    name: str
    brand: str | None
    per100: Per100Values
    issues: list[MissingIssue]


def _number(nutriments: dict[str, Any], key: str) -> float | None:
    value = nutriments.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


async def fetch_product_by_barcode(barcode: str) -> OFFResult | None:
    """Return a candidate, ``None`` for an authoritative miss, or raise on failure."""
    base_url = resolve_openfoodfacts_base_url()
    try:
        async with httpx.AsyncClient(
            timeout=10, headers={"User-Agent": USER_AGENT}
        ) as client:
            response = await client.get(
                f"{base_url.rstrip('/')}/product/{barcode}.json",
                params={"fields": PRODUCT_FIELDS},
            )
    except httpx.HTTPError as exc:
        raise OFFUpstreamError("Open Food Facts request failed") from exc

    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise OFFUpstreamError(
            f"Open Food Facts returned HTTP {response.status_code}"
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise OFFUpstreamError("Open Food Facts returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise OFFUpstreamError("Open Food Facts returned an invalid response")

    product = data.get("product")
    if product is None and data.get("status") == 0:
        return None
    if not isinstance(product, dict):
        raise OFFUpstreamError("Open Food Facts response omitted product data")

    nutriments = product.get("nutriments")
    if not isinstance(nutriments, dict):
        nutriments = {}

    kcal = _number(nutriments, "energy-kcal_100g")
    if kcal is None:
        kilojoules = _number(nutriments, "energy_100g")
        kcal = kilojoules / 4.184 if kilojoules is not None else None

    values = {
        "calories": kcal,
        "protein_g": _number(nutriments, "proteins_100g"),
        "carbs_g": _number(nutriments, "carbohydrates_100g"),
        "fat_g": _number(nutriments, "fat_100g"),
        "fiber_g": _number(nutriments, "fiber_100g"),
    }
    issue_names: dict[str, MissingIssue] = {
        "calories": "missing_calories",
        "protein_g": "missing_protein",
        "carbs_g": "missing_carbs",
        "fat_g": "missing_fat",
        "fiber_g": "missing_fiber",
    }
    issues = [issue_names[field] for field, value in values.items() if value is None]

    raw_name = product.get("product_name")
    name = raw_name.strip() if isinstance(raw_name, str) else ""
    if not name:
        name = f"Barcode {barcode}"
        issues.insert(0, "missing_name")

    raw_brands = product.get("brands")
    brand = raw_brands.split(",")[0].strip() if isinstance(raw_brands, str) else None
    try:
        return OFFResult(
            name=name[:255],
            brand=brand[:255] if brand else None,
            per100=Per100Values(**{
                field: round(value, 2) if value is not None else 0.0
                for field, value in values.items()
            }),
            issues=issues,
        )
    except ValidationError as exc:
        raise OFFUpstreamError("Open Food Facts returned invalid nutrition data") from exc
