"""multi-user accounts on user_profile

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-26

Adds nullable credential columns; the application bootstrap (not this
migration) backfills the pre-existing row from env secrets, so no plaintext
or derived secret material ever passes through Alembic.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_profile",
        sa.Column("username", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ux_user_profile_username", "user_profile", ["username"], unique=True
    )
    op.add_column(
        "user_profile",
        sa.Column("password_hash", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "user_profile",
        sa.Column(
            "is_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "user_profile",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("user_profile", "created_at")
    op.drop_column("user_profile", "is_admin")
    op.drop_index("ux_user_profile_username", table_name="user_profile")
    op.drop_column("user_profile", "password_hash")
    op.drop_column("user_profile", "username")
