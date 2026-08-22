"""Open Food Facts barcode lookup, mapped to our per-100g schema."""

import httpx
from pydantic import BaseModel

from app.config import get_settings
from app.schemas.llm_contracts import Per100Values

USER_AGENT = "PlateOS/0.1 (self-hosted nutrition tracker)"


class OFFResult(BaseModel):
    name: str
    brand: str | None
    per100: Per100Values


def _num(nutriments: dict, key: str) -> float:
    v = nutriments.get(key)
    return float(v) if isinstance(v, (int, float)) else 0.0


async def fetch_product_by_barcode(barcode: str) -> OFFResult | None:
    s = get_settings()
    async with httpx.AsyncClient(timeout=10, headers={"User-Agent": USER_AGENT}) as client:
        resp = await client.get(f"{s.openfoodfacts_base_url}/product/{barcode}.json")
        if resp.status_code != 200:
            return None
        data = resp.json()

    product = data.get("product")
    if not product:
        return None

    nut = product.get("nutriments", {})
    kcal = _num(nut, "energy-kcal_100g")
    if kcal == 0.0:
        kj = _num(nut, "energy_100g")
        kcal = kj / 4.184 if kj else 0.0

    per100 = Per100Values(
        calories=round(kcal, 2),
        protein_g=_num(nut, "proteins_100g"),
        carbs_g=_num(nut, "carbohydrates_100g"),
        fat_g=_num(nut, "fat_100g"),
        fiber_g=_num(nut, "fiber_100g"),
    )
    if all(getattr(per100, f) == 0 for f in ("calories", "protein_g", "carbs_g", "fat_g")):
        return None

    brands: str | None = product.get("brands")
    return OFFResult(
        name=product.get("product_name") or f"Barcode {barcode}",
        brand=brands.split(",")[0].strip() if brands else None,
        per100=per100,
    )
