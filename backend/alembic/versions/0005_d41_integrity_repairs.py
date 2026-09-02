"""D41 ownership constraints for databases already upgraded through 0004

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("meal_occurrences", sa.Column("user_id", postgresql.UUID(as_uuid=True)))
    op.execute(
        """
        UPDATE meal_occurrences AS occurrence
        SET user_id = schedule.user_id
        FROM meal_schedules AS schedule
        WHERE occurrence.schedule_id = schedule.id
        """
    )
    op.alter_column("meal_occurrences", "user_id", nullable=False)
    op.add_column("meal_occurrence_logs", sa.Column("user_id", postgresql.UUID(as_uuid=True)))
    op.execute(
        """
        UPDATE meal_occurrence_logs AS occurrence_log
        SET user_id = occurrence.user_id
        FROM meal_occurrences AS occurrence
        WHERE occurrence_log.occurrence_id = occurrence.id
        """
    )
    op.alter_column("meal_occurrence_logs", "user_id", nullable=False)

    op.create_unique_constraint("uq_meal_logs_id_user", "meal_logs", ["id", "user_id"])
    op.create_unique_constraint("uq_routines_id_user", "meal_routines", ["id", "user_id"])
    op.create_unique_constraint("uq_schedules_id_user", "meal_schedules", ["id", "user_id"])
    op.create_unique_constraint("uq_occurrences_id_user", "meal_occurrences", ["id", "user_id"])

    op.drop_constraint("meal_schedules_routine_id_fkey", "meal_schedules", type_="foreignkey")
    op.create_foreign_key(
        "fk_schedules_routine_user", "meal_schedules", "meal_routines",
        ["routine_id", "user_id"], ["id", "user_id"], ondelete="CASCADE",
    )
    op.drop_constraint("meal_occurrences_schedule_id_fkey", "meal_occurrences", type_="foreignkey")
    op.create_foreign_key(
        "fk_occurrences_schedule_user", "meal_occurrences", "meal_schedules",
        ["schedule_id", "user_id"], ["id", "user_id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_occurrences_user", "meal_occurrences", "user_profile",
        ["user_id"], ["id"], ondelete="CASCADE",
    )
    op.drop_constraint("meal_occurrence_logs_occurrence_id_fkey", "meal_occurrence_logs", type_="foreignkey")
    op.drop_constraint("meal_occurrence_logs_meal_log_id_fkey", "meal_occurrence_logs", type_="foreignkey")
    op.create_foreign_key(
        "fk_occurrence_logs_occurrence_user", "meal_occurrence_logs", "meal_occurrences",
        ["occurrence_id", "user_id"], ["id", "user_id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_occurrence_logs_meal_user", "meal_occurrence_logs", "meal_logs",
        ["meal_log_id", "user_id"], ["id", "user_id"], ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_occurrence_logs_user", "meal_occurrence_logs", "user_profile",
        ["user_id"], ["id"], ondelete="CASCADE",
    )
    op.drop_constraint("notification_intents_occurrence_id_fkey", "notification_intents", type_="foreignkey")
    op.create_foreign_key(
        "fk_notification_intents_occurrence_user", "notification_intents", "meal_occurrences",
        ["occurrence_id", "user_id"], ["id", "user_id"], ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_notification_intents_occurrence_user", "notification_intents", type_="foreignkey")
    op.create_foreign_key(
        "notification_intents_occurrence_id_fkey", "notification_intents", "meal_occurrences",
        ["occurrence_id"], ["id"], ondelete="CASCADE",
    )
    op.drop_constraint("fk_occurrence_logs_user", "meal_occurrence_logs", type_="foreignkey")
    op.drop_constraint("fk_occurrence_logs_meal_user", "meal_occurrence_logs", type_="foreignkey")
    op.drop_constraint("fk_occurrence_logs_occurrence_user", "meal_occurrence_logs", type_="foreignkey")
    op.create_foreign_key(
        "meal_occurrence_logs_meal_log_id_fkey", "meal_occurrence_logs", "meal_logs",
        ["meal_log_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "meal_occurrence_logs_occurrence_id_fkey", "meal_occurrence_logs", "meal_occurrences",
        ["occurrence_id"], ["id"], ondelete="CASCADE",
    )
    op.drop_constraint("fk_occurrences_user", "meal_occurrences", type_="foreignkey")
    op.drop_constraint("fk_occurrences_schedule_user", "meal_occurrences", type_="foreignkey")
    op.create_foreign_key(
        "meal_occurrences_schedule_id_fkey", "meal_occurrences", "meal_schedules",
        ["schedule_id"], ["id"], ondelete="CASCADE",
    )
    op.drop_constraint("fk_schedules_routine_user", "meal_schedules", type_="foreignkey")
    op.create_foreign_key(
        "meal_schedules_routine_id_fkey", "meal_schedules", "meal_routines",
        ["routine_id"], ["id"], ondelete="CASCADE",
    )
    op.drop_constraint("uq_occurrences_id_user", "meal_occurrences", type_="unique")
    op.drop_constraint("uq_schedules_id_user", "meal_schedules", type_="unique")
    op.drop_constraint("uq_routines_id_user", "meal_routines", type_="unique")
    op.drop_constraint("uq_meal_logs_id_user", "meal_logs", type_="unique")
    op.drop_column("meal_occurrence_logs", "user_id")
    op.drop_column("meal_occurrences", "user_id")
