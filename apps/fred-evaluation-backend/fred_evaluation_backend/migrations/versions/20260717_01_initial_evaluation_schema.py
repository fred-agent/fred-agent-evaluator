"""initial evaluation schema

Revision ID: 20260717_01
Revises:
Create Date: 2026-07-17 12:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260717_01"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "question_set",
        sa.Column("question_set_id", sa.String(), nullable=False),
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
        sa.PrimaryKeyConstraint("question_set_id"),
    )
    op.create_index("ix_question_set_agent_id", "question_set", ["agent_id"])
    op.create_index("ix_question_set_team_id", "question_set", ["team_id"])

    op.create_table(
        "evaluation",
        sa.Column("evaluation_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("version", sa.String(length=100), nullable=False),
        sa.Column("team_id", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("completeness", sa.String(length=32), nullable=False),
        sa.Column("source_question_set_id", sa.String(), nullable=True),
        sa.Column("cases_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("evaluation_id"),
    )
    op.create_index("ix_evaluation_completeness", "evaluation", ["completeness"])
    op.create_index("ix_evaluation_name", "evaluation", ["name"])
    op.create_index("ix_evaluation_team_id", "evaluation", ["team_id"])

    op.create_table(
        "evaluation_run",
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("evaluation_id", sa.String(), nullable=False),
        sa.Column("team_id", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=True),
        sa.Column("target_kind", sa.String(length=32), nullable=False),
        sa.Column("target_runtime_id", sa.String(), nullable=True),
        sa.Column("target_agent_id", sa.String(), nullable=True),
        sa.Column("target_instance_id", sa.String(), nullable=False),
        sa.Column("profile", sa.String(length=64), nullable=False),
        sa.Column("judge_profile_id", sa.String(length=255), nullable=False),
        sa.Column("custom_metrics_json", sa.Text(), nullable=True),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("operational_state", sa.String(length=32), nullable=False),
        sa.Column("verdict", sa.String(length=32), nullable=False),
        sa.Column("total_cases", sa.Integer(), nullable=False),
        sa.Column("completed_cases", sa.Integer(), nullable=False),
        sa.Column("passed_cases", sa.Integer(), nullable=False),
        sa.Column("failed_cases", sa.Integer(), nullable=False),
        sa.Column("execution_error_cases", sa.Integer(), nullable=False),
        sa.Column("scoring_error_cases", sa.Integer(), nullable=False),
        sa.Column("metric_averages_json", sa.Text(), nullable=True),
        sa.Column("analysis_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["evaluation_id"], ["evaluation.evaluation_id"]),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index("ix_evaluation_run_created_by", "evaluation_run", ["created_by"])
    op.create_index("ix_evaluation_run_evaluation_id", "evaluation_run", ["evaluation_id"])
    op.create_index("ix_evaluation_run_task_id", "evaluation_run", ["task_id"])
    op.create_index("ix_evaluation_run_team_id", "evaluation_run", ["team_id"])

    op.create_table(
        "evaluation_case",
        sa.Column("case_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=True),
        sa.Column("verdict", sa.String(length=32), nullable=False),
        sa.Column("input", sa.Text(), nullable=False),
        sa.Column("expected_output", sa.Text(), nullable=True),
        sa.Column("actual_output", sa.Text(), nullable=True),
        sa.Column("profile", sa.String(length=64), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("token_usage_json", sa.Text(), nullable=True),
        sa.Column("structural_checks_json", sa.Text(), nullable=True),
        sa.Column("execution_error", sa.Text(), nullable=True),
        sa.Column("scoring_errors_json", sa.Text(), nullable=True),
        sa.Column("raw_trace_ref", sa.String(), nullable=True),
        sa.Column("telemetry_trace_id", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["evaluation_run.run_id"]),
        sa.PrimaryKeyConstraint("case_id"),
    )
    op.create_index("ix_evaluation_case_run_id", "evaluation_case", ["run_id"])

    op.create_table(
        "evaluation_metric_result",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("score", sa.String(length=32), nullable=True),
        sa.Column("threshold", sa.String(length=32), nullable=True),
        sa.Column("verdict", sa.String(length=32), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["case_id"], ["evaluation_case.case_id"]),
        sa.ForeignKeyConstraint(["run_id"], ["evaluation_run.run_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evaluation_metric_result_case_id", "evaluation_metric_result", ["case_id"])
    op.create_index("ix_evaluation_metric_result_run_id", "evaluation_metric_result", ["run_id"])

    op.create_table(
        "evaluation_event",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["evaluation_run.run_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evaluation_event_run_id", "evaluation_event", ["run_id"])

    op.create_table(
        "evaluation_export_delivery",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("exporter", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["evaluation_run.run_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_evaluation_export_delivery_run_id",
        "evaluation_export_delivery",
        ["run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_evaluation_export_delivery_run_id", table_name="evaluation_export_delivery")
    op.drop_table("evaluation_export_delivery")
    op.drop_index("ix_evaluation_event_run_id", table_name="evaluation_event")
    op.drop_table("evaluation_event")
    op.drop_index("ix_evaluation_metric_result_run_id", table_name="evaluation_metric_result")
    op.drop_index("ix_evaluation_metric_result_case_id", table_name="evaluation_metric_result")
    op.drop_table("evaluation_metric_result")
    op.drop_index("ix_evaluation_case_run_id", table_name="evaluation_case")
    op.drop_table("evaluation_case")
    op.drop_index("ix_evaluation_run_team_id", table_name="evaluation_run")
    op.drop_index("ix_evaluation_run_task_id", table_name="evaluation_run")
    op.drop_index("ix_evaluation_run_evaluation_id", table_name="evaluation_run")
    op.drop_index("ix_evaluation_run_created_by", table_name="evaluation_run")
    op.drop_table("evaluation_run")
    op.drop_index("ix_evaluation_team_id", table_name="evaluation")
    op.drop_index("ix_evaluation_name", table_name="evaluation")
    op.drop_index("ix_evaluation_completeness", table_name="evaluation")
    op.drop_table("evaluation")
    op.drop_index("ix_question_set_team_id", table_name="question_set")
    op.drop_index("ix_question_set_agent_id", table_name="question_set")
    op.drop_table("question_set")
