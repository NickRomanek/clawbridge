"""Shared fixtures for ClawBridge tests."""

from __future__ import annotations

import os
import pytest

# Ensure no real .env keys leak into tests
os.environ.setdefault("ANTHROPIC_API_KEY", "")
os.environ.setdefault("OPENAI_API_KEY", "")


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset module-level singletons between tests so state doesn't leak."""
    import clawbridge.config as cfg_mod
    import clawbridge.orchestrator.manager as mgr_mod
    import clawbridge.telemetry.logger as log_mod

    cfg_mod._settings = None
    mgr_mod._task_manager = None
    log_mod._audit_logger = None
    yield
    cfg_mod._settings = None
    mgr_mod._task_manager = None
    log_mod._audit_logger = None


@pytest.fixture
def sample_task():
    """Create a minimal Task for testing."""
    from clawbridge.shared.schemas import Task
    return Task(prompt="Search for Python best practices")


@pytest.fixture
def sample_step():
    """Create a minimal TaskStep for testing."""
    from clawbridge.shared.schemas import TaskStep
    return TaskStep(action="navigate", target="https://example.com")
