"""initial schema: user_profile, food_items, meal_logs, chat_messages

Revision ID: 0001
Revises:
Create Date: 2026-08-21

Deviations from the original brief (documented in
docs/decisions/2026-08-21-initial-stack-architecture.md, decision D15):
- meal_logs.calculated_fiber added (fiber was extracted but never persisted)
- chat_messages.session_id added (conversation threading)
- user_profile.timezone added (local-midnight daily rollups, decision D14)
- Index ix_meal_logs_user_logged_at on (user_id, logged_at) for range queries
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_profile",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("weight_kg", sa.Numeric(5, 2), nullable=False),
        sa.Column("height_cm", sa.Numeric(5, 2), nullable=False),
        sa.Column("target_calories", sa.Integer(), nullable=False),
        sa.Column("target_protein_g", sa.Integer(), nullable=False),
        sa.Column("target_carbs_g", sa.Integer(), nullable=False),
        sa.Column("target_fat_g", sa.Integer(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_table(
        "food_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("barcode", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("brand", sa.String(length=255), nullable=True),
        sa.Column("serving_unit", sa.String(length=32), nullable=False),
        sa.Column("calories_per_100", sa.Numeric(6, 2), nullable=False),
        sa.Column("protein_per_100", sa.Numeric(6, 2), nullable=False),
        sa.Column("carbs_per_100", sa.Numeric(6, 2), nullable=False),
        sa.Column("fat_per_100", sa.Numeric(6, 2), nullable=False),
        sa.Column("fiber_per_100", sa.Numeric(6, 2), nullable=False),
        sa.Column("is_verified", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("barcode", name="uq_food_items_barcode"),
    )
    op.create_table(
        "meal_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_profile.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "food_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("food_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("custom_name", sa.String(length=255), nullable=True),
        sa.Column(
            "logged_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("quantity_g", sa.Numeric(6, 2), nullable=False),
        sa.Column("calculated_calories", sa.Numeric(6, 2), nullable=False),
        sa.Column("calculated_protein", sa.Numeric(6, 2), nullable=False),
        sa.Column("calculated_carbs", sa.Numeric(6, 2), nullable=False),
        sa.Column("calculated_fat", sa.Numeric(6, 2), nullable=False),
        sa.Column("calculated_fiber", sa.Numeric(6, 2), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
    )
    op.create_index(
        "ix_meal_logs_user_logged_at", "meal_logs", ["user_id", "logged_at"], unique=False
    )
    op.create_table(
        "chat_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_profile.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("tool_calls", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_chat_messages_user_session",
        "chat_messages",
        ["user_id", "session_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_chat_messages_user_session", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_meal_logs_user_logged_at", table_name="meal_logs")
    op.drop_table("meal_logs")
    op.drop_table("food_items")
    op.drop_table("user_profile")
