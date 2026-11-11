"""evaluation_run: drop task_id

The `/tasks` surface that addressed a run by a separate task id is gone (Fred 5
has no shared task tray); a run is addressed by its `run_id` only.

Revision ID: 20261111_01
Revises: 20260910_01
Create Date: 2026-11-11 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261111_01"
down_revision: str | Sequence[str] | None = "20260910_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Batch mode: SQLite cannot drop an indexed column in place.
    with op.batch_alter_table("evaluation_run") as batch:
        batch.drop_index("ix_evaluation_run_task_id")
        batch.drop_column("task_id")


def downgrade() -> None:
    with op.batch_alter_table("evaluation_run") as batch:
        batch.add_column(sa.Column("task_id", sa.String(), nullable=True))
        batch.create_index("ix_evaluation_run_task_id", ["task_id"])
