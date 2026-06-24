from __future__ import annotations

import logging

import httpx
from fred_core import M2MBearerAuth, M2MTokenProvider
from fred_sdk.contracts.eval import EvalTrace
from fred_sdk.contracts.execution import ExecutionGrant

logger = logging.getLogger(__name__)


class AgentClient:
    def __init__(self, *, timeout_seconds: int = 600) -> None:
        self._timeout = timeout_seconds

    async def evaluate(
        self,
        *,
        evaluate_url: str,
        execution_grant: ExecutionGrant,
        agent_id: str | None,
        agent_instance_id: str | None = None,
        session_id: str,
        input: str,
        token_provider: M2MTokenProvider | None = None,
    ) -> EvalTrace:
        token = execution_grant.model_dump_json()
        headers = {
            "Content-Type": "application/json",
            "X-Execution-Grant": token,
        }
        # When M2M is configured the bearer token is injected by M2MBearerAuth;
        # otherwise fall back to a dev token (local stacks run agents without auth).
        auth = M2MBearerAuth(token_provider) if token_provider else None
        if auth is None:
            headers["Authorization"] = "Bearer dev"
        body: dict = {
            "session_id": session_id,
            "input": input,
            "execution_grant": execution_grant.model_dump(),
        }
        if agent_instance_id:
            body["agent_instance_id"] = agent_instance_id
        elif agent_id:
            body["agent_id"] = agent_id
        logger.info(
            "[AGENT-CLIENT] POST %s agent=%s session=%s",
            evaluate_url,
            agent_id,
            session_id,
        )
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                evaluate_url, headers=headers, json=body, auth=auth
            )
            response.raise_for_status()
            return EvalTrace.model_validate(response.json())
