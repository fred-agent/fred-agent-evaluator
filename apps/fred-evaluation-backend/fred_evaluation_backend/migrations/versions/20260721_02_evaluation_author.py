"""evaluation: declared author

Adds the optional `author` declared by the uploaded evaluation document.
Nullable on purpose: existing rows have no declared author, and the field is
optional in the document format. The verified uploader stays in `created_by`.

Revision ID: 20260721_02
Revises: 20260721_01
Create Date: 2026-07-21 13:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260721_02"
down_revision: str | Sequence[str] | None = "20260721_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "evaluation", sa.Column("author", sa.String(length=255), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("evaluation", "author")
