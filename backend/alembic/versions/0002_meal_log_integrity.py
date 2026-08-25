"""meal-log idempotency ledger and immutable nutrition density snapshots

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM meal_logs WHERE quantity_g <= 0) THEN
                RAISE EXCEPTION
                    'Cannot backfill meal density snapshots: quantity_g <= 0 exists';
            END IF;
        END $$
        """
    )

    op.alter_column(
        "meal_logs",
        "quantity_g",
        existing_type=sa.Numeric(6, 2),
        type_=sa.Numeric(8, 2),
        existing_nullable=False,
        postgresql_using="quantity_g::numeric(8,2)",
    )
    for column in (
        "calculated_calories",
        "calculated_protein",
        "calculated_carbs",
        "calculated_fat",
        "calculated_fiber",
    ):
        op.alter_column(
            "meal_logs",
            column,
            existing_type=sa.Numeric(6, 2),
            type_=sa.Numeric(12, 2),
            existing_nullable=False,
            postgresql_using=f"{column}::numeric(12,2)",
        )

    for column in (
        "calories_per_100",
        "protein_per_100",
        "carbs_per_100",
        "fat_per_100",
        "fiber_per_100",
    ):
        op.add_column(
            "meal_logs", sa.Column(column, sa.Numeric(14, 4), nullable=True)
        )

    op.execute(
        """
        UPDATE meal_logs
        SET calories_per_100 = round(calculated_calories * 100 / quantity_g, 4),
            protein_per_100 = round(calculated_protein * 100 / quantity_g, 4),
            carbs_per_100 = round(calculated_carbs * 100 / quantity_g, 4),
            fat_per_100 = round(calculated_fat * 100 / quantity_g, 4),
            fiber_per_100 = round(calculated_fiber * 100 / quantity_g, 4)
        """
    )
    for column in (
        "calories_per_100",
        "protein_per_100",
        "carbs_per_100",
        "fat_per_100",
        "fiber_per_100",
    ):
        op.alter_column(
            "meal_logs",
            column,
            existing_type=sa.Numeric(14, 4),
            nullable=False,
        )

    op.create_check_constraint(
        "ck_meal_logs_quantity_positive", "meal_logs", "quantity_g > 0"
    )
    op.create_check_constraint(
        "ck_meal_logs_density_nonnegative",
        "meal_logs",
        "calories_per_100 >= 0 AND protein_per_100 >= 0 "
        "AND carbs_per_100 >= 0 AND fat_per_100 >= 0 AND fiber_per_100 >= 0",
    )

    op.create_table(
        "meal_log_mutations",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_profile.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "client_mutation_id", postgresql.UUID(as_uuid=True), primary_key=True
        ),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "meal_log_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("meal_logs.id", ondelete="SET NULL"),
            nullable=True,
            unique=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM meal_logs
            WHERE abs(quantity_g) > 9999.99
               OR abs(calculated_calories) > 9999.99
               OR abs(calculated_protein) > 9999.99
               OR abs(calculated_carbs) > 9999.99
               OR abs(calculated_fat) > 9999.99
               OR abs(calculated_fiber) > 9999.99
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade meal-log numeric widths: out-of-range rows exist';
            END IF;
        END $$
        """
    )

    op.drop_table("meal_log_mutations")
    op.drop_constraint(
        "ck_meal_logs_density_nonnegative", "meal_logs", type_="check"
    )
    op.drop_constraint(
        "ck_meal_logs_quantity_positive", "meal_logs", type_="check"
    )
    for column in (
        "fiber_per_100",
        "fat_per_100",
        "carbs_per_100",
        "protein_per_100",
        "calories_per_100",
    ):
        op.drop_column("meal_logs", column)

    for column in (
        "calculated_fiber",
        "calculated_fat",
        "calculated_carbs",
        "calculated_protein",
        "calculated_calories",
    ):
        op.alter_column(
            "meal_logs",
            column,
            existing_type=sa.Numeric(12, 2),
            type_=sa.Numeric(6, 2),
            existing_nullable=False,
            postgresql_using=f"{column}::numeric(6,2)",
        )
    op.alter_column(
        "meal_logs",
        "quantity_g",
        existing_type=sa.Numeric(8, 2),
        type_=sa.Numeric(6, 2),
        existing_nullable=False,
        postgresql_using="quantity_g::numeric(6,2)",
    )
