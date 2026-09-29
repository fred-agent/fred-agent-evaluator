"""Catalog of built-in metric ids selectable on a run.

Deliberately dependency-free (no `fred_deepeval_cli`, no `deepeval`): this
module is imported by the API layer, which never installs the `scoring`
extra (see `dockerfiles/Dockerfile-api`). The worker maps these same ids to
DeepEval metric classes in `fred_deepeval_cli.core.scorer`.
"""

from __future__ import annotations

BUILTIN_METRIC_IDS: frozenset[str] = frozenset(
    {
        "answer_relevancy",
        "faithfulness",
        "contextual_relevancy",
        "contextual_precision",
        "contextual_recall",
    }
)

# Scored against `expected_output`: on a case without one they are reported
# `skipped`, so they only make sense on a `complete` evaluation.
EXPECTED_OUTPUT_METRIC_IDS: frozenset[str] = frozenset(
    {"contextual_precision", "contextual_recall"}
)
