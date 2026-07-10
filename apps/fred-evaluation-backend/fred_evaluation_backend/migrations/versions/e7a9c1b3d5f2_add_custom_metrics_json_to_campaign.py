"""add custom_metrics_json to evaluation_campaign

Revision ID: e7a9c1b3d5f2
Revises: c5d3a2b1e4f7
Create Date: 2026-07-09 10:00:00.000000

EVAL-CUSTOM-METRIC: user-defined GEval criteria, stored as a JSON list of
CustomMetricSpec on the campaign so the worker can read them back at scoring time.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e7a9c1b3d5f2"  # pragma: allowlist secret
down_revision: Union[str, None] = "c5d3a2b1e4f7"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "evaluation_campaign",
        sa.Column("custom_metrics_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("evaluation_campaign", "custom_metrics_json")
