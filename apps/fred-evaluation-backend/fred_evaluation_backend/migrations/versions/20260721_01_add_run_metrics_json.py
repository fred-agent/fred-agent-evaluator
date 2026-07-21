"""add evaluation_run.metrics_json

Revision ID: 20260721_01
Revises: 20260717_01
Create Date: 2026-07-21 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260721_01"
down_revision: str | Sequence[str] | None = "20260717_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("evaluation_run", sa.Column("metrics_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("evaluation_run", "metrics_json")
