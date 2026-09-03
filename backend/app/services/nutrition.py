"""Deterministic nutrition arithmetic.

This module is the ONLY place where macro scaling happens on the server.
It is mirrored byte-for-byte in spirit by frontend/src/lib/nutrition.ts so
proposal-card quantity edits recompute instantly client-side (decision D13:
the LLM extracts, the app computes).
"""

from collections.abc import Mapping
from decimal import Decimal, ROUND_HALF_UP

from app.schemas.llm_contracts import FoodItemProposal, NutritionLabelExtraction, Per100Values

MACRO_FIELDS = ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g")
ONE_DECIMAL = Decimal("0.1")
DENSITY_DECIMALS = Decimal("0.0001")
QUANTITY_DECIMALS = Decimal("0.01")


def _decimal(value: float | Decimal) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def round1(value: float | Decimal) -> float:
    return float(_decimal(value).quantize(ONE_DECIMAL, rounding=ROUND_HALF_UP))


def canonical_quantity(value: float | Decimal) -> Decimal:
    return _decimal(value).quantize(QUANTITY_DECIMALS, rounding=ROUND_HALF_UP)


def canonical_density_values(per100: Per100Values) -> dict[str, Decimal]:
    return {
        field: _decimal(getattr(per100, field)).quantize(
            DENSITY_DECIMALS, rounding=ROUND_HALF_UP
        )
        for field in MACRO_FIELDS
    }


def scale_density_values(
    densities: Mapping[str, float | Decimal], quantity_g: float | Decimal
) -> dict[str, float]:
    quantity = canonical_quantity(quantity_g)
    return {
        field: round1(_decimal(densities[field]) * quantity / Decimal(100))
        for field in MACRO_FIELDS
    }


def normalize_extraction(e: NutritionLabelExtraction) -> Per100Values:
    """Normalize a raw label extraction (per 100g OR per serving) to per-100g."""
    if e.basis == "per_100g":
        vals = {f: getattr(e, f) for f in MACRO_FIELDS}
    else:
        serving = e.serving_size_g or 0.0
        if serving <= 0:
            raise ValueError("basis is per_serving but serving_size_g is missing or zero")
        vals = {f: getattr(e, f) / serving * 100.0 for f in MACRO_FIELDS}
    return Per100Values(**{k: round1(v) for k, v in vals.items()})


def suggested_quantity_g(e: NutritionLabelExtraction) -> float | None:
    """Return a package quantity in the app's shared g/ml quantity scale."""
    if e.net_quantity is not None and e.net_quantity_unit is not None:
        factor = Decimal(1000) if e.net_quantity_unit in {"kg", "l"} else Decimal(1)
        return float(canonical_quantity(_decimal(e.net_quantity) * factor))
    if e.serving_size_g is not None and e.serving_size_g > 0:
        return float(canonical_quantity(e.serving_size_g))
    return None


def scale_to_quantity(
    per100: Per100Values, quantity_g: float | Decimal
) -> dict[str, float]:
    return scale_density_values(canonical_density_values(per100), quantity_g)


def sum_totals(items: list[dict[str, float]]) -> dict[str, float]:
    return {f: round1(sum((_decimal(i[f]) for i in items), Decimal(0))) for f in MACRO_FIELDS}


def proposal_totals(items: list[FoodItemProposal]) -> dict[str, float]:
    """Totals across a proposal card, for display in the confirm button."""
    return sum_totals([scale_to_quantity(i.per100, i.estimated_weight_g) for i in items])
