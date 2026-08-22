"""Pydantic contracts for LLM structured output.

INVARIANT (decision D13): the LLM only extracts raw reference values exactly
as printed on a label or estimated for a portion. It never scales, sums, or
performs any arithmetic — all math lives in app.services.nutrition and its
client-side mirror frontend/src/lib/nutrition.ts.
"""

from typing import Literal

from pydantic import BaseModel, Field


class Per100Values(BaseModel):
    """Nutrient density normalized to per 100 g/ml."""

    calories: float = Field(ge=0, description="kcal per 100 g/ml")
    protein_g: float = Field(ge=0)
    carbs_g: float = Field(ge=0)
    fat_g: float = Field(ge=0)
    fiber_g: float = Field(default=0, ge=0)


class NutritionLabelExtraction(BaseModel):
    """Vision LLM contract: raw values exactly as printed on the label.

    The model also reports the basis (per 100g vs per serving); normalization
    to per-100g happens deterministically in the backend (normalize_extraction).
    """

    product_name: str | None = Field(default=None, description="Product/brand name if visible")
    basis: Literal["per_100g", "per_serving"] = Field(description="Basis of the printed values")
    serving_size_g: float | None = Field(
        default=None, ge=0, description="Explicit serving size in g/ml, if indicated"
    )
    calories: float = Field(ge=0, description="Energy in kcal at the stated basis")
    protein_g: float = Field(ge=0)
    carbs_g: float = Field(ge=0)
    fat_g: float = Field(ge=0)
    fiber_g: float = Field(default=0, ge=0)
    confidence_score: float = Field(ge=0, le=1, description="Visual clarity and extraction confidence")


class FoodItemProposal(BaseModel):
    """One item inside a proposal card. Macro values are the LLM's estimate for
    the stated weight; per100 is included so the client can recompute totals
    deterministically when the user edits quantities."""

    name: str
    estimated_weight_g: float = Field(ge=0)
    calories: float = Field(ge=0)
    protein_g: float = Field(ge=0)
    carbs_g: float = Field(ge=0)
    fat_g: float = Field(ge=0)
    confidence: Literal["high", "medium", "low"]
    reasoning: str = Field(description="Brief portion assumptions (raw vs cooked, oil, etc.)")
    per100: Per100Values


class LogProposalResponse(BaseModel):
    """Assistant tool-call contract for freeform meal text.

    requires_user_confirmation is hard-coded True: proposals are ALWAYS shown
    as an editable card and only persisted after explicit user confirmation
    (decision D2 of the product brief: zero silent database mutations).
    """

    assistant_message: str = Field(description="Conversational, empathetic yet concise response")
    proposed_items: list[FoodItemProposal] = Field(default_factory=list)
    requires_user_confirmation: bool = True
