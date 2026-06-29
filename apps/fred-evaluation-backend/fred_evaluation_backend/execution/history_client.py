"""HTTP client that reads an agent's conversation history from the runtime.

Why this client is different from `agent_client` / `control_plane_client`:
- those call the runtime in **M2M** (service token), from the background worker.
- capture is **interactive** (a user triggers the import and waits), so we propagate
  the **caller's JWT** instead — the runtime then authorizes via ReBAC on the user's
  team (no service authorization needed). See EVAL-DATASET backlog Phase 2.

The response shape mirrors the runtime's `CapturePage` (frozen in fred #1874). We model
it locally rather than importing from fred-core, because the deployed fred-core release
does not ship the capture reader yet — and parsing into our own model keeps the two
services decoupled across the HTTP boundary.
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Safety bound: never loop more than this many pages for a single capture, so a
# misbehaving cursor cannot spin forever.
_MAX_PAGES = 200


class CapturedMessage(BaseModel):
    session_id: str
    user_id: str
    exchange_id: str | None = None
    role: str
    content: str
    timestamp: datetime


class CapturePage(BaseModel):
    messages: list[CapturedMessage]
    next_cursor: str | None = None


class HistoryClient:
    """Reads `GET /agents/{agent_instance_id}/history`, propagating the user JWT."""

    def __init__(self, *, runtime_base_url: str, timeout_seconds: int = 60) -> None:
        # runtime_base_url is the runtime host + path prefix that mounts the agent
        # routes (e.g. http://localhost:8000/pod/v1). The route is `/agents/...`.
        self._base_url = runtime_base_url.rstrip("/")
        self._timeout = timeout_seconds

    async def fetch_page(
        self,
        *,
        agent_instance_id: str,
        team_id: str,
        period_from: datetime,
        period_to: datetime,
        bearer_token: str | None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> CapturePage:
        """Fetch a single page of history messages from the runtime."""
        url = f"{self._base_url}/agents/{agent_instance_id}/history"
        params: dict[str, str | int] = {
            "team_id": team_id,
            "period_from": period_from.isoformat(),
            "period_to": period_to.isoformat(),
            "limit": limit,
        }
        if cursor is not None:
            params["cursor"] = cursor
        # Propagate the caller's JWT so the runtime authorizes the real user (ReBAC).
        headers = {"Authorization": bearer_token} if bearer_token else {}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            return CapturePage.model_validate(response.json())

    async def fetch_all(
        self,
        *,
        agent_instance_id: str,
        team_id: str,
        period_from: datetime,
        period_to: datetime,
        bearer_token: str | None,
        page_limit: int = 100,
        max_messages: int | None = None,
    ) -> list[CapturedMessage]:
        """Stream all pages (following the cursor) into a flat message list.

        `max_messages` caps the total captured, mirroring the server-side bounding.
        """
        out: list[CapturedMessage] = []
        cursor: str | None = None
        for _ in range(_MAX_PAGES):
            page = await self.fetch_page(
                agent_instance_id=agent_instance_id,
                team_id=team_id,
                period_from=period_from,
                period_to=period_to,
                bearer_token=bearer_token,
                cursor=cursor,
                limit=page_limit,
            )
            out.extend(page.messages)
            if max_messages is not None and len(out) >= max_messages:
                return out[:max_messages]
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
        return out
