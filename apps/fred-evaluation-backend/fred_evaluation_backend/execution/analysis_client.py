from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

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

    cases_section = "\n".join(case_lines) if case_lines else "  No case details available."

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
        f'{{\n'
        f'  "summary": "2-3 technical sentences on overall pipeline health",\n'
        f'  "strengths": ["concrete observation with metric reference", ...],\n'
        f'  "weaknesses": ["specific failure with root cause hypothesis", ...],\n'
        f'  "recommendations": ["prioritised, actionable engineering task", ...],\n'
        f'  "risk_level": "low" | "medium" | "high"\n'
        f'}}'
    )


class AnalysisClient:
    def __init__(self, api_key: str, model: str, base_url: str) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")

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
        logger.info("[ANALYSIS] calling Mistral model=%s prompt_chars=%d", self._model, len(prompt))

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
