"""add dataset_id to evaluation_campaign; relax dataset_name/version to nullable

Revision ID: f1b2c3d4e5a6
Revises: e7a9c1b3d5f2
Create Date: 2026-07-16 10:00:00.000000

EVAL-04: campaigns now reference EvaluationDataset by dataset_id. dataset_name /
dataset_version stop being written for new campaigns (the joined dataset is the
sole source going forward) but are kept, nullable, as a read-only remnant for
rows created before this migration — no backfill, no column drop.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1b2c3d4e5a6"  # pragma: allowlist secret
down_revision: Union[str, None] = "e7a9c1b3d5f2"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "evaluation_campaign",
        sa.Column("dataset_id", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_evaluation_campaign_dataset_id", "evaluation_campaign", ["dataset_id"]
    )
    op.create_foreign_key(
        "fk_evaluation_campaign_dataset_id",
        "evaluation_campaign",
        "evaluation_dataset",
        ["dataset_id"],
        ["dataset_id"],
    )
    op.alter_column(
        "evaluation_campaign",
        "dataset_name",
        existing_type=sa.String(length=255),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "evaluation_campaign",
        "dataset_name",
        existing_type=sa.String(length=255),
        nullable=False,
    )
    op.drop_constraint(
        "fk_evaluation_campaign_dataset_id", "evaluation_campaign", type_="foreignkey"
    )
    op.drop_index("ix_evaluation_campaign_dataset_id", "evaluation_campaign")
    op.drop_column("evaluation_campaign", "dataset_id")
