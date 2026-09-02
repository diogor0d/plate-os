import uuid
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UserProfile(Base):
    __tablename__ = "user_profile"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Local account credentials (decision D36). Nullable for the 0002-era row;
    # startup bootstrap fills them from env secrets before first login.
    username: Mapped[str | None] = mapped_column(String(32), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(256))
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
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
    """Household-global products explicitly accepted by a user (D41)."""

    __tablename__ = "food_items"
    __table_args__ = (
        CheckConstraint(
            "calories_per_100 >= 0 AND protein_per_100 >= 0 "
            "AND carbs_per_100 >= 0 AND fat_per_100 >= 0 AND fiber_per_100 >= 0",
            name="ck_food_items_density_nonnegative",
        ),
        CheckConstraint("version >= 1", name="ck_food_items_version_positive"),
    )

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
    nutrition_source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    accepted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user_profile.id", ondelete="set null")
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class FoodItemMutation(Base):
    __tablename__ = "food_item_mutations"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_profile.id", ondelete="cascade"), primary_key=True
    )
    client_mutation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    food_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("food_items.id", ondelete="set null")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MealLog(Base):
    """A persisted meal entry. calculated_* columns are computed by the app
    runtime (never by the LLM and never trusted from the client)."""

    __tablename__ = "meal_logs"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_meal_logs_id_user"),
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


class MealRoutine(Base):
    __tablename__ = "meal_routines"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_routines_id_user"),
        CheckConstraint("mode IN ('rough', 'defined')", name="ck_meal_routines_mode"),
        CheckConstraint("version >= 1", name="ck_meal_routines_version_positive"),
        Index("ix_meal_routines_user_active", "user_id", "archived_at", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_profile.id", ondelete="cascade"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    rough_text: Mapped[str | None] = mapped_column(String(2000))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MealRoutineItem(Base):
    __tablename__ = "meal_routine_items"
    __table_args__ = (
        CheckConstraint("position >= 0 AND position <= 7", name="ck_routine_items_position"),
        CheckConstraint("quantity_g > 0", name="ck_routine_items_quantity"),
        UniqueConstraint("routine_id", "food_item_id", name="uq_routine_items_product"),
    )

    routine_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("meal_routines.id", ondelete="cascade"), primary_key=True
    )
    position: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    food_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("food_items.id", ondelete="restrict"), nullable=False
    )
    quantity_g: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)


class MealSchedule(Base):
    __tablename__ = "meal_schedules"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_schedules_id_user"),
        ForeignKeyConstraint(
            ["routine_id", "user_id"],
            ["meal_routines.id", "meal_routines.user_id"],
            name="fk_schedules_routine_user",
            ondelete="cascade",
        ),
        CheckConstraint("frequency IN ('daily', 'weekly')", name="ck_meal_schedules_frequency"),
        CheckConstraint("interval >= 1 AND interval <= 4", name="ck_meal_schedules_interval"),
        CheckConstraint("version >= 1", name="ck_meal_schedules_version_positive"),
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="ck_meal_schedules_dates"),
        CheckConstraint(
            "reminder_minutes IS NULL OR (reminder_minutes >= 0 AND reminder_minutes <= 1440)",
            name="ck_meal_schedules_reminder",
        ),
        Index("ix_meal_schedules_user_enabled", "user_id", "enabled"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_profile.id", ondelete="cascade"), nullable=False
    )
    routine_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    local_time: Mapped[time] = mapped_column(Time(timezone=False), nullable=False)
    frequency: Mapped[str] = mapped_column(String(16), nullable=False)
    interval: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    reminder_minutes: Mapped[int | None] = mapped_column(SmallInteger)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MealScheduleWeekday(Base):
    __tablename__ = "meal_schedule_weekdays"
    __table_args__ = (
        CheckConstraint("iso_weekday >= 1 AND iso_weekday <= 7", name="ck_schedule_weekdays_iso"),
    )

    schedule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("meal_schedules.id", ondelete="cascade"), primary_key=True
    )
    iso_weekday: Mapped[int] = mapped_column(SmallInteger, primary_key=True)


class MealOccurrence(Base):
    __tablename__ = "meal_occurrences"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_occurrences_id_user"),
        UniqueConstraint("schedule_id", "scheduled_local_date", name="uq_occurrence_schedule_day"),
        ForeignKeyConstraint(
            ["schedule_id", "user_id"],
            ["meal_schedules.id", "meal_schedules.user_id"],
            name="fk_occurrences_schedule_user",
            ondelete="cascade",
        ),
        CheckConstraint(
            "status IN ('scheduled', 'completed', 'skipped')", name="ck_occurrences_status"
        ),
        Index("ix_occurrences_schedule_at", "schedule_id", "scheduled_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_profile.id", ondelete="cascade"), nullable=False
    )
    schedule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    scheduled_local_date: Mapped[date] = mapped_column(Date, nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    time_resolution: Mapped[str] = mapped_column(String(32), nullable=False, default="exact")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="scheduled")
    acted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MealOccurrenceLog(Base):
    __tablename__ = "meal_occurrence_logs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["occurrence_id", "user_id"],
            ["meal_occurrences.id", "meal_occurrences.user_id"],
            name="fk_occurrence_logs_occurrence_user",
            ondelete="cascade",
        ),
        ForeignKeyConstraint(
            ["meal_log_id", "user_id"],
            ["meal_logs.id", "meal_logs.user_id"],
            name="fk_occurrence_logs_meal_user",
            ondelete="restrict",
        ),
        UniqueConstraint("meal_log_id", name="uq_occurrence_logs_meal"),
        UniqueConstraint("occurrence_id", "position", name="uq_occurrence_logs_position"),
    )

    occurrence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    meal_log_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_profile.id", ondelete="cascade"), nullable=False
    )
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)


class PlanningMutation(Base):
    __tablename__ = "planning_mutations"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_profile.id", ondelete="cascade"), primary_key=True
    )
    client_mutation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    __table_args__ = (
        UniqueConstraint("endpoint_fingerprint", name="uq_push_endpoint_fingerprint"),
        Index("ix_push_subscriptions_user_active", "user_id", "disabled_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_profile.id", ondelete="cascade"), nullable=False
    )
    endpoint_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    encrypted_subscription: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    device_name: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationIntent(Base):
    __tablename__ = "notification_intents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["occurrence_id", "user_id"],
            ["meal_occurrences.id", "meal_occurrences.user_id"],
            name="fk_notification_intents_occurrence_user",
            ondelete="cascade",
        ),
        UniqueConstraint("occurrence_id", "kind", name="uq_notification_occurrence_kind"),
        Index("ix_notification_intents_due", "scheduled_for", "cancelled_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_profile.id", ondelete="cascade"), nullable=False
    )
    occurrence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="meal_reminder")
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WebPushDelivery(Base):
    __tablename__ = "web_push_deliveries"
    __table_args__ = (
        Index("ix_web_push_deliveries_claim", "status", "next_attempt_at", "leased_until"),
    )

    intent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notification_intents.id", ondelete="cascade"), primary_key=True
    )
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("push_subscriptions.id", ondelete="cascade"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    leased_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    last_status_code: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(64))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
