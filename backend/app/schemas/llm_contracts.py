"""Pydantic contracts for LLM structured output.

INVARIANT (decision D13): the LLM only extracts raw reference values exactly
as printed on a label or estimated for a portion. It never scales, sums, or
performs any arithmetic — all math lives in app.services.nutrition and its
client-side mirror frontend/src/lib/nutrition.ts.
"""

from datetime import date
from typing import Annotated, Literal

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
    """One proposal item: reference density plus estimated quantity only."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)

    name: str = Field(min_length=1, max_length=255)
    basis: Literal["per_100g"] = "per_100g"
    estimated_weight_g: float = Field(ge=0.01, le=10000, allow_inf_nan=False)
    confidence: Literal["high", "medium", "low"]
    reasoning: str = Field(min_length=1, max_length=500, description="Brief portion assumptions")
    per100: Per100Values

    @field_validator("estimated_weight_g")
    @classmethod
    def canonicalize_weight(cls, value: float) -> float:
        return float(
            Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )


class GoalTargets(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_calories: int = Field(ge=800, le=6000)
    target_protein_g: int = Field(ge=20, le=400)
    target_carbs_g: int = Field(ge=0, le=800)
    target_fat_g: int = Field(ge=20, le=300)


class MealProposalBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Literal["meal_proposal"]
    title: str = Field(min_length=1, max_length=100)
    items: list[FoodItemProposal] = Field(min_length=1, max_length=8)
    requires_user_confirmation: Literal[True] = True


class GoalDraftBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Literal["goal_draft"]
    proposed_targets: GoalTargets
    rationale: str = Field(min_length=1, max_length=800)
    caveats: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(
        default_factory=list, max_length=5
    )
    requires_user_confirmation: Literal[True] = True


AnalyticsMetric = Literal["calories", "protein_g", "carbs_g", "fat_g", "fiber_g"]
AnalyticsSource = Literal["vision_label", "text_estimate", "manual", "barcode"]


class AnalyticsQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    days: int | None = Field(default=None, ge=1, le=366)
    start: date | None = None
    end: date | None = None
    metric: AnalyticsMetric = "calories"
    source_types: list[AnalyticsSource] = Field(default_factory=list, max_length=4)
    food_query: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_range(self) -> "AnalyticsQuery":
        custom = self.start is not None or self.end is not None
        if self.days is not None and custom:
            raise ValueError("use days or custom dates, not both")
        if (self.start is None) != (self.end is None):
            raise ValueError("start and end must be supplied together")
        if self.days is None and not custom:
            raise ValueError("an analytics range is required")
        if self.start is not None and self.end is not None:
            if self.end < self.start:
                raise ValueError("end must not precede start")
            if (self.end - self.start).days + 1 > 366:
                raise ValueError("range must not exceed 366 days")
        if len(set(self.source_types)) != len(self.source_types):
            raise ValueError("source_types must be unique")
        return self


class AnalyticsNavigationBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Literal["analytics_navigation"]
    label: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=240)
    query: AnalyticsQuery


class EvidenceInsightBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Literal["evidence_insight"]
    title: str = Field(min_length=1, max_length=100)
    interpretation: str = Field(min_length=1, max_length=600)
    tone: Literal["neutral", "positive", "warning"] = "neutral"


AssistantBlock = Annotated[
    MealProposalBlock | GoalDraftBlock | AnalyticsNavigationBlock | EvidenceInsightBlock,
    Field(discriminator="type"),
]


class AssistantHarnessResponse(BaseModel):
    """Versioned, allowlisted UI output from the assistant harness."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal["1"] = "1"
    assistant_message: str = Field(min_length=1, max_length=1200)
    blocks: list[AssistantBlock] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def limit_mutation_drafts(self) -> "AssistantHarnessResponse":
        types = [block.type for block in self.blocks]
        if types.count("meal_proposal") > 1 or types.count("goal_draft") > 1:
            raise ValueError("at most one meal proposal and one goal draft are allowed")
        return self


class LogProposalResponse(BaseModel):
    """Legacy meal-only response retained for compatibility tests/imports."""

    assistant_message: str = Field(description="Conversational, empathetic yet concise response")
    proposed_items: list[FoodItemProposal] = Field(default_factory=list)
    requires_user_confirmation: Literal[True] = True
