from __future__ import annotations

from fred_core import M2MAuthConfig, M2MTokenProvider, SecurityConfiguration


def build_m2m_token_provider(
    security: SecurityConfiguration,
) -> M2MTokenProvider | None:
    """Build a Keycloak client-credentials token provider for outbound M2M calls.

    Returns ``None`` when M2M is disabled. Weaver evaluation requires a real
    service identity: AgentClient fails before sending a request in that case.
    """
    m2m = security.m2m
    if not m2m.enabled:
        return None
    return M2MTokenProvider(
        M2MAuthConfig(
            keycloak_realm_url=str(m2m.realm_url),
            client_id=m2m.client_id,
            secret_env=m2m.secret_env_var,
        )
    )
