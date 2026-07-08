"""EVAL-02: add the shared task-event bus tables (task_run, task_event_log)

Revision ID: d6e4b3c2f8a9
Revises: c5d3a2b1e4f7
Create Date: 2026-07-06 16:00:00.000000

Materializes the ``fred_core.tasks`` bus tables in the evaluator database so
campaigns can be driven as bus tasks (kind ``evaluation``) — the same task-event
bus + scheduler used by control-plane and knowledge-flow (EVAL-02).

The tables are created directly from the fred-core ORM models rather than a
hand-written DDL, so the schema can never drift from fred-core (and the correct
Postgres/SQLite column types are chosen from the bound dialect).
"""

from typing import Sequence, Union

from alembic import op
from fred_core.tasks.orm_models import TaskEventLogRow, TaskRunRow

revision: str = "d6e4b3c2f8a9"  # pragma: allowlist secret
down_revision: Union[str, None] = "c5d3a2b1e4f7"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    TaskRunRow.__table__.create(bind, checkfirst=True)
    TaskEventLogRow.__table__.create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    TaskEventLogRow.__table__.drop(bind, checkfirst=True)
    TaskRunRow.__table__.drop(bind, checkfirst=True)
