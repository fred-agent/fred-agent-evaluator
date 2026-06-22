"""add metric_averages_json to evaluation_campaign

Revision ID: a3f1e2c4d5b6
Revises: 61967f47d286
Create Date: 2026-06-19 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a3f1e2c4d5b6"
down_revision: Union[str, None] = "61967f47d286"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "evaluation_campaign",
        sa.Column("metric_averages_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("evaluation_campaign", "metric_averages_json")
