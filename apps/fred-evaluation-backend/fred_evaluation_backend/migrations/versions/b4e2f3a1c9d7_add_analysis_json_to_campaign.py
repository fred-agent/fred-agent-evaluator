"""add analysis_json to evaluation_campaign

Revision ID: b4e2f3a1c9d7
Revises: a3f1e2c4d5b6
Create Date: 2026-06-22 18:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4e2f3a1c9d7"
down_revision: Union[str, None] = "a3f1e2c4d5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "evaluation_campaign",
        sa.Column("analysis_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("evaluation_campaign", "analysis_json")
