"""Explicit outbound-authentication types for calls to the Control Plane.

RFC EVAL-AUTH requires two never-conflated identities:
- interactive API requests act as the caller (their bearer token, verbatim),
- asynchronous worker requests act as the worker's own M2M service identity.

`OutboundAuth` is a closed, discriminated union that every Control Plane call
must pass explicitly, so no call site can silently default to one identity or
the other. There is no default in `ControlPlaneClient` — this is deliberate:
an ambiguous "no auth specified" case must not be a spelling of M2M.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request


@dataclass(frozen=True)
class UserAuthentication:
    """Propagate the interactive caller's bearer token, verbatim.

    `authorization_header` is the raw `Authorization` header value (e.g.
    ``"Bearer eyJ..."``), never persisted, never logged, and scoped to a
    single request — it must not be stored on any long-lived object.
    """

    authorization_header: str


@dataclass(frozen=True)
class ServiceAuthentication:
    """Use the worker's own M2M service identity (Keycloak client-credentials)."""


@dataclass(frozen=True)
class NoAuthentication:
    """Explicit no-credentials outbound call — local dev with user security disabled.

    Distinct from `ServiceAuthentication` so dev-mode traffic can never be
    mistaken for (or silently upgraded to) the worker's service identity.
    """


OutboundAuth = UserAuthentication | ServiceAuthentication | NoAuthentication


def resolve_interactive_auth(
    request: Request, *, user_security_enabled: bool
) -> OutboundAuth:
    """Build the outbound auth for an interactive (API) request.

    - Security disabled (local dev): always `NoAuthentication` — explicit, so
      dev traffic can never be mistaken for the worker's M2M identity.
    - Security enabled: the caller's raw `Authorization` header, verbatim.

    This is only ever called from a route that also depends on fred-core's
    `get_current_user`, which FastAPI resolves first and which already rejects
    a missing/malformed header (its own `HTTPException`, normalized into this
    app's error envelope at the API boundary — see
    `evaluator_errors.normalize_unstructured_auth_error`). So by the time this
    runs with `user_security_enabled=True`, the header is guaranteed present —
    indexing it directly turns a violation of that invariant into a real
    error instead of silently manufacturing a fake one here.
    """
    if not user_security_enabled:
        return NoAuthentication()
    return UserAuthentication(authorization_header=request.headers["authorization"])
