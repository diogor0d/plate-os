"""reviewed products, meal routines, occurrences, and Web Push outbox

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("food_items", sa.Column("nutrition_source", sa.String(32), nullable=True))
    op.add_column("food_items", sa.Column("accepted_by_user_id", postgresql.UUID(as_uuid=True)))
    op.add_column("food_items", sa.Column("accepted_at", sa.DateTime(timezone=True)))
    op.add_column("food_items", sa.Column("updated_at", sa.DateTime(timezone=True)))
    op.add_column("food_items", sa.Column("version", sa.Integer(), server_default="1", nullable=False))
    op.add_column("food_items", sa.Column("archived_at", sa.DateTime(timezone=True)))
    op.create_foreign_key(
        "fk_food_items_accepted_by_user", "food_items", "user_profile",
        ["accepted_by_user_id"], ["id"], ondelete="SET NULL",
    )
    op.execute(
        """
        UPDATE food_items
        SET nutrition_source = 'manual',
            accepted_at = CASE WHEN is_verified THEN created_at ELSE NULL END,
            updated_at = created_at,
            archived_at = CASE WHEN is_verified THEN NULL ELSE created_at END
        """
    )
    op.alter_column("food_items", "nutrition_source", nullable=False, server_default="manual")
    op.alter_column("food_items", "updated_at", nullable=False, server_default=sa.text("now()"))
    op.create_check_constraint(
        "ck_food_items_density_nonnegative", "food_items",
        "calories_per_100 >= 0 AND protein_per_100 >= 0 AND carbs_per_100 >= 0 "
        "AND fat_per_100 >= 0 AND fiber_per_100 >= 0",
    )
    op.create_check_constraint("ck_food_items_version_positive", "food_items", "version >= 1")
    op.drop_column("food_items", "is_verified")

    op.create_table(
        "food_item_mutations",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_mutation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("food_item_id", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_profile.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["food_item_id"], ["food_items.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("user_id", "client_mutation_id"),
    )

    op.create_table(
        "meal_routines",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("rough_text", sa.String(2000)),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("mode IN ('rough', 'defined')", name="ck_meal_routines_mode"),
        sa.CheckConstraint("version >= 1", name="ck_meal_routines_version_positive"),
        sa.ForeignKeyConstraint(["user_id"], ["user_profile.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_meal_routines_user_active", "meal_routines", ["user_id", "archived_at", "updated_at"])

    op.create_table(
        "meal_routine_items",
        sa.Column("routine_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("food_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quantity_g", sa.Numeric(8, 2), nullable=False),
        sa.CheckConstraint("position >= 0 AND position <= 7", name="ck_routine_items_position"),
        sa.CheckConstraint("quantity_g > 0", name="ck_routine_items_quantity"),
        sa.ForeignKeyConstraint(["routine_id"], ["meal_routines.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["food_item_id"], ["food_items.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("routine_id", "position"),
        sa.UniqueConstraint("routine_id", "food_item_id", name="uq_routine_items_product"),
    )

    op.create_table(
        "meal_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("routine_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("local_time", sa.Time(), nullable=False),
        sa.Column("frequency", sa.String(16), nullable=False),
        sa.Column("interval", sa.SmallInteger(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date()),
        sa.Column("reminder_minutes", sa.SmallInteger()),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("frequency IN ('daily', 'weekly')", name="ck_meal_schedules_frequency"),
        sa.CheckConstraint("interval >= 1 AND interval <= 4", name="ck_meal_schedules_interval"),
        sa.CheckConstraint("version >= 1", name="ck_meal_schedules_version_positive"),
        sa.CheckConstraint("end_date IS NULL OR end_date >= start_date", name="ck_meal_schedules_dates"),
        sa.CheckConstraint(
            "reminder_minutes IS NULL OR (reminder_minutes >= 0 AND reminder_minutes <= 1440)",
            name="ck_meal_schedules_reminder",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user_profile.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["routine_id"], ["meal_routines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_meal_schedules_user_enabled", "meal_schedules", ["user_id", "enabled"])

    op.create_table(
        "meal_schedule_weekdays",
        sa.Column("schedule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("iso_weekday", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint("iso_weekday >= 1 AND iso_weekday <= 7", name="ck_schedule_weekdays_iso"),
        sa.ForeignKeyConstraint(["schedule_id"], ["meal_schedules.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("schedule_id", "iso_weekday"),
    )

    op.create_table(
        "meal_occurrences",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("schedule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scheduled_local_date", sa.Date(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("time_resolution", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("acted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('scheduled', 'completed', 'skipped')", name="ck_occurrences_status"),
        sa.ForeignKeyConstraint(["schedule_id"], ["meal_schedules.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("schedule_id", "scheduled_local_date", name="uq_occurrence_schedule_day"),
    )
    op.create_index("ix_occurrences_schedule_at", "meal_occurrences", ["schedule_id", "scheduled_at"])

    op.create_table(
        "meal_occurrence_logs",
        sa.Column("occurrence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("meal_log_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.ForeignKeyConstraint(["occurrence_id"], ["meal_occurrences.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["meal_log_id"], ["meal_logs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("occurrence_id", "meal_log_id"),
        sa.UniqueConstraint("meal_log_id", name="uq_occurrence_logs_meal"),
        sa.UniqueConstraint("occurrence_id", "position", name="uq_occurrence_logs_position"),
    )

    op.create_table(
        "planning_mutations",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_mutation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_profile.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "client_mutation_id"),
    )

    op.create_table(
        "push_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("endpoint_fingerprint", sa.String(64), nullable=False),
        sa.Column("encrypted_subscription", sa.LargeBinary(), nullable=False),
        sa.Column("device_name", sa.String(80)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("disabled_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["user_id"], ["user_profile.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("endpoint_fingerprint", name="uq_push_endpoint_fingerprint"),
    )
    op.create_index("ix_push_subscriptions_user_active", "push_subscriptions", ["user_id", "disabled_at"])

    op.create_table(
        "notification_intents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("occurrence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_profile.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["occurrence_id"], ["meal_occurrences.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("occurrence_id", "kind", name="uq_notification_occurrence_kind"),
    )
    op.create_index("ix_notification_intents_due", "notification_intents", ["scheduled_for", "cancelled_at"])

    op.create_table(
        "web_push_deliveries",
        sa.Column("intent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subscription_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("leased_until", sa.DateTime(timezone=True)),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True)),
        sa.Column("last_status_code", sa.Integer()),
        sa.Column("error_code", sa.String(64)),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["intent_id"], ["notification_intents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subscription_id"], ["push_subscriptions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("intent_id", "subscription_id"),
    )
    op.create_index(
        "ix_web_push_deliveries_claim", "web_push_deliveries",
        ["status", "next_attempt_at", "leased_until"],
    )


def downgrade() -> None:
    op.drop_index("ix_web_push_deliveries_claim", table_name="web_push_deliveries")
    op.drop_table("web_push_deliveries")
    op.drop_index("ix_notification_intents_due", table_name="notification_intents")
    op.drop_table("notification_intents")
    op.drop_index("ix_push_subscriptions_user_active", table_name="push_subscriptions")
    op.drop_table("push_subscriptions")
    op.drop_table("planning_mutations")
    op.drop_table("meal_occurrence_logs")
    op.drop_index("ix_occurrences_schedule_at", table_name="meal_occurrences")
    op.drop_table("meal_occurrences")
    op.drop_table("meal_schedule_weekdays")
    op.drop_index("ix_meal_schedules_user_enabled", table_name="meal_schedules")
    op.drop_table("meal_schedules")
    op.drop_table("meal_routine_items")
    op.drop_index("ix_meal_routines_user_active", table_name="meal_routines")
    op.drop_table("meal_routines")
    op.drop_table("food_item_mutations")

    op.add_column(
        "food_items",
        sa.Column("is_verified", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.execute("UPDATE food_items SET is_verified = (accepted_at IS NOT NULL)")
    op.drop_constraint("ck_food_items_version_positive", "food_items", type_="check")
    op.drop_constraint("ck_food_items_density_nonnegative", "food_items", type_="check")
    op.drop_constraint("fk_food_items_accepted_by_user", "food_items", type_="foreignkey")
    op.drop_column("food_items", "archived_at")
    op.drop_column("food_items", "version")
    op.drop_column("food_items", "updated_at")
    op.drop_column("food_items", "accepted_at")
    op.drop_column("food_items", "accepted_by_user_id")
    op.drop_column("food_items", "nutrition_source")
