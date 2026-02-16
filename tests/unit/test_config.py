"""Tests for clawbridge.config -- settings loading, properties, key detection."""

from __future__ import annotations

import os

import pytest

from clawbridge.shared.schemas import EngineName, PolicyMode


class TestSettings:
    """Test the Settings class and its properties."""

    def _make_settings(self, **env_overrides):
        """Create a Settings instance with custom env vars."""
        for k, v in env_overrides.items():
            os.environ[k] = v
        try:
            from clawbridge.config import Settings
            return Settings()
        finally:
            for k in env_overrides:
                os.environ.pop(k, None)

    def test_default_host_and_port(self):
        s = self._make_settings()
        assert s.host == "127.0.0.1"
        assert s.port == 8765

    def test_custom_host_and_port(self):
        s = self._make_settings(CLAWBRIDGE_HOST="0.0.0.0", CLAWBRIDGE_PORT="9000")
        assert s.host == "0.0.0.0"
        assert s.port == 9000

    def test_default_policy_mode(self):
        s = self._make_settings()
        assert s.policy_mode == PolicyMode.GUARDED

    def test_custom_policy_mode(self):
        s = self._make_settings(POLICY_MODE="strict")
        assert s.policy_mode == PolicyMode.STRICT

    def test_default_max_concurrent_tasks(self):
        s = self._make_settings()
        assert s.max_concurrent_tasks == 3

    def test_default_max_actions_per_task(self):
        s = self._make_settings()
        assert s.max_actions_per_task == 50

    def test_default_browser_headless(self):
        s = self._make_settings()
        assert s.browser_headless is True

    def test_default_log_retention(self):
        s = self._make_settings()
        assert s.log_retention_hours == 72

    def test_default_log_level(self):
        s = self._make_settings()
        assert s.log_level == "INFO"

    def test_default_enabled_engines(self):
        s = self._make_settings()
        assert s.enabled_engines == "browser_use,computer_use,openclaw"


class TestKeyDetection:
    """Test API key presence detection properties."""

    def _make_settings(self, **env_overrides):
        for k, v in env_overrides.items():
            os.environ[k] = v
        try:
            from clawbridge.config import Settings
            return Settings()
        finally:
            for k in env_overrides:
                os.environ.pop(k, None)

    def test_no_keys_by_default(self):
        s = self._make_settings(ANTHROPIC_API_KEY="", OPENAI_API_KEY="", OPENROUTER_API_KEY="")
        assert s.has_anthropic_key is False
        assert s.has_openai_key is False
        assert s.has_any_key is False

    def test_anthropic_key_present(self):
        s = self._make_settings(ANTHROPIC_API_KEY="sk-ant-test123")
        assert s.has_anthropic_key is True
        assert s.has_any_key is True

    def test_openai_key_present(self):
        s = self._make_settings(OPENAI_API_KEY="sk-test123")
        assert s.has_openai_key is True
        assert s.has_any_key is True

    def test_both_keys_present(self):
        s = self._make_settings(ANTHROPIC_API_KEY="sk-ant-x", OPENAI_API_KEY="sk-y")
        assert s.has_anthropic_key is True
        assert s.has_openai_key is True
        assert s.has_any_key is True


class TestEnabledEngineList:
    """Test the enabled_engine_list property parsing."""

    def _make_settings(self, **env_overrides):
        for k, v in env_overrides.items():
            os.environ[k] = v
        try:
            from clawbridge.config import Settings
            return Settings()
        finally:
            for k in env_overrides:
                os.environ.pop(k, None)

    def test_default_engines(self):
        s = self._make_settings()
        engines = s.enabled_engine_list
        assert EngineName.BROWSER_USE in engines
        assert EngineName.OPENCLAW in engines

    def test_single_engine(self):
        s = self._make_settings(ENABLED_ENGINES="browser_use")
        engines = s.enabled_engine_list
        assert engines == [EngineName.BROWSER_USE]

    def test_invalid_engine_ignored(self):
        s = self._make_settings(ENABLED_ENGINES="browser_use,invalid_engine")
        engines = s.enabled_engine_list
        assert EngineName.BROWSER_USE in engines
        assert len(engines) == 1

    def test_empty_engines(self):
        s = self._make_settings(ENABLED_ENGINES="")
        engines = s.enabled_engine_list
        assert engines == []

    def test_whitespace_handling(self):
        s = self._make_settings(ENABLED_ENGINES=" browser_use , openclaw ")
        engines = s.enabled_engine_list
        assert EngineName.BROWSER_USE in engines
        assert EngineName.OPENCLAW in engines


class TestReprSafety:
    """Test that repr never leaks API keys."""

    def _make_settings(self, **env_overrides):
        for k, v in env_overrides.items():
            os.environ[k] = v
        try:
            from clawbridge.config import Settings
            return Settings()
        finally:
            for k in env_overrides:
                os.environ.pop(k, None)

    def test_repr_does_not_contain_api_keys(self):
        s = self._make_settings(
            ANTHROPIC_API_KEY="sk-ant-supersecret123",
            OPENAI_API_KEY="sk-opensecret456",
        )
        r = repr(s)
        assert "supersecret" not in r
        assert "opensecret" not in r
        assert "has_anthropic_key=True" in r
        assert "has_openai_key=True" in r

    def test_repr_without_keys(self):
        s = self._make_settings(ANTHROPIC_API_KEY="", OPENAI_API_KEY="")
        r = repr(s)
        assert "has_anthropic_key=False" in r
        assert "has_openai_key=False" in r


class TestSingleton:
    """Test the singleton pattern for settings."""

    def test_get_settings_returns_same_instance(self):
        from clawbridge.config import get_settings
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_reload_settings_returns_new_instance(self):
        from clawbridge.config import get_settings, reload_settings
        s1 = get_settings()
        s2 = reload_settings()
        assert s1 is not s2
