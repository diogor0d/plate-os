"""Deterministic nutrition arithmetic.

This module is the ONLY place where macro scaling happens on the server.
It is mirrored byte-for-byte in spirit by frontend/src/lib/nutrition.ts so
proposal-card quantity edits recompute instantly client-side (decision D13:
the LLM extracts, the app computes).
"""

from app.schemas.llm_contracts import FoodItemProposal, NutritionLabelExtraction, Per100Values

MACRO_FIELDS = ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g")


def round1(value: float) -> float:
    return round(value, 1)


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


def scale_to_quantity(per100: Per100Values, quantity_g: float) -> dict[str, float]:
    return {f: round1(getattr(per100, f) * quantity_g / 100.0) for f in MACRO_FIELDS}


def sum_totals(items: list[dict[str, float]]) -> dict[str, float]:
    return {f: round1(sum(i[f] for i in items)) for f in MACRO_FIELDS}


def proposal_totals(items: list[FoodItemProposal]) -> dict[str, float]:
    """Totals across a proposal card, for display in the confirm button."""
    return sum_totals([{f: getattr(i, f) for f in MACRO_FIELDS} for i in items])
