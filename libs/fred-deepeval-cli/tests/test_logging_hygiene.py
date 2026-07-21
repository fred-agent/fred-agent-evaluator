"""Importing this library must not reconfigure the host application's logging.

The worker imports `core.scorer` lazily, the first time it scores a case. A previous
version silenced the root logger at import, so the worker logged normally at startup
and then went mute mid-run — which is almost certainly why debug `print()` calls had
been added to the activity: the logger was dead.
"""

from __future__ import annotations

import logging


def test_importing_the_scorer_leaves_the_root_logger_alone():
    """`logging.getLogger("root")` is the real root logger, not a private namespace.

    Setting it from a library silences every logger in the process that has not
    opted out — the host application's included.
    """
    root = logging.getLogger()
    previous = root.level
    root.setLevel(logging.INFO)
    try:
        import fred_deepeval_cli.core.scorer  # noqa: F401

        assert root.level == logging.INFO, (
            "importing the scorer changed the root logger level"
        )
        app_logger = logging.getLogger("some.host.application")
        assert app_logger.isEnabledFor(logging.INFO)
        assert app_logger.isEnabledFor(logging.ERROR)
    finally:
        root.setLevel(previous)


def test_litellm_noise_is_damped_without_hiding_failures():
    """Rate limits and retries are the signal an operator needs when a run starts
    failing; only the per-request chatter below WARNING should be suppressed."""
    import fred_deepeval_cli.core.scorer  # noqa: F401

    litellm_logger = logging.getLogger("LiteLLM")
    assert litellm_logger.isEnabledFor(logging.WARNING)
    assert litellm_logger.isEnabledFor(logging.ERROR)
    assert not litellm_logger.isEnabledFor(logging.INFO)
