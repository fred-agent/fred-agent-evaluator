from __future__ import annotations

import argparse
import asyncio
import json
import uuid
import os
from pathlib import Path

from fred_deepeval_cli.cli.display import console, render_campaign
from fred_deepeval_cli.core.models import EvaluationCaseRequest
from fred_deepeval_cli.core.evaluator import evaluate_case_sync
from fred_deepeval_cli.core.judge_factory import build_judge
from dotenv import load_dotenv

dotenv_path = os.getenv("ENV_FILE", "./config/.env")
load_dotenv(dotenv_path)

DEFAULT_DATASET_PATH = (
    Path(__file__).resolve().parents[1] / "tests" / "rag_dataset.json"
)


def load_dataset(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate_scenario(
    scenario: dict,
    *,
    base_url: str,
    agent_id: str,
    user_id: str,
    team_id: str | None,
    access_token: str | None,
    search_policy: str | None,
) -> dict:
    session_id = f"{scenario['id']}-{uuid.uuid4().hex[:8]}"

    request = EvaluationCaseRequest(
        agent_id=agent_id,
        input=scenario["input"],
        session_id=session_id,
        expected_output=scenario.get("expected_answer"),
        runtime_context={
            "user_id": user_id,
            **({"team_id": team_id} if team_id else {}),
            **({"search_policy": search_policy} if search_policy else {}),
        },
    )

    judge = build_judge()
    result = evaluate_case_sync(base_url=base_url, request=request, judge=judge, access_token=access_token)

    rag_ok = all(c.passed for c in result.structural_checks)
    metrics_by_name = {m.name: {"score": m.score, "verdict": m.verdict, "explanation": m.explanation} for m in result.metrics}

    return {
        "id": scenario["id"],
        "input": scenario["input"],
        "outcome": result.outcome,
        "profile": result.profile,
        "rag_ok": rag_ok,
        "structural_checks": [c.model_dump() for c in result.structural_checks],
        "metrics": metrics_by_name,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run RAG evaluation scenarios against a fred RAG agent."
    )
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--agent-id", default="fred.github.rag_expert")
    parser.add_argument("--user-id", default="alice")
    parser.add_argument("--team-id")
    parser.add_argument("--access-token", default=os.environ.get("FRED_ACCESS_TOKEN"))
    parser.add_argument("--search-policy", default="semantic")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET_PATH))
    parser.add_argument("--use-temporal", action="store_true", default=False)
    parser.add_argument("--temporal-server", default=None)
    return parser


def _build_questions(dataset: list[dict], args: argparse.Namespace) -> list[dict]:
    questions = []
    for scenario in dataset:
        questions.append({
            "id": scenario["id"],
            "input": scenario["input"],
            "expected_answer": scenario.get("expected_answer"),
            "base_url": args.base_url,
            "agent_id": args.agent_id,
            "session_id": f"{scenario['id']}-{uuid.uuid4().hex[:8]}",
            "user_id": args.user_id,
            "team_id": args.team_id,
            "access_token": args.access_token,
            "search_policy": args.search_policy,
        })
    return questions


def main() -> int:
    args = build_parser().parse_args()
    dataset = load_dataset(Path(args.dataset))

    console.print(f"\n[bold cyan]RAG scenario campaign[/bold cyan] — {len(dataset)} question(s)\n")

    if args.use_temporal:
        from fred_deepeval_cli.dataset_workflow import run_with_temporal, run_with_temporal_server
        questions = _build_questions(dataset, args)
        if args.temporal_server:
            console.print(f"[dim]Mode Temporal — serveur : {args.temporal_server}[/dim]\n")
            results = asyncio.run(run_with_temporal_server(questions, args.temporal_server))
        else:
            console.print("[dim]Mode Temporal — in-memory (pas de serveur requis)[/dim]\n")
            results = asyncio.run(run_with_temporal(questions))
    else:
        results = []
        for i, scenario in enumerate(dataset, start=1):
            console.print(f"  [dim]{i}/{len(dataset)}[/dim] {scenario['id']}...")
            result = evaluate_scenario(
                scenario,
                base_url=args.base_url,
                agent_id=args.agent_id,
                user_id=args.user_id,
                team_id=args.team_id,
                access_token=args.access_token,
                search_policy=args.search_policy,
            )
            results.append(result)

    render_campaign(results)
    print(json.dumps({"results": results}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
