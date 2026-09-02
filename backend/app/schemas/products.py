"""Reviewed product-library and external candidate contracts (D41)."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.llm_contracts import Per100Values

ProductSource = Literal["manual", "open_food_facts", "vision_label"]


class ProductOut(BaseModel):
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
    nutrition_source: ProductSource
    accepted_at: datetime
    updated_at: datetime
    version: int
    archived_at: datetime | None


class ProductCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source: Literal["open_food_facts", "vision_label"]
    barcode: str | None = Field(default=None, min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    brand: str | None = Field(default=None, max_length=255)
    serving_unit: str = Field(default="g", min_length=1, max_length=32)
    per100: Per100Values
    retrieved_at: datetime
    confidence_score: float | None = Field(default=None, ge=0, le=1)
    issues: list[Literal[
        "missing_name", "missing_calories", "missing_protein", "missing_carbs",
        "missing_fat", "missing_fiber",
    ]] = Field(default_factory=list, max_length=6)
    acceptance_proof: str = Field(min_length=1)


class AcceptedResolution(BaseModel):
    kind: Literal["accepted"]
    product: ProductOut


class CandidateResolution(BaseModel):
    kind: Literal["candidate"]
    candidate: ProductCandidate


class NotFoundResolution(BaseModel):
    kind: Literal["not_found"]
    barcode: str


BarcodeResolution = Annotated[
    AcceptedResolution | CandidateResolution | NotFoundResolution,
    Field(discriminator="kind"),
]


class ProductCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    client_mutation_id: uuid.UUID
    barcode: str | None = Field(default=None, min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    brand: str | None = Field(default=None, max_length=255)
    serving_unit: str = Field(default="g", min_length=1, max_length=32)
    per100: Per100Values
    nutrition_source: ProductSource
    acceptance_proof: str | None = None


class ProductUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    client_mutation_id: uuid.UUID
    expected_version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=255)
    brand: str | None = Field(default=None, max_length=255)
    serving_unit: str = Field(default="g", min_length=1, max_length=32)
    per100: Per100Values


class ProductArchive(BaseModel):
    client_mutation_id: uuid.UUID
    expected_version: int = Field(ge=1)
