from __future__ import annotations

import argparse
import json
import uuid
import os
from numbers import Number
from pathlib import Path

from fred_deepeval_cli.cli.display import render_sql_campaign
from fred_deepeval_cli.core.models import EvaluationCaseRequest
from fred_deepeval_cli.core.evaluator import evaluate_case_sync, fetch_trace
from dotenv import load_dotenv

dotenv_path = os.getenv("ENV_FILE", "./config/.env")
load_dotenv(dotenv_path)

DEFAULT_SCENARIOS_PATH = (
    Path(__file__).resolve().parents[1] / "tests" / "sql_scenarios.json"
)


def load_scenarios(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def compare_expected_flow(checks: list[dict], expected_flow: dict) -> list[str]:
    failures: list[str] = []
    checks_by_name = {c["name"]: c["passed"] for c in checks}

    expected_query_executed = expected_flow.get("query_executed")
    if expected_query_executed is not None:
        actual = checks_by_name.get("sql_query_executed")
        if actual != expected_query_executed:
            failures.append(
                f"query_executed expected={expected_query_executed} actual={actual}"
            )

    return failures


def extract_latest_query_result(trace: dict) -> dict | None:
    for step in reversed(trace.get("steps", [])):
        if step.get("kind") != "tool_result":
            continue
        if step.get("tool_name") != "read_query":
            continue
        if step.get("is_error"):
            continue
        content = step.get("content")
        if isinstance(content, dict):
            return content
        if isinstance(content, str) and content.strip():
            if content.lstrip().startswith("Error:"):
                continue
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                return None
            if isinstance(parsed, dict):
                return parsed
    return None


def values_match(expected: object, actual: object, *, tolerance: float = 0.01) -> bool:
    if isinstance(expected, Number) and isinstance(actual, Number):
        return abs(float(expected) - float(actual)) <= tolerance
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.casefold() == actual.casefold()
    return expected == actual


def row_matches_expected_values(actual_row: dict, expected_row: dict) -> bool:
    for key, expected_value in expected_row.items():
        if key not in actual_row:
            return False
        if not values_match(expected_value, actual_row.get(key)):
            return False
    return True


def compare_expected_values(trace: dict, expected_values: dict) -> list[str]:
    failures: list[str] = []
    if not expected_values:
        return failures

    output = trace.get("output") or ""
    for snippet in expected_values.get("output_contains", []):
        if snippet not in output:
            failures.append(f"output missing snippet={snippet!r}")

    query_result = extract_latest_query_result(trace)
    rows = query_result.get("rows", []) if isinstance(query_result, dict) else []

    expects_query_result = any(
        key in expected_values for key in ("row_count", "first_row", "contains_rows")
    )
    if expects_query_result and query_result is None:
        failures.append(
            "expected query result but no successful read_query result was found"
        )
        return failures

    if expected_values.get("row_count") is not None:
        expected_row_count = expected_values["row_count"]
        if len(rows) != expected_row_count:
            failures.append(
                f"row_count expected={expected_row_count} actual={len(rows)}"
            )

    expected_first_row = expected_values.get("first_row")
    if expected_first_row is not None:
        if not rows:
            failures.append("first_row expected but query returned no rows")
        elif not row_matches_expected_values(rows[0], expected_first_row):
            failures.append(f"first_row expected={expected_first_row} actual={rows[0]}")

    for expected_row in expected_values.get("contains_rows", []):
        if not any(row_matches_expected_values(r, expected_row) for r in rows):
            failures.append(f"expected row not found: {expected_row}")

    return failures


def summarize_observed_values(trace: dict) -> dict:
    query_result = extract_latest_query_result(trace)
    rows = query_result.get("rows", []) if isinstance(query_result, dict) else []
    sql_query = (
        query_result.get("sql_query") if isinstance(query_result, dict) else None
    )
    return {
        "sql_query": sql_query,
        "query_row_count": len(rows),
        "query_first_row": rows[0] if rows else None,
    }


def evaluate_scenario(
    scenario: dict,
    *,
    base_url: str,
    agent_id: str,
    user_id: str,
    team_id: str | None,
    access_token: str | None,
) -> tuple[str, dict]:
    session_id = f"{scenario['id']}-{uuid.uuid4().hex[:8]}"

    request = EvaluationCaseRequest(
        agent_id=agent_id,
        input=scenario["input"],
        session_id=session_id,
        runtime_context={
            "user_id": user_id,
            **({"team_id": team_id} if team_id else {}),
        },
    )

    trace = fetch_trace(base_url=base_url, request=request, access_token=access_token)
    result = evaluate_case_sync(
        base_url=base_url, request=request, access_token=access_token
    )

    checks_as_dicts = [c.model_dump() for c in result.structural_checks]
    failures = compare_expected_flow(checks_as_dicts, scenario.get("expected_flow", {}))
    failures.extend(compare_expected_values(trace, scenario.get("expected_values", {})))

    return result.outcome, {
        "id": scenario["id"],
        "input": scenario["input"],
        "outcome": result.outcome,
        "profile": result.profile,
        "expected_flow": scenario.get("expected_flow", {}),
        "expected_values": scenario.get("expected_values", {}),
        "observed_checks": {c["name"]: c["passed"] for c in checks_as_dicts},
        "observed_values": summarize_observed_values(trace),
        "pass": not failures,
        "failures": failures,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run SQL evaluation scenarios.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--agent-id", default="fred.github.sql_expert")
    parser.add_argument("--user-id", default="alice")
    parser.add_argument("--team-id")
    parser.add_argument("--access-token", default=os.environ.get("FRED_ACCESS_TOKEN"))
    parser.add_argument("--scenarios", default=str(DEFAULT_SCENARIOS_PATH))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    scenarios = load_scenarios(Path(args.scenarios))

    results: list[dict] = []
    has_failures = False

    for scenario in scenarios:
        _, result = evaluate_scenario(
            scenario,
            base_url=args.base_url,
            agent_id=args.agent_id,
            user_id=args.user_id,
            team_id=args.team_id,
            access_token=args.access_token,
        )
        results.append(result)
        if not result["pass"]:
            has_failures = True

    render_sql_campaign(results)
    print(json.dumps({"results": results}, indent=2, ensure_ascii=False))
    return 1 if has_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
