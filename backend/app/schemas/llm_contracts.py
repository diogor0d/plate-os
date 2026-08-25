"""Pydantic contracts for LLM structured output.

INVARIANT (decision D13): the LLM only extracts raw reference values exactly
as printed on a label or estimated for a portion. It never scales, sums, or
performs any arithmetic — all math lives in app.services.nutrition and its
client-side mirror frontend/src/lib/nutrition.ts.
"""

from typing import Literal

from decimal import Decimal, ROUND_HALF_UP

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Per100Values(BaseModel):
    """Nutrient density normalized to per 100 g/ml."""

    model_config = ConfigDict(allow_inf_nan=False)

    calories: float = Field(ge=0, le=1000, description="kcal per 100 g/ml")
    protein_g: float = Field(ge=0, le=100)
    carbs_g: float = Field(ge=0, le=100)
    fat_g: float = Field(ge=0, le=100)
    fiber_g: float = Field(default=0, ge=0, le=100)

    @field_validator("calories", "protein_g", "carbs_g", "fat_g", "fiber_g")
    @classmethod
    def canonicalize_density(cls, value: float) -> float:
        canonical = Decimal(str(value)).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )
        return 0.0 if canonical == 0 else float(canonical)


class NutritionLabelExtraction(BaseModel):
    """Vision LLM contract: raw values exactly as printed on the label.

    The model also reports the basis (per 100g vs per serving); normalization
    to per-100g happens deterministically in the backend (normalize_extraction).
    """

    model_config = ConfigDict(str_strip_whitespace=True, allow_inf_nan=False)

    product_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Product/brand name if visible",
    )
    basis: Literal["per_100g", "per_serving"] = Field(description="Basis of the printed values")
    serving_size_g: float | None = Field(
        default=None, ge=0, le=10000, allow_inf_nan=False,
        description="Explicit serving size in g/ml, if indicated"
    )
    calories: float = Field(ge=0, le=10000, allow_inf_nan=False, description="Energy in kcal at the stated basis")
    protein_g: float = Field(ge=0, le=10000, allow_inf_nan=False)
    carbs_g: float = Field(ge=0, le=10000, allow_inf_nan=False)
    fat_g: float = Field(ge=0, le=10000, allow_inf_nan=False)
    fiber_g: float = Field(default=0, ge=0, le=10000, allow_inf_nan=False)
    confidence_score: float = Field(ge=0, le=1, allow_inf_nan=False, description="Visual clarity and extraction confidence")

    @model_validator(mode="after")
    def validate_normalized_density(self) -> "NutritionLabelExtraction":
        if self.basis == "per_serving":
            if self.serving_size_g is None or self.serving_size_g <= 0:
                raise ValueError(
                    "serving_size_g must be positive when basis is per_serving"
                )
            factor = 100 / self.serving_size_g
        else:
            factor = 1

        limits = {
            "calories": 1000,
            "protein_g": 100,
            "carbs_g": 100,
            "fat_g": 100,
            "fiber_g": 100,
        }
        if any(getattr(self, field) * factor > limit for field, limit in limits.items()):
            raise ValueError("normalized per-100 values exceed physical limits")
        return self


class FoodItemProposal(BaseModel):
    """One item inside a proposal card. Macro values are the LLM's estimate for
    the stated weight; per100 is included so the client can recompute totals
    deterministically when the user edits quantities."""

    model_config = ConfigDict(str_strip_whitespace=True, allow_inf_nan=False)

    name: str = Field(min_length=1, max_length=255)
    estimated_weight_g: float = Field(ge=0.01, le=10000, allow_inf_nan=False)
    calories: float = Field(ge=0)
    protein_g: float = Field(ge=0)
    carbs_g: float = Field(ge=0)
    fat_g: float = Field(ge=0)
    confidence: Literal["high", "medium", "low"]
    reasoning: str = Field(description="Brief portion assumptions (raw vs cooked, oil, etc.)")
    per100: Per100Values

    @field_validator("estimated_weight_g")
    @classmethod
    def canonicalize_weight(cls, value: float) -> float:
        return float(
            Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )


class LogProposalResponse(BaseModel):
    """Assistant tool-call contract for freeform meal text.

    requires_user_confirmation is hard-coded True: proposals are ALWAYS shown
    as an editable card and only persisted after explicit user confirmation
    (decision D2 of the product brief: zero silent database mutations).
    """

    assistant_message: str = Field(description="Conversational, empathetic yet concise response")
    proposed_items: list[FoodItemProposal] = Field(default_factory=list)
    requires_user_confirmation: bool = True
