"""SQLAlchemy tables for the dataset domain.

Two tables, mirroring the RFC's two persisted models:

- ``question_set``       — capture + curation (mutable)
- ``evaluation_dataset`` — frozen, versioned dataset consumed by campaigns

Persistence rule (RFC §8): typed columns for everything we filter/sort/index;
a single Text column (JSON-serialized) for the nested/variable lists, whose shape
is guaranteed by the Pydantic models in ``schemas.py`` at the (de)serialization
boundary. We reuse the shared ``Base`` from ``campaigns.base`` so Alembic sees all
tables under one metadata.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from fred_evaluation_backend.campaigns.base import Base, utcnow


class QuestionSetRow(Base):
    __tablename__ = "question_set"

    question_set_id: Mapped[str] = mapped_column(String, primary_key=True)
    team_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="captured")
    period_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    period_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    keep_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    # JSON-serialized lists/maps (shape guaranteed by Pydantic schemas)
    candidates_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_filters_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class EvaluationDatasetRow(Base):
    __tablename__ = "evaluation_dataset"

    dataset_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(100), nullable=False)
    team_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    completeness: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_question_set_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # JSON-serialized list of DatasetCase (shape guaranteed by Pydantic schemas)
    cases_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
