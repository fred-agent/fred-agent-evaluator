from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from rich.text import Text

from fred_deepeval_cli.core.models import EvaluationCaseRequest, EvaluationCaseResult

console = Console(stderr=True)


def _check_icon(value: object) -> str:
    return "✅" if value is True else "❌"


def _outcome_text(outcome: str) -> Text:
    if outcome == "execution_error":
        return Text(f"  {outcome}", style="bold red")
    return Text(f"  {outcome}", style="bold green")


def render_score(
    result: EvaluationCaseResult,
    request: EvaluationCaseRequest | None = None,
) -> None:
    # ── Header ──────────────────────────────────────────────────────────────
    header = Table.grid(padding=(0, 2))
    header.add_column(style="bold cyan")
    header.add_column()
    if request:
        header.add_row("Agent", request.agent_id)
        header.add_row("Session", request.session_id)
        header.add_row("Input", request.input)
    header.add_row("Profile", result.profile)

    console.print()
    console.print(
        Panel(header, title="[bold]fred-deepeval-cli[/bold]", border_style="cyan")
    )

    # ── Output agent ────────────────────────────────────────────────────────
    agent_output = result.actual_output or "—"
    console.print(Panel(agent_output, title="Output", border_style="yellow"))

    # ── Outcome ─────────────────────────────────────────────────────────────
    console.print(
        Panel(
            _outcome_text(result.outcome),
            title="Outcome",
            border_style="green" if result.outcome != "execution_error" else "red",
        )
    )

    # ── Structural Checks ───────────────────────────────────────────────────
    if result.structural_checks:
        table = Table(box=box.SIMPLE, show_header=True, header_style="bold magenta")
        table.add_column("Check", style="cyan")
        table.add_column("", justify="center")

        for check in result.structural_checks:
            table.add_row(check.name, _check_icon(check.passed))

        console.print(
            Panel(
                table,
                title=f"Structural Checks [{result.profile}]",
                border_style="magenta",
            )
        )

    # ── DeepEval Metrics ────────────────────────────────────────────────────
    if result.metrics:
        table = Table(box=box.SIMPLE, show_header=True, header_style="bold blue")
        table.add_column("Metric", style="cyan")
        table.add_column("Score", justify="right")
        table.add_column("", justify="center")
        table.add_column("Reason", style="dim", no_wrap=False, max_width=60)

        for m in result.metrics:
            score_str = f"{m.score:.2f}" if isinstance(m.score, float) else "—"
            icon = (
                "✅"
                if m.verdict == "passed"
                else ("⏭" if m.verdict == "skipped" else "❌")
            )
            table.add_row(m.name, score_str, icon, m.explanation or m.error or "—")

        console.print(Panel(table, title="DeepEval Metrics", border_style="blue"))

    # ── Erreurs ─────────────────────────────────────────────────────────────
    if result.scoring_errors:
        console.print(
            Panel(
                "\n".join(result.scoring_errors),
                title="Scoring Errors",
                border_style="red",
            )
        )

    console.print()


# ── Campagne ────────────────────────────────────────────────────────────────

_CAMPAIGN_METRICS = [
    "AnswerRelevancyMetric",
    "FaithfulnessMetric",
    "ContextualRelevancyMetric",
    "ContextualPrecisionMetric",
    "ContextualRecallMetric",
]


def _fmt_score(metrics_by_name: dict, name: str, totals: dict) -> str:
    m = metrics_by_name.get(name)
    if m is None:
        return "—"
    score = m.get("score")
    if score is None:
        return "—"
    totals[name].append(score)
    icon = "✅" if m.get("verdict") == "passed" else "❌"
    return f"{score:.2f}{icon}"


def render_campaign(results: list[dict]) -> None:
    """Affiche le tableau récapitulatif d'une campagne RAG."""
    totals: dict[str, list[float]] = {m: [] for m in _CAMPAIGN_METRICS}

    table = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
    table.add_column("ID", style="dim", width=22)
    table.add_column("Outcome", width=10)
    table.add_column("RAG", justify="center", width=5)
    table.add_column("AnswerRel", justify="right", width=10)
    table.add_column("Faithful", justify="right", width=10)
    table.add_column("CtxRel", justify="right", width=8)
    table.add_column("CtxPrec", justify="right", width=9)
    table.add_column("CtxRecall", justify="right", width=10)

    for r in results:
        raw_metrics = r.get("metrics", {})
        metrics_by_name = (
            raw_metrics
            if isinstance(raw_metrics, dict)
            else {m["name"]: m for m in raw_metrics}
        )
        table.add_row(
            r["id"],
            r["outcome"],
            "✅" if r.get("rag_ok") else "❌",
            _fmt_score(metrics_by_name, "AnswerRelevancyMetric", totals),
            _fmt_score(metrics_by_name, "FaithfulnessMetric", totals),
            _fmt_score(metrics_by_name, "ContextualRelevancyMetric", totals),
            _fmt_score(metrics_by_name, "ContextualPrecisionMetric", totals),
            _fmt_score(metrics_by_name, "ContextualRecallMetric", totals),
        )

    console.print()
    console.print(Panel(table, title="Résultats par scénario", border_style="cyan"))

    # ── Moyennes ─────────────────────────────────────────────────────────────
    avg_table = Table(box=box.SIMPLE, show_header=True, header_style="bold blue")
    avg_table.add_column("Métrique", style="cyan")
    avg_table.add_column("Moyenne", justify="right")
    avg_table.add_column("N", justify="right", style="dim")

    overall: list[float] = []
    for name in _CAMPAIGN_METRICS:
        scores = totals[name]
        if scores:
            avg = sum(scores) / len(scores)
            overall.append(avg)
            avg_table.add_row(name, f"{avg:.4f}  ({avg * 100:.1f}%)", str(len(scores)))
        else:
            avg_table.add_row(name, "—", "0")

    if overall:
        global_avg = sum(overall) / len(overall)
        avg_table.add_row(
            "OVERALL",
            f"{global_avg:.4f}  ({global_avg * 100:.1f}%)",
            "",
            style="bold",
        )

    console.print(Panel(avg_table, title="Moyennes par métrique", border_style="blue"))
    console.print()


def render_sql_campaign(results: list[dict]) -> None:
    """Affiche le tableau récapitulatif d'une campagne SQL."""
    table = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
    table.add_column("ID", style="dim", width=22)
    table.add_column("Outcome", width=12)
    table.add_column("Query exec", justify="center", width=12)
    table.add_column("No error", justify="center", width=10)
    table.add_column("Pass", justify="center", width=6)
    table.add_column("Failures", style="dim", no_wrap=False, max_width=50)

    passed = 0
    for r in results:
        checks = r.get("observed_checks", {})
        failures = r.get("failures", [])
        is_pass = r.get("pass", False)
        if is_pass:
            passed += 1

        table.add_row(
            r["id"],
            r["outcome"],
            "✅" if checks.get("sql_query_executed") else "❌",
            "✅" if checks.get("sql_no_execution_error") else "❌",
            "✅" if is_pass else "❌",
            " | ".join(failures) if failures else "—",
        )

    console.print()
    console.print(Panel(table, title="Résultats SQL par scénario", border_style="cyan"))

    total = len(results)
    color = "green" if passed == total else "yellow" if passed > 0 else "red"
    console.print(
        Panel(
            f"[bold {color}]{passed}/{total} scénarios passés[/bold {color}]",
            border_style=color,
        )
    )
    console.print()
