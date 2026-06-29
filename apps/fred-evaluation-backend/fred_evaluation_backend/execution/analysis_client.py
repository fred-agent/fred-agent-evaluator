from __future__ import annotations

import logging
from dataclasses import dataclass

from fred_core.common import ModelConfiguration

from fred_evaluation_backend.model.factory import build_judge_model

logger = logging.getLogger(__name__)


def _extract_json_object(text: str) -> str:
    """Return the outermost JSON object found in `text`.

    Unlike the old raw HTTP call (which forced `response_format=json_object`),
    DeepEval's `a_generate` does not constrain the output format, so models often
    wrap the JSON in markdown fences or add a sentence of prose around it. The
    downstream caller does `json.loads`, which fails on anything but pure JSON —
    so extract the object spanning the first `{` to the last `}`.
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return text.strip()
    return text[start : end + 1]


_PROFILE_FOCUS = {
    "rag": (
        "Focus your analysis on retrieval quality: ContextualRelevancy, ContextualPrecision, "
        "ContextualRecall, and Faithfulness. Flag any drop in grounding or source accuracy."
    ),
    "sql": (
        "Focus your analysis on query correctness and data accuracy. "
        "Flag any incorrect SQL generation, wrong results, or schema mismatches."
    ),
    "workflow": (
        "Focus your analysis on task completion and step accuracy across the workflow. "
        "Flag any broken steps, incorrect tool calls, or incomplete task execution."
    ),
    "default": (
        "Analyse all metrics holistically and identify strengths and areas for improvement."
    ),
}


@dataclass
class CaseMetricDetail:
    name: str
    score: float | None
    verdict: str
    explanation: str | None


@dataclass
class CaseDetail:
    case_id: str
    input: str
    verdict: str
    metrics: list[CaseMetricDetail]


def _build_prompt(
    campaign_name: str,
    profile: str,
    verdict: str,
    total_cases: int,
    passed_cases: int,
    failed_cases: int,
    metric_averages: dict[str, float],
    cases: list[CaseDetail],
) -> str:
    focus = _PROFILE_FOCUS.get(profile, _PROFILE_FOCUS["default"])

    metrics_lines = "\n".join(
        f"  {name}: {round(score * 100)}%" for name, score in metric_averages.items()
    )

    case_lines: list[str] = []
    for c in cases:
        prefix = "PASS" if c.verdict == "passed" else "FAIL"
        case_lines.append(f"  [{prefix}] {c.input[:120]}")
        if c.verdict != "passed":
            for m in c.metrics:
                score_str = f"{round(m.score * 100)}%" if m.score is not None else "n/a"
                expl = f" | {m.explanation}" if m.explanation else ""
                case_lines.append(f"         {m.name}: {score_str} ({m.verdict}){expl}")

    cases_section = (
        "\n".join(case_lines) if case_lines else "  No case details available."
    )

    return (
        f"You are a senior AI/ML engineer at Thales reviewing an automated evaluation report "
        f"for an enterprise LLM agent. The agent runs in a production environment and is used "
        f"by internal teams. Your analysis must be technical, precise, and actionable — "
        f"written for engineers, not business stakeholders.\n\n"
        f"CAMPAIGN: {campaign_name}\n"
        f"PROFILE: {profile}\n"
        f"VERDICT: {verdict.upper()} — {passed_cases}/{total_cases} cases passed, {failed_cases} failed\n\n"
        f"METRIC AVERAGES:\n{metrics_lines}\n\n"
        f"CASE BREAKDOWN:\n{cases_section}\n\n"
        f"EVALUATION FOCUS: {focus}\n\n"
        f"Return ONLY a valid JSON object. No markdown, no explanation outside the JSON.\n"
        f"Schema:\n"
        f"{{\n"
        f'  "summary": "2-3 technical sentences on overall pipeline health",\n'
        f'  "strengths": ["concrete observation with metric reference", ...],\n'
        f'  "weaknesses": ["specific failure with root cause hypothesis", ...],\n'
        f'  "recommendations": ["prioritised, actionable engineering task", ...],\n'
        f'  "risk_level": "low" | "medium" | "high"\n'
        f"}}"
    )


class AnalysisClient:
    """Generate a textual analysis of a campaign, provider-agnostically.

    Reuses the judge factory (`build_judge_model`) so the analysis works with any
    provider (litellm / openai / ollama) selected purely by config — the same
    mechanism as metric scoring, but with its own `ModelConfiguration` so the
    analysis model can differ from the scoring model.
    """

    def __init__(self, config: ModelConfiguration) -> None:
        self._config: ModelConfiguration = config
        self._model = build_judge_model(config)

    async def analyze(
        self,
        campaign_name: str,
        profile: str,
        verdict: str,
        total_cases: int,
        passed_cases: int,
        failed_cases: int,
        metric_averages: dict[str, float],
        cases: list[CaseDetail],
    ) -> str:
        prompt = _build_prompt(
            campaign_name=campaign_name,
            profile=profile,
            verdict=verdict,
            total_cases=total_cases,
            passed_cases=passed_cases,
            failed_cases=failed_cases,
            metric_averages=metric_averages,
            cases=cases,
        )
        logger.info(
            "[ANALYSIS] calling judge model provider=%s name=%s prompt_chars=%d",
            self._config.provider,
            self._config.name,
            len(prompt),
        )

        # DeepEval models return (output, cost); we only need the text. The prompt
        # already instructs the model to return a single JSON object.
        output, _cost = await self._model.a_generate(prompt)
        text = output if isinstance(output, str) else str(output)
        logger.info("[ANALYSIS] raw model output (%d chars): %r", len(text), text[:300])
        return _extract_json_object(text)
