from __future__ import annotations

from datetime import timedelta

from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.worker import Worker, UnsandboxedWorkflowRunner
from temporalio.testing import WorkflowEnvironment

from fred_deepeval_cli.core.models import EvaluationCaseRequest
from fred_deepeval_cli.core.evaluator import evaluate_case_sync
from fred_deepeval_cli.core.judge_factory import build_judge


@activity.defn
async def evaluate_question_activity(params: dict) -> dict:
    """Une question = une activity Temporal."""
    request = EvaluationCaseRequest(
        agent_id=params["agent_id"],
        input=params["input"],
        session_id=params["session_id"],
        expected_output=params.get("expected_answer"),
        profile=params.get("profile", "auto"),
        runtime_context={
            "user_id": params["user_id"],
            **({"team_id": params["team_id"]} if params.get("team_id") else {}),
            **({"search_policy": params["search_policy"]} if params.get("search_policy") else {}),
        },
    )

    try:
        judge = build_judge()
        result = evaluate_case_sync(
            base_url=params["base_url"],
            request=request,
            judge=judge,
            access_token=params.get("access_token"),
        )
    except Exception as e:
        return {
            "id": params["id"],
            "input": params["input"],
            "outcome": "error",
            "profile": "unknown",
            "rag_ok": False,
            "structural_checks": [],
            "metrics": [],
            "error": str(e),
        }

    rag_ok = all(c.passed for c in result.structural_checks)
    metrics_by_name = {m.name: m.model_dump() for m in result.metrics}

    return {
        "id": params["id"],
        "input": params["input"],
        "outcome": result.outcome,
        "profile": result.profile,
        "rag_ok": rag_ok,
        "structural_checks": [c.model_dump() for c in result.structural_checks],
        "metrics": metrics_by_name,
    }


@workflow.defn
class RagDatasetWorkflow:
    @workflow.run
    async def run(self, questions: list[dict]) -> list[dict]:
        results = []
        for q in questions:
            result = await workflow.execute_activity(
                evaluate_question_activity,
                q,
                start_to_close_timeout=timedelta(minutes=10),
            )
            results.append(result)
        return results


async def run_with_temporal(questions: list[dict]) -> list[dict]:
    """Lance le workflow en mode in-memory (pas de serveur Temporal requis)."""
    async with await WorkflowEnvironment.start_local() as env:
        async with Worker(
            env.client,
            task_queue="rag-eval",
            workflows=[RagDatasetWorkflow],
            activities=[evaluate_question_activity],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            results: list[dict] = await env.client.execute_workflow(
                RagDatasetWorkflow.run,
                questions,
                id="rag-dataset-eval",
                task_queue="rag-eval",
            )
    return results


async def run_with_temporal_server(questions: list[dict], server_url: str) -> list[dict]:
    """Lance le workflow sur un serveur Temporal réel (production)."""
    client = await Client.connect(server_url)
    async with Worker(
        client,
        task_queue="rag-eval",
        workflows=[RagDatasetWorkflow],
        activities=[evaluate_question_activity],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        results: list[dict] = await client.execute_workflow(
            RagDatasetWorkflow.run,
            questions,
            id="rag-dataset-eval",
            task_queue="rag-eval",
        )
    return results
