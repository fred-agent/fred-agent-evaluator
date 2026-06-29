"""add question_set and evaluation_dataset tables

Revision ID: c5d3a2b1e4f7
Revises: b4e2f3a1c9d7
Create Date: 2026-06-29 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c5d3a2b1e4f7"  # pragma: allowlist secret
down_revision: Union[str, None] = "b4e2f3a1c9d7"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "question_set",
        sa.Column("question_set_id", sa.String(), primary_key=True),
        sa.Column("team_id", sa.String(), nullable=False),
        sa.Column("agent_id", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("period_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("keep_threshold", sa.Integer(), nullable=False),
        sa.Column("candidates_json", sa.Text(), nullable=True),
        sa.Column("extra_filters_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_question_set_team_id", "question_set", ["team_id"])
    op.create_index("ix_question_set_agent_id", "question_set", ["agent_id"])

    op.create_table(
        "evaluation_dataset",
        sa.Column("dataset_id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("version", sa.String(length=100), nullable=False),
        sa.Column("team_id", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("completeness", sa.String(length=32), nullable=False),
        sa.Column("source_question_set_id", sa.String(), nullable=True),
        sa.Column("cases_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_evaluation_dataset_name", "evaluation_dataset", ["name"])
    op.create_index("ix_evaluation_dataset_team_id", "evaluation_dataset", ["team_id"])
    op.create_index(
        "ix_evaluation_dataset_completeness", "evaluation_dataset", ["completeness"]
    )


def downgrade() -> None:
    op.drop_index("ix_evaluation_dataset_completeness", "evaluation_dataset")
    op.drop_index("ix_evaluation_dataset_team_id", "evaluation_dataset")
    op.drop_index("ix_evaluation_dataset_name", "evaluation_dataset")
    op.drop_table("evaluation_dataset")
    op.drop_index("ix_question_set_agent_id", "question_set")
    op.drop_index("ix_question_set_team_id", "question_set")
    op.drop_table("question_set")
