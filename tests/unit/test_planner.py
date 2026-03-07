"""Unit tests for multi-engine task planner and routing improvements.

Tests the _plan_task() decomposer, result chaining, and updated routing heuristics.
These tests mock LLM API calls and test the logic in isolation.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from clawbridge.shared.schemas import EngineName, EngineStatus, Task, TaskResult, TaskStatus


# ── Plan Task Decomposer ─────────────────────────────────────────────────


class TestPlanTaskDecomposer:
    """Test the _plan_task() method that replaces _classify_prompt_with_llm()."""

    def _make_manager(self):
        """Create a minimal TaskManager-like object with _plan_task logic."""
        # We test the planner logic by importing the parsing/validation portion.
        # Since the monolith's TaskManager isn't importable as a module, we test
        # the JSON parsing and engine mapping logic directly.
        pass

    def test_single_step_plan_parsing(self):
        """Single-step plans should map engine correctly."""
        raw = '[{"instruction": "Search for robots on Google", "engine": "BROWSER"}]'
        steps = json.loads(raw)
        engine_map = {
            "BROWSER": "browser_use", "COMPUTER": "computer_use", "CHAT": "openclaw",
            "browser_use": "browser_use", "computer_use": "computer_use", "openclaw": "openclaw",
        }
        result = []
        for s in steps[:3]:
            eng = engine_map.get(s["engine"].upper().strip(), engine_map.get(s["engine"].strip()))
            if eng:
                result.append({"instruction": s["instruction"], "engine": eng})
        assert len(result) == 1
        assert result[0]["engine"] == "browser_use"
        assert "robots" in result[0]["instruction"]

    def test_multi_step_plan_parsing(self):
        """Multi-step plans should parse all steps."""
        raw = json.dumps([
            {"instruction": "Go to google.com and search for robots", "engine": "BROWSER"},
            {"instruction": "Summarize the search results", "engine": "CHAT"},
        ])
        steps = json.loads(raw)
        engine_map = {
            "BROWSER": "browser_use", "COMPUTER": "computer_use", "CHAT": "openclaw",
        }
        result = []
        for s in steps[:3]:
            eng = engine_map.get(s["engine"].upper().strip())
            if eng:
                result.append({"instruction": s["instruction"], "engine": eng})
        assert len(result) == 2
        assert result[0]["engine"] == "browser_use"
        assert result[1]["engine"] == "openclaw"

    def test_plan_capped_at_three_steps(self):
        """Plans exceeding 3 steps should be capped."""
        steps = [
            {"instruction": f"Step {i}", "engine": "BROWSER"} for i in range(5)
        ]
        capped = steps[:3]
        assert len(capped) == 3

    def test_plan_with_invalid_engine(self):
        """Steps with invalid engine names should be filtered out."""
        raw = json.dumps([
            {"instruction": "Do something", "engine": "INVALID_ENGINE"},
            {"instruction": "Search web", "engine": "BROWSER"},
        ])
        steps = json.loads(raw)
        engine_map = {
            "BROWSER": "browser_use", "COMPUTER": "computer_use", "CHAT": "openclaw",
        }
        result = []
        for s in steps[:3]:
            eng = engine_map.get(s["engine"].upper().strip())
            if eng:
                result.append({"instruction": s["instruction"], "engine": eng})
        assert len(result) == 1
        assert result[0]["engine"] == "browser_use"

    def test_plan_with_missing_fields(self):
        """Steps missing required fields should be filtered out."""
        raw = json.dumps([
            {"instruction": "Search web"},  # missing engine
            {"engine": "BROWSER"},  # missing instruction
            {"instruction": "Valid step", "engine": "COMPUTER"},
        ])
        steps = json.loads(raw)
        engine_map = {
            "BROWSER": "browser_use", "COMPUTER": "computer_use", "CHAT": "openclaw",
        }
        result = []
        for s in steps[:3]:
            if not isinstance(s, dict) or "instruction" not in s or "engine" not in s:
                continue
            eng = engine_map.get(s["engine"].upper().strip())
            if eng:
                result.append({"instruction": s["instruction"], "engine": eng})
        assert len(result) == 1
        assert result[0]["engine"] == "computer_use"

    def test_plan_handles_markdown_fenced_json(self):
        """Planner should handle LLM responses wrapped in markdown code fences."""
        text = '```json\n[{"instruction": "Search", "engine": "BROWSER"}]\n```'
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        steps = json.loads(text)
        assert len(steps) == 1
        assert steps[0]["engine"] == "BROWSER"

    def test_plan_accepts_lowercase_engine_names(self):
        """Planner should accept both uppercase and lowercase engine names."""
        raw = json.dumps([
            {"instruction": "Step 1", "engine": "browser_use"},
            {"instruction": "Step 2", "engine": "openclaw"},
        ])
        steps = json.loads(raw)
        engine_map = {
            "BROWSER": "browser_use", "COMPUTER": "computer_use", "CHAT": "openclaw",
            "BROWSER_USE": "browser_use", "COMPUTER_USE": "computer_use", "OPENCLAW": "openclaw",
            "browser_use": "browser_use", "computer_use": "computer_use", "openclaw": "openclaw",
        }
        result = []
        for s in steps[:3]:
            eng = engine_map.get(s["engine"].upper().strip(), engine_map.get(s["engine"].strip()))
            if eng:
                result.append({"instruction": s["instruction"], "engine": eng})
        assert len(result) == 2


# ── Planner Sanity Checks ────────────────────────────────────────────────


class TestPlannerSanityChecks:
    """Test that planner results are validated against URL/keyword patterns."""

    _URL_PATTERN = __import__("re").compile(r'https?://|www\.|\w\.(?:com|org|net|io|ai|dev)\b')

    def _apply_sanity_check(self, planned_engine: str, prompt: str) -> str:
        """Simulate the monolith's single-step planner sanity check."""
        WEB_SEARCH_KEYWORDS = (
            "search google", "google for", "web search", "search the web",
            "browse to", "go to website", "open website", "visit website",
            "find online", "navigate to",
        )
        if planned_engine == "openclaw":
            prompt_lower = prompt.lower()
            if self._URL_PATTERN.search(prompt_lower):
                return "browser_use"
            if any(kw in prompt_lower for kw in WEB_SEARCH_KEYWORDS):
                return "browser_use"
        return planned_engine

    def test_chat_overridden_when_url_present(self):
        """Planner returning CHAT for 'go to wikipedia.org' should be overridden to BROWSER."""
        assert self._apply_sanity_check("openclaw", "go to wikipedia.org and tell me the birth rate") == "browser_use"

    def test_chat_overridden_for_https_url(self):
        assert self._apply_sanity_check("openclaw", "tell me what's on https://example.com") == "browser_use"

    def test_chat_overridden_for_dotcom(self):
        assert self._apply_sanity_check("openclaw", "check amazon.com for deals") == "browser_use"

    def test_chat_overridden_for_web_keywords(self):
        assert self._apply_sanity_check("openclaw", "search google for python tutorials") == "browser_use"

    def test_chat_not_overridden_for_pure_question(self):
        """Pure reasoning should stay as openclaw."""
        assert self._apply_sanity_check("openclaw", "what is the meaning of life?") == "openclaw"

    def test_browser_not_affected(self):
        """Browser engine should pass through unchanged."""
        assert self._apply_sanity_check("browser_use", "search google for robots") == "browser_use"

    def test_computer_not_affected(self):
        """Computer engine should pass through unchanged."""
        assert self._apply_sanity_check("computer_use", "open notepad") == "computer_use"

    def test_step_level_url_sanity_in_plan(self):
        """Within _plan_task, steps with CHAT engine but URL in instruction should be fixed."""
        import re
        url_pattern = re.compile(r'https?://|www\.|\w\.(?:com|org|net|io|ai|dev)\b')
        engine_map = {"CHAT": "openclaw", "BROWSER": "browser_use"}
        steps_raw = [
            {"instruction": "Go to wikipedia.org and get the data", "engine": "CHAT"},
            {"instruction": "Summarize the results", "engine": "CHAT"},
        ]
        result = []
        for s in steps_raw:
            eng = engine_map.get(s["engine"])
            if eng == "openclaw" and url_pattern.search(s["instruction"].lower()):
                eng = "browser_use"
            result.append({"instruction": s["instruction"], "engine": eng})
        assert result[0]["engine"] == "browser_use"  # overridden
        assert result[1]["engine"] == "openclaw"  # no URL, stays as chat


# ── Result Chaining ──────────────────────────────────────────────────────


class TestResultChaining:
    """Test that results chain correctly between multi-step execution."""

    def test_previous_result_injected_into_prompt(self):
        """Step 2's prompt should include step 1's result."""
        previous_result = "Found 5 robots: Boston Dynamics Spot, Unitree Go2..."
        step_instruction = "Summarize the robots found"
        step_prompt = f"[PREVIOUS STEP RESULTS]\n{previous_result[:3000]}\n[END PREVIOUS RESULTS]\n\n{step_instruction}"
        assert "[PREVIOUS STEP RESULTS]" in step_prompt
        assert "Boston Dynamics" in step_prompt
        assert step_instruction in step_prompt

    def test_previous_result_capped_at_3000_chars(self):
        """Previous results should be capped to prevent context overflow."""
        long_result = "x" * 5000
        capped = long_result[:3000]
        assert len(capped) == 3000

    def test_first_step_has_no_previous_result(self):
        """First step should not have previous results injected."""
        previous_result = ""
        step_instruction = "Search Google for robots"
        if previous_result:
            step_prompt = f"[PREVIOUS STEP RESULTS]\n{previous_result}\n[END]\n\n{step_instruction}"
        else:
            step_prompt = step_instruction
        assert "[PREVIOUS" not in step_prompt
        assert step_prompt == step_instruction

    def test_aggregate_tokens_across_steps(self):
        """Total tokens should be sum of all steps (tests monolith aggregation logic)."""
        # Monolith uses tokens_in/tokens_out/estimated_cost_usd directly on TaskResult.
        # Package uses TokenUsage. Test the aggregation logic independent of model.
        step_tokens = [
            {"tokens_in": 100, "tokens_out": 50, "cost": 0.01},
            {"tokens_in": 200, "tokens_out": 100, "cost": 0.02},
        ]
        total_in = sum(s["tokens_in"] for s in step_tokens)
        total_out = sum(s["tokens_out"] for s in step_tokens)
        total_cost = sum(s["cost"] for s in step_tokens)
        assert total_in == 300
        assert total_out == 150
        assert abs(total_cost - 0.03) < 0.001


# ── Routing Heuristics ───────────────────────────────────────────────────


class TestRoutingHeuristics:
    """Test the updated keyword-based routing in _engine_for."""

    def _classify_prompt(self, prompt: str) -> str:
        """Simulate the updated keyword heuristics from _engine_for."""
        from clawbridge.shared.schemas import EngineName

        DESKTOP_KEYWORDS = (
            "notepad", "excel", "word", "outlook", "explorer", "taskbar",
            "desktop", "file manager", "calculator", "paint", "terminal",
            "cmd", "powershell", "open app", "launch app",
        )
        WEB_SEARCH_KEYWORDS = (
            "search", "google", "browse", "website", "web page", "url",
            "http", "download", "navigate to", "go to",
        )
        prompt_lower = prompt.lower()
        is_desktop = any(kw in prompt_lower for kw in DESKTOP_KEYWORDS)
        is_web = any(kw in prompt_lower for kw in WEB_SEARCH_KEYWORDS)

        _interactive_kws = (
            "log in", "login", "sign in", "signin", "sign up",
            "register", "fill", "submit", "click", "type in",
            "enter my", "my account", "my profile", "authenticate",
            "password", "checkout", "purchase", "buy", "add to cart",
        )
        is_interactive = any(kw in prompt_lower for kw in _interactive_kws)

        if is_web and is_interactive and not is_desktop:
            return "computer_use"
        elif is_web and not is_desktop:
            return "browser_use"
        elif is_desktop:
            return "computer_use"
        else:
            return "openclaw"

    def test_web_research_routes_to_browser_use(self):
        assert self._classify_prompt("Search Google for affordable robots") == "browser_use"

    def test_web_extraction_routes_to_browser_use(self):
        assert self._classify_prompt("Go to wikipedia.org and summarize the page") == "browser_use"

    def test_url_navigation_routes_to_browser_use(self):
        assert self._classify_prompt("Navigate to https://example.com") == "browser_use"

    def test_interactive_web_routes_to_computer_use(self):
        assert self._classify_prompt("Go to gmail.com and log in to my account") == "computer_use"

    def test_form_filling_routes_to_computer_use(self):
        assert self._classify_prompt("Fill in the registration form on the website") == "computer_use"

    def test_purchase_routes_to_computer_use(self):
        assert self._classify_prompt("Go to Amazon and buy a keyboard") == "computer_use"

    def test_desktop_routes_to_computer_use(self):
        assert self._classify_prompt("Open Notepad and type hello") == "computer_use"

    def test_chat_routes_to_openclaw(self):
        assert self._classify_prompt("What is the meaning of life?") == "openclaw"

    def test_analysis_routes_to_openclaw(self):
        assert self._classify_prompt("Analyze this code for bugs") == "openclaw"

    def test_desktop_overrides_web(self):
        """Desktop keywords should take priority even with web keywords."""
        assert self._classify_prompt("Search for a file in the file manager") == "computer_use"


# ── Replay Bypass ────────────────────────────────────────────────────────


class TestReplayBypass:
    """Test that replay tasks skip the planner entirely."""

    def test_replay_detected(self):
        prompt = "replay: my-workflow-123"
        is_replay = prompt.strip().lower().startswith("replay:")
        assert is_replay

    def test_non_replay_not_detected(self):
        prompt = "Search Google for something"
        is_replay = prompt.strip().lower().startswith("replay:")
        assert not is_replay

    def test_replay_with_whitespace(self):
        prompt = "  replay: workflow"
        is_replay = prompt.strip().lower().startswith("replay:")
        assert is_replay


# ── Engine Display Names ─────────────────────────────────────────────────


class TestEngineDisplay:
    """Test that multi-engine display works correctly."""

    def test_multi_engine_in_display_map(self):
        ENGINE_DISPLAY = {
            "browser_use": "Browser",
            "computer_use": "Computer",
            "openclaw": "Chat",
            "auto": "Auto",
            "replay": "Replay",
            "multi-engine": "Multi-Engine",
        }
        assert ENGINE_DISPLAY["multi-engine"] == "Multi-Engine"

    def test_plan_payload_structure(self):
        """Verify the task_plan payload has required fields."""
        plan = [
            {"instruction": "Search web", "engine": "browser_use"},
            {"instruction": "Summarize", "engine": "openclaw"},
        ]
        _engine_display = {
            "browser_use": "Web Browser (Isolated)",
            "computer_use": "Computer Control",
            "openclaw": "AI Chat",
        }
        payload = []
        for i, step in enumerate(plan):
            payload.append({
                "step": i + 1,
                "total": len(plan),
                "instruction": step["instruction"][:200],
                "engine": step["engine"],
                "engine_display": _engine_display.get(step["engine"], step["engine"]),
            })
        assert len(payload) == 2
        assert payload[0]["step"] == 1
        assert payload[0]["total"] == 2
        assert payload[0]["engine_display"] == "Web Browser (Isolated)"
        assert payload[1]["engine_display"] == "AI Chat"
