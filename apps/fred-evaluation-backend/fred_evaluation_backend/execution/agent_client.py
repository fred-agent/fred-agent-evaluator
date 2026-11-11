from __future__ import annotations

import logging

import httpx
from fred_core import M2MBearerAuth, M2MTokenProvider
from fred_sdk.contracts.eval import EvalTrace

logger = logging.getLogger(__name__)


class AgentClient:
    def __init__(self, *, timeout_seconds: int = 600) -> None:
        self._timeout = timeout_seconds

    async def evaluate(
        self,
        *,
        evaluate_url: str,
        team_id: str,
        agent_instance_id: str,
        created_by: str,
        run_id: str,
        input: str,
        token_provider: M2MTokenProvider | None = None,
    ) -> EvalTrace:
        if token_provider is None:
            raise RuntimeError(
                "Weaver evaluation requires the worker's M2M token provider."
            )
        headers = {"Content-Type": "application/json"}
        auth = M2MBearerAuth(token_provider)
        body = {
            "agent_instance_id": agent_instance_id,
            "input": input,
            "runtime_context": {
                "space_id": team_id,
                "team_id": team_id,
                "user_id": created_by,
            },
        }
        # No session_id: an existing conversation would need Control Plane validation.
        params = {"person": created_by, "run": run_id, "agent": agent_instance_id}
        logger.info(
            "[AGENT-CLIENT] POST %s instance=%s run=%s",
            evaluate_url,
            agent_instance_id,
            run_id,
        )
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                evaluate_url, headers=headers, json=body, params=params, auth=auth
            )
            response.raise_for_status()
            return EvalTrace.model_validate(response.json())
