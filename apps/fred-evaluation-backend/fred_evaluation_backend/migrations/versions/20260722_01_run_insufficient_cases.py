"""evaluation_run: track insufficient_cases

`EvaluationRun.verdict` per case can be "passed", "insufficient", or "failed"
(see `activities.py`'s verdict decision), but the run-level aggregate only
ever counted "passed" and "failed" — a case landing on "insufficient" (partial
metric coverage, no outright failure) was silently excluded from every
run-level counter (passed_cases, failed_cases, execution_error_cases,
scoring_error_cases), making completed cases look uncounted in the UI even
though the run was progressing normally.

server_default="0" backfills existing rows; new rows get it from
`summarize_cases()` like every other aggregate column.

Revision ID: 20260722_01
Revises: 20260721_02
Create Date: 2026-07-22 05:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260722_01"
down_revision: str | Sequence[str] | None = "20260721_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "evaluation_run",
        sa.Column(
            "insufficient_cases",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("evaluation_run", "insufficient_cases")
