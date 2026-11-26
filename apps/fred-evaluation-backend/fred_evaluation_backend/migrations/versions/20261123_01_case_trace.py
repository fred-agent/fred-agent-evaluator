"""Retain case evidence inline; session identifies the single agent attempt.

Revision ID: 20261123_01
Revises: 20261111_01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261123_01"
down_revision: str | Sequence[str] | None = "20261111_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("evaluation_case") as batch:
        batch.drop_column("raw_trace_ref")
        batch.add_column(sa.Column("trace_json", sa.Text(), nullable=True))
        batch.add_column(sa.Column("execution_session_id", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("evaluation_case") as batch:
        batch.drop_column("trace_json")
        batch.drop_column("execution_session_id")
        batch.add_column(sa.Column("raw_trace_ref", sa.String(), nullable=True))
