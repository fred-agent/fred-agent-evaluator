from __future__ import annotations

from fred_deepeval_cli.test_helpers import make_trace
from fred_deepeval_cli.core.scorer import _trace_to_test_case


def test_trace_to_test_case_maps_input_output_and_retrieval_context() -> None:
    trace = make_trace(
        input="What is Fred?",
        output="Fred is an agent platform.",
        retrieval_context=["Fred is an agent platform built on LangGraph."],
    )
    test_case = _trace_to_test_case(trace, expected_output="Fred is an agent platform.")
    assert test_case.input == "What is Fred?"
    assert test_case.actual_output == "Fred is an agent platform."
    assert test_case.retrieval_context == [
        "Fred is an agent platform built on LangGraph."
    ]
