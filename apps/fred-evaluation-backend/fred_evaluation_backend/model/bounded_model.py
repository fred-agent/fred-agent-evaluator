"""DeepEval's LiteLLM model, with its call wrapper replaced by our `CallPolicy`.

DeepEval 4 runs each call through its own retry layer (none for LiteLLM) and a
per-attempt deadline thread that would also count our rate-cap waits. The public
methods call the transport methods directly, under our policy instead.
"""

from __future__ import annotations

from typing import override

from deepeval.models.llms import LiteLLMModel
from pydantic import BaseModel

from fred_evaluation_backend.model.judge_calls import CallPolicy

# The return shapes of DeepEval's own methods: (output, cost).
Generated = tuple[str | BaseModel, float | None]
Raw = tuple[object, float | None]


class BoundedLiteLLMModel(LiteLLMModel):
    def __init__(
        self,
        *,
        call_policy: CallPolicy,
        model: str,
        api_key: str | None,
        base_url: str | None,
        request_timeout: float,
    ) -> None:
        # num_retries=0: our policy owns retries, LiteLLM must not add its own.
        super().__init__(
            model=model,
            api_key=api_key,
            base_url=base_url,
            request_timeout=request_timeout,
            num_retries=0,
        )
        self._call_policy: CallPolicy = call_policy

    @override
    def generate(self, prompt: str, schema: BaseModel | None = None) -> Generated:
        return self._call_policy.call(lambda: self._generate(prompt, schema))

    @override
    async def a_generate(
        self, prompt: str, schema: BaseModel | None = None
    ) -> Generated:
        return await self._call_policy.acall(lambda: self._a_generate(prompt, schema))

    @override
    def generate_raw_response(self, prompt: str, top_logprobs: int = 5) -> Raw:
        return self._call_policy.call(
            lambda: self._generate_raw_response(prompt, top_logprobs)
        )

    @override
    async def a_generate_raw_response(self, prompt: str, top_logprobs: int = 5) -> Raw:
        return await self._call_policy.acall(
            lambda: self._a_generate_raw_response(prompt, top_logprobs)
        )
