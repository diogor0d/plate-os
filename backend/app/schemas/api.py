"""API request/response DTOs."""

import uuid
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)

from app.schemas.llm_contracts import Per100Values

SourceType = Literal["vision_label", "text_estimate", "manual", "barcode"]


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


class UserProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    weight_kg: float
    height_cm: float
    target_calories: int
    target_protein_g: int
    target_carbs_g: int
    target_fat_g: int
    timezone: str


class UserProfileUpdate(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    weight_kg: float | None = Field(default=None, gt=0, lt=1000)
    height_cm: float | None = Field(default=None, gt=0, lt=1000)
    target_calories: int | None = Field(default=None, ge=0, le=100000)
    target_protein_g: int | None = Field(default=None, ge=0, le=10000)
    target_carbs_g: int | None = Field(default=None, ge=0, le=10000)
    target_fat_g: int | None = Field(default=None, ge=0, le=10000)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("must be a valid IANA timezone") from exc
        return value


class FoodItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    barcode: str | None
    name: str
    brand: str | None
    serving_unit: str
    calories_per_100: float
    protein_per_100: float
    carbs_per_100: float
    fat_per_100: float
    fiber_per_100: float
    is_verified: bool


class FoodItemCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    barcode: str | None = Field(default=None, min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    brand: str | None = Field(default=None, max_length=255)
    serving_unit: str = Field(default="g", min_length=1, max_length=32)
    per100: Per100Values


class MealLogCreate(BaseModel):
    """Client sends quantity plus (for custom items) the per-100g density.

    Totals are ALWAYS computed server-side via scale_to_quantity; any totals
    a client might send are ignored by design.
    """

    model_config = ConfigDict(str_strip_whitespace=True, allow_inf_nan=False)

    logged_at: AwareDatetime | None = None
    client_mutation_id: uuid.UUID | None = None
    food_item_id: uuid.UUID | None = None
    custom_name: str | None = Field(default=None, max_length=255)
    quantity_g: float = Field(ge=0.01, le=10000)
    per100: Per100Values | None = None  # required when food_item_id is null
    source_type: SourceType

    @field_validator("quantity_g")
    @classmethod
    def validate_quantity_precision(cls, value: float) -> float:
        decimal = Decimal(str(value))
        if decimal != decimal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP):
            raise ValueError("must have at most 2 decimal places")
        return value

    @model_validator(mode="after")
    def validate_food_reference(self) -> "MealLogCreate":
        if self.food_item_id is None:
            if self.per100 is None:
                raise ValueError("per100 is required for a custom item")
            if not self.custom_name:
                raise ValueError("custom_name is required for a custom item")
        elif self.per100 is not None:
            raise ValueError("per100 must be omitted when food_item_id is provided")
        return self


class MealLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    logged_at: datetime
    food_item_id: uuid.UUID | None
    custom_name: str | None
    quantity_g: float
    calculated_calories: float
    calculated_protein: float
    calculated_carbs: float
    calculated_fat: float
    calculated_fiber: float
    source_type: str


class MealLogPatch(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    quantity_g: float | None = Field(default=None, ge=0.01, le=10000)
    logged_at: AwareDatetime | None = None

    @field_validator("quantity_g")
    @classmethod
    def validate_quantity_precision(cls, value: float | None) -> float | None:
        if value is None:
            return None
        decimal = Decimal(str(value))
        if decimal != decimal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP):
            raise ValueError("must have at most 2 decimal places")
        return value


class DailySummary(BaseModel):
    date: str
    timezone: str
    targets: dict[str, int]
    consumed: dict[str, float]
    remaining: dict[str, float]


class DayTotals(BaseModel):
    date: str
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float


class AnalyticsResponse(BaseModel):
    timezone: str
    days: int
    targets: dict[str, int]
    history: list[DayTotals]
    rolling_avg_calories_7d: float


class VisionParseRequest(BaseModel):
    image_base64: str = Field(
        min_length=1,
        max_length=1_900_000,
        description="Data URL or raw base64 of the client-downscaled label photo",
    )


class VisionParseResponse(BaseModel):
    product_name: str | None
    per100: Per100Values
    confidence_score: float


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: uuid.UUID | None = None


# --- Settings screen (decisions D34/D35) ---------------------------------


class ProviderConfigOut(BaseModel):
    base_url: str | None
    model: str | None
    has_api_key: bool


class RuntimeSettingsOut(BaseModel):
    text: ProviderConfigOut
    vision: ProviderConfigOut
    vision_inherits_text: bool
    openfoodfacts_base_url: str | None
    updated_at: datetime | None


class ProviderConfigIn(BaseModel):
    """api_key tri-state: omitted -> keep stored key; "" -> clear; value ->
    replace. base_url/model: null clears the override (falls back)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    base_url: HttpUrl | None = None
    model: str | None = Field(default=None, min_length=1, max_length=200)
    api_key: str | None = Field(default=None, max_length=4096)


class VisionProviderConfigIn(ProviderConfigIn):
    inherit_text: bool = True


class RuntimeSettingsIn(BaseModel):
    text: ProviderConfigIn
    vision: VisionProviderConfigIn
    openfoodfacts_base_url: HttpUrl | None = None


class SettingsTestRequest(BaseModel):
    task: Literal["text", "vision"]


class SettingsTestResponse(BaseModel):
    ok: bool
    detail: str
