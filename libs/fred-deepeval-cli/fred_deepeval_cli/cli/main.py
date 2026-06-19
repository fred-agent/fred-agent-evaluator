from __future__ import annotations

import argparse
import json
import os

from fred_deepeval_cli.core.models import EvaluationCaseRequest
from fred_deepeval_cli.core.evaluator import evaluate_case_sync
from fred_deepeval_cli.core.judge_factory import build_judge
from fred_deepeval_cli.cli.display import render_score
from dotenv import load_dotenv

dotenv_path = os.getenv("ENV_FILE", "./config/.env")
load_dotenv(dotenv_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fred-deepeval-cli",
        description="External CLI for evaluating Fred agent turns.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    score_parser = subparsers.add_parser(
        "score",
        help="Evaluate one Fred agent turn and score it with DeepEval.",
    )
    add_shared_eval_args(score_parser)

    return parser


def add_shared_eval_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-url", required=True, help="Fred pod base URL.")
    parser.add_argument("--agent-id", required=True, help="Agent identifier.")
    parser.add_argument("--input", required=True, help="User input to evaluate.")
    parser.add_argument("--session-id", required=True, help="Session identifier.")
    parser.add_argument("--user-id", required=True, help="Runtime user identifier.")
    parser.add_argument("--team-id", help="Optional runtime team identifier.")
    parser.add_argument(
        "--access-token",
        default=os.environ.get("FRED_ACCESS_TOKEN"),
        help="Optional bearer token for authenticated agent evaluation.",
    )
    parser.add_argument(
        "--search-policy",
        default=os.environ.get("FRED_SEARCH_POLICY"),
        help="Optional runtime search policy override (for example: semantic).",
    )
    parser.add_argument(
        "--profile",
        default="auto",
        choices=["auto", "rag", "sql", "workflow", "default"],
        help="Evaluation profile. Defaults to auto-detection from agent_tags.",
    )


def run_score(args: argparse.Namespace) -> int:
    runtime_context: dict = {"user_id": args.user_id}
    if args.team_id:
        runtime_context["team_id"] = args.team_id
    if args.search_policy:
        runtime_context["search_policy"] = args.search_policy

    request = EvaluationCaseRequest(
        agent_id=args.agent_id,
        input=args.input,
        session_id=args.session_id,
        profile=args.profile,
        runtime_context=runtime_context,
    )

    judge = build_judge()
    result = evaluate_case_sync(
        base_url=args.base_url,
        request=request,
        judge=judge,
        access_token=args.access_token,
    )

    render_score(result, request=request)
    print(json.dumps(result.model_dump(), indent=2, ensure_ascii=False))

    return 1 if result.outcome == "execution_error" else 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "score":
        return run_score(args)

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
