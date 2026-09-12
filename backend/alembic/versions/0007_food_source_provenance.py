"""Preserve official food provenance and four-decimal densities

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("food_items", sa.Column("nutrition_source_id", sa.String(64)))
    op.add_column("food_items", sa.Column("nutrition_source_version", sa.String(32)))
    for column in (
        "calories_per_100", "protein_per_100", "carbs_per_100", "fat_per_100", "fiber_per_100"
    ):
        op.alter_column(
            "food_items",
            column,
            existing_type=sa.Numeric(6, 2),
            type_=sa.Numeric(14, 4),
            existing_nullable=False,
        )


def downgrade() -> None:
    for column in (
        "calories_per_100", "protein_per_100", "carbs_per_100", "fat_per_100", "fiber_per_100"
    ):
        op.alter_column(
            "food_items",
            column,
            existing_type=sa.Numeric(14, 4),
            type_=sa.Numeric(6, 2),
            existing_nullable=False,
        )
    op.drop_column("food_items", "nutrition_source_version")
    op.drop_column("food_items", "nutrition_source_id")
