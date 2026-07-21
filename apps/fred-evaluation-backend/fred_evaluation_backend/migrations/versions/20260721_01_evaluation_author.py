"""evaluation: declared author

Adds the optional `author` declared by the uploaded evaluation document.
Nullable on purpose: existing rows have no declared author, and the field is
optional in the document format. The verified uploader stays in `created_by`.

Revision ID: 20260721_01
Revises: 20260717_01
Create Date: 2026-07-21 13:40:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260721_01"
down_revision: Union[str, Sequence[str], None] = "20260717_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "evaluation", sa.Column("author", sa.String(length=255), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("evaluation", "author")
