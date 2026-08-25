import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UserProfile(Base):
    __tablename__ = "user_profile"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    height_cm: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    target_calories: Mapped[int] = mapped_column(nullable=False, default=2400)
    target_protein_g: Mapped[int] = mapped_column(nullable=False, default=140)
    target_carbs_g: Mapped[int] = mapped_column(nullable=False, default=280)
    target_fat_g: Mapped[int] = mapped_column(nullable=False, default=65)
    # IANA timezone used for midnight-to-midnight daily rollups (decision D14).
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Europe/Lisbon")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FoodItem(Base):
    """Master food library: cached Open Food Facts lookups and user-entered items.

    Single-user system: the library is global, not per-user (decision D11).
    All nutrient values are normalized to per-100g/ml at write time.
    """

    __tablename__ = "food_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    barcode: Mapped[str | None] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(255))
    serving_unit: Mapped[str] = mapped_column(String(32), nullable=False, default="g")
    calories_per_100: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    protein_per_100: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    carbs_per_100: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    fat_per_100: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    fiber_per_100: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MealLog(Base):
    """A persisted meal entry. calculated_* columns are computed by the app
    runtime (never by the LLM and never trusted from the client)."""

    __tablename__ = "meal_logs"
    __table_args__ = (
        Index("ix_meal_logs_user_logged_at", "user_id", "logged_at"),
        CheckConstraint("quantity_g > 0", name="ck_meal_logs_quantity_positive"),
        CheckConstraint(
            "calories_per_100 >= 0 AND protein_per_100 >= 0 "
            "AND carbs_per_100 >= 0 AND fat_per_100 >= 0 AND fiber_per_100 >= 0",
            name="ck_meal_logs_density_nonnegative",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_profile.id", ondelete="cascade"), nullable=False
    )
    food_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("food_items.id", ondelete="set null")
    )
    custom_name: Mapped[str | None] = mapped_column(String(255))
    logged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    quantity_g: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    # Immutable density snapshot: PATCH always recomputes from these values,
    # never from already-rounded calculated totals.
    calories_per_100: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    protein_per_100: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    carbs_per_100: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    fat_per_100: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    fiber_per_100: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    calculated_calories: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    calculated_protein: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    calculated_carbs: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    calculated_fat: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    calculated_fiber: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)


class MealLogMutation(Base):
    """Idempotency ledger retained after a meal is deleted.

    A nullable meal_log_id is a tombstone: replaying the consumed mutation key
    cannot recreate a deliberately deleted entry.
    """

    __tablename__ = "meal_log_mutations"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_profile.id", ondelete="cascade"), primary_key=True
    )
    client_mutation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    meal_log_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("meal_logs.id", ondelete="set null"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (Index("ix_chat_messages_user_session", "user_id", "session_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_profile.id", ondelete="cascade"), nullable=False
    )
    # Groups messages into conversations; supplied by the client (UUIDv4).
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, default=uuid.uuid4
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(nullable=False)
    tool_calls: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
