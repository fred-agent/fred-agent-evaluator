"""evaluation_run/evaluation_case: agent model override + actual model traceability

Adds `evaluation_run.agent_model_override` (the run-scoped chat-model override
requested at run creation, threaded to the Control Plane's prepare-execution —
never persisted to the team's routing policy) and
`evaluation_case.actual_model_name` (the model that actually answered, read
from `EvalTrace.model_name` — ground truth, may differ from the requested
override if a higher-precedence Control Plane policy silently won).

Revision ID: 20260910_01
Revises: 20260722_01
Create Date: 2026-09-10 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260910_01"
down_revision: str | Sequence[str] | None = "20260722_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "evaluation_run",
        sa.Column("agent_model_override", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "evaluation_case",
        sa.Column("actual_model_name", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("evaluation_case", "actual_model_name")
    op.drop_column("evaluation_run", "agent_model_override")
