"""Pydantic contracts for LLM structured output.

INVARIANT (decision D13): the LLM only extracts raw reference values exactly
as printed on a label or estimated for a portion. It never scales, sums, or
performs any arithmetic — all math lives in app.services.nutrition and its
client-side mirror frontend/src/lib/nutrition.ts.
"""

from datetime import date, time
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
    reference_unit: Literal["g", "ml"] = Field(
        default="g",
        description="Whether the printed nutrition reference quantity is measured in grams or milliliters",
    )
    serving_size_g: float | None = Field(
        default=None, ge=0, le=10000, allow_inf_nan=False,
        description="Explicit serving size in g/ml, if indicated"
    )
    net_quantity: float | None = Field(
        default=None, gt=0, le=10000, allow_inf_nan=False,
        description="Explicit printed net quantity for one package/unit, without multiplying multipacks",
    )
    net_quantity_unit: Literal["g", "kg", "ml", "l"] | None = Field(
        default=None,
        description="Unit printed with net_quantity",
    )
    calories: float = Field(ge=0, le=10000, allow_inf_nan=False, description="Energy in kcal at the stated basis")
    protein_g: float = Field(ge=0, le=10000, allow_inf_nan=False)
    carbs_g: float = Field(ge=0, le=10000, allow_inf_nan=False)
    fat_g: float = Field(ge=0, le=10000, allow_inf_nan=False)
    fiber_g: float = Field(default=0, ge=0, le=10000, allow_inf_nan=False)
    confidence_score: float = Field(ge=0, le=1, allow_inf_nan=False, description="Visual clarity and extraction confidence")

    @model_validator(mode="after")
    def validate_normalized_density(self) -> "NutritionLabelExtraction":
        if self.serving_size_g is not None and 0 < self.serving_size_g < 0.005:
            raise ValueError("serving_size_g is too small for the supported quantity precision")
        if (self.net_quantity is None) != (self.net_quantity_unit is None):
            raise ValueError("net_quantity and net_quantity_unit must be provided together")
        if self.net_quantity is not None and self.net_quantity_unit is not None:
            expected_units = {"g", "kg"} if self.reference_unit == "g" else {"ml", "l"}
            if self.net_quantity_unit not in expected_units:
                raise ValueError("net quantity unit must match the nutrition reference unit")
            factor = 1000 if self.net_quantity_unit in {"kg", "l"} else 1
            if self.net_quantity * factor < 0.005:
                raise ValueError("normalized net quantity is too small for the supported quantity precision")
            if self.net_quantity * factor > 10000:
                raise ValueError("normalized net quantity exceeds 10000 g/ml")
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


class MealPlanScheduleDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    local_time: time
    timezone: str = Field(min_length=1, max_length=64)
    frequency: Literal["daily", "weekly"]
    interval: int = Field(default=1, ge=1, le=4)
    iso_weekdays: list[int] = Field(default_factory=list, max_length=7)
    start_date: date
    end_date: date | None = None
    reminder_minutes: int | None = Field(default=None, ge=0, le=1440)

    @field_validator("local_time", mode="before")
    @classmethod
    def validate_local_time(cls, value: object) -> object:
        if type(value) is time:
            return value
        if not isinstance(value, str) or len(value) not in {5, 8}:
            raise ValueError("must use HH:MM or HH:MM:SS")
        try:
            parsed = time.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("must be a valid local time") from exc
        if parsed.microsecond or parsed.isoformat(timespec="seconds")[: len(value)] != value:
            raise ValueError("must use HH:MM or HH:MM:SS")
        return parsed

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def validate_strict_date(cls, value: object) -> object:
        if value is None or type(value) is date:
            return value
        if not isinstance(value, str) or len(value) != 10:
            raise ValueError("must use YYYY-MM-DD")
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("must be a valid date") from exc
        if parsed.isoformat() != value:
            raise ValueError("must use YYYY-MM-DD")
        return parsed

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("must be a valid IANA timezone") from exc
        return value

    @model_validator(mode="after")
    def validate_recurrence(self) -> "MealPlanScheduleDraft":
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date must not precede start_date")
        if len(set(self.iso_weekdays)) != len(self.iso_weekdays):
            raise ValueError("iso_weekdays must be unique")
        if any(day < 1 or day > 7 for day in self.iso_weekdays):
            raise ValueError("iso_weekdays must be between 1 and 7")
        if self.frequency == "daily" and self.iso_weekdays:
            raise ValueError("daily schedules cannot specify weekdays")
        if self.frequency == "weekly" and not self.iso_weekdays:
            raise ValueError("weekly schedules require weekdays")
        return self


class MealPlanDraftBlock(BaseModel):
    """Review-only rough routine draft; persistence remains a user action."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Literal["meal_plan_draft"]
    title: str = Field(min_length=1, max_length=100)
    rough_text: str = Field(min_length=1, max_length=2000)
    schedule: MealPlanScheduleDraft | None = None
    requires_user_confirmation: Literal[True]


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
    MealProposalBlock
    | GoalDraftBlock
    | MealPlanDraftBlock
    | AnalyticsNavigationBlock
    | EvidenceInsightBlock,
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
        if any(types.count(block_type) > 1 for block_type in (
            "meal_proposal", "goal_draft", "meal_plan_draft"
        )):
            raise ValueError("at most one draft of each mutation type is allowed")
        return self


class LogProposalResponse(BaseModel):
    """Legacy meal-only response retained for compatibility tests/imports."""

    assistant_message: str = Field(description="Conversational, empathetic yet concise response")
    proposed_items: list[FoodItemProposal] = Field(default_factory=list)
    requires_user_confirmation: Literal[True] = True
