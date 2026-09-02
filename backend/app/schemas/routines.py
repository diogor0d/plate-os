"""Meal routine, recurrence, agenda, and occurrence contracts (D41)."""

import uuid
from datetime import date, datetime, time
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.products import ProductOut


class RoutineItemIn(BaseModel):
    food_item_id: uuid.UUID
    quantity_g: float = Field(ge=0.01, le=10000)

    @field_validator("quantity_g")
    @classmethod
    def quantity_precision(cls, value: float) -> float:
        raw = Decimal(str(value))
        if raw != raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP):
            raise ValueError("must have at most 2 decimal places")
        return value


class RoutineWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    client_mutation_id: uuid.UUID
    title: str = Field(min_length=1, max_length=100)
    mode: Literal["rough", "defined"]
    rough_text: str | None = Field(default=None, max_length=2000)
    items: list[RoutineItemIn] = Field(default_factory=list, max_length=8)
    expected_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_mode(self) -> "RoutineWrite":
        if self.mode == "rough":
            if not self.rough_text or self.items:
                raise ValueError("rough routines require rough_text and no items")
        elif self.rough_text is not None or not self.items:
            raise ValueError("defined routines require items and no rough_text")
        ids = [item.food_item_id for item in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError("routine products must be unique")
        return self


class RoutineItemOut(BaseModel):
    position: int
    quantity_g: float
    product: ProductOut


class RoutineOut(BaseModel):
    id: uuid.UUID
    title: str
    mode: Literal["rough", "defined"]
    rough_text: str | None
    version: int
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
    items: list[RoutineItemOut]


class RoutineArchive(BaseModel):
    client_mutation_id: uuid.UUID
    expected_version: int = Field(ge=1)


class ScheduleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_mutation_id: uuid.UUID
    local_time: time
    timezone: str = Field(min_length=1, max_length=64)
    frequency: Literal["daily", "weekly"]
    interval: int = Field(default=1, ge=1, le=4)
    iso_weekdays: list[int] = Field(default_factory=list, max_length=7)
    start_date: date
    end_date: date | None = None
    reminder_minutes: int | None = Field(default=None, ge=0, le=1440)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("must be a valid IANA timezone") from exc
        return value

    @model_validator(mode="after")
    def validate_recurrence(self) -> "ScheduleCreate":
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


class ScheduleOut(BaseModel):
    id: uuid.UUID
    routine_id: uuid.UUID
    local_time: time
    timezone: str
    frequency: Literal["daily", "weekly"]
    interval: int
    iso_weekdays: list[int]
    start_date: date
    end_date: date | None
    reminder_minutes: int | None
    enabled: bool
    version: int


class ScheduleStateChange(BaseModel):
    client_mutation_id: uuid.UUID
    expected_version: int = Field(ge=1)
    enabled: bool


class OccurrenceOut(BaseModel):
    id: uuid.UUID
    routine: RoutineOut
    schedule_id: uuid.UUID
    scheduled_at: datetime
    scheduled_local_date: date
    schedule_timezone: str
    time_resolution: str
    status: Literal["scheduled", "completed", "skipped"]
    state: Literal["upcoming", "due", "missed", "completed", "skipped"]


class AgendaOut(BaseModel):
    server_now: datetime
    display_timezone: str
    occurrences: list[OccurrenceOut]
    next_due_at: datetime | None
    countdown_seconds: int | None


class OccurrenceComplete(BaseModel):
    client_mutation_id: uuid.UUID
    confirmed_at: AwareDatetime
    meal_log_client_mutation_ids: list[uuid.UUID] = Field(min_length=1, max_length=8)

    @field_validator("meal_log_client_mutation_ids")
    @classmethod
    def unique_ids(cls, values: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(set(values)) != len(values):
            raise ValueError("meal mutation IDs must be unique")
        return values


class OccurrenceSkip(BaseModel):
    client_mutation_id: uuid.UUID
    acted_at: AwareDatetime
