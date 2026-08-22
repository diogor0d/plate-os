"""API request/response DTOs."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.llm_contracts import Per100Values

SourceType = Literal["vision_label", "text_estimate", "manual", "barcode"]


class LoginRequest(BaseModel):
    password: str


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
    weight_kg: float | None = Field(default=None, gt=0)
    height_cm: float | None = Field(default=None, gt=0)
    target_calories: int | None = Field(default=None, ge=0)
    target_protein_g: int | None = Field(default=None, ge=0)
    target_carbs_g: int | None = Field(default=None, ge=0)
    target_fat_g: int | None = Field(default=None, ge=0)
    timezone: str | None = None


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
    barcode: str | None = None
    name: str
    brand: str | None = None
    serving_unit: str = "g"
    per100: Per100Values


class MealLogCreate(BaseModel):
    """Client sends quantity plus (for custom items) the per-100g density.

    Totals are ALWAYS computed server-side via scale_to_quantity; any totals
    a client might send are ignored by design.
    """

    logged_at: datetime | None = None
    food_item_id: uuid.UUID | None = None
    custom_name: str | None = None
    quantity_g: float = Field(gt=0, le=10000)
    per100: Per100Values | None = None  # required when food_item_id is null
    source_type: SourceType


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
    quantity_g: float | None = Field(default=None, gt=0, le=10000)
    logged_at: datetime | None = None


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
    image_base64: str = Field(description="Data URL or raw base64 of the client-downscaled label photo")


class VisionParseResponse(BaseModel):
    product_name: str | None
    per100: Per100Values
    confidence_score: float


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: uuid.UUID | None = None
