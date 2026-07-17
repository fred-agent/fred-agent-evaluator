"""Interactive-request auth resolution (EVAL-AUTH RFC §3 / §9).

`resolve_interactive_auth` is only ever called from a route that also depends
on fred-core's `get_current_user`, which FastAPI resolves first and which
already fails closed on a missing/malformed Authorization header (normalized
into this app's error envelope at the API boundary — see
`test_auth_error_normalization.py` for that production-route proof). So this
unit only needs to lock in the two reachable branches:
- security disabled (local dev) -> explicit `NoAuthentication`, even if a
  header happens to be present (dev traffic must never look like the user's
  identity, nor the worker's M2M identity);
- security enabled -> the caller's raw Authorization header is propagated
  verbatim.
"""

from __future__ import annotations

from fastapi import Request

from fred_evaluation_backend.execution.outbound_auth import (
    NoAuthentication,
    UserAuthentication,
    resolve_interactive_auth,
)


def _request(headers: dict[str, str]) -> Request:
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    scope = {
        "type": "http",
        "headers": raw_headers,
        "method": "POST",
        "path": "/evaluations/eval-1/runs",
    }
    return Request(scope)


def test_security_disabled_always_returns_no_authentication_even_with_header():
    request = _request({"authorization": "Bearer some-user-token"})
    auth = resolve_interactive_auth(request, user_security_enabled=False)
    assert isinstance(auth, NoAuthentication)


def test_security_enabled_propagates_raw_authorization_header_verbatim():
    request = _request({"authorization": "Bearer some-user-token"})
    auth = resolve_interactive_auth(request, user_security_enabled=True)
    assert isinstance(auth, UserAuthentication)
    assert auth.authorization_header == "Bearer some-user-token"
