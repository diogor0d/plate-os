"""Add a daily fiber target to user profiles

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_profile",
        sa.Column("target_fiber_g", sa.Integer(), nullable=False, server_default="25"),
    )
    op.alter_column("user_profile", "target_fiber_g", server_default=None)


def downgrade() -> None:
    op.drop_column("user_profile", "target_fiber_g")
