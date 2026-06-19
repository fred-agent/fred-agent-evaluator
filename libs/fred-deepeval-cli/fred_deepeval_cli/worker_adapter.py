from __future__ import annotations

import asyncio

from fred_deepeval_cli.core.evaluator import evaluate_case_sync
from fred_deepeval_cli.core.models import EvaluationCaseRequest, EvaluationCaseResult


async def evaluate_case(
    request: EvaluationCaseRequest,
    *,
    base_url: str,
    judge=None,
    access_token: str | None = None,
) -> EvaluationCaseResult:
    return await asyncio.to_thread(
        evaluate_case_sync,
        base_url,
        request,
        judge=judge,
        access_token=access_token,
    )