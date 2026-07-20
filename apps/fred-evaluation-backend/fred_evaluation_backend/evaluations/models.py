"""SQLAlchemy tables for the evaluation catalog domain."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from fred_evaluation_backend.runs.base import Base, utcnow


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
    candidates_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_filters_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class EvaluationRow(Base):
    __tablename__ = "evaluation"

    evaluation_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(100), nullable=False)
    team_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    completeness: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_question_set_id: Mapped[str | None] = mapped_column(String, nullable=True)
    cases_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
