"""browser-use engine adapter for ClawBridge.

Wraps the browser-use library (Playwright-based AI browser automation)
behind the standard EngineBase interface.
"""

from __future__ import annotations

import asyncio
import time
import logging
from datetime import datetime
from typing import Any

from clawbridge.config import get_settings
from clawbridge.engines.base import EngineBase, EngineError
from clawbridge.shared.schemas import (
    Citation,
    EngineName,
    EngineStatus,
    StepResult,
    Task,
    TaskResult,
    TaskStatus,
    TaskStep,
    TokenUsage,
)

logger = logging.getLogger(__name__)


class BrowserUseEngine(EngineBase):
    """Agent engine powered by the browser-use library."""

    def __init__(self) -> None:
        self._status: EngineStatus = EngineStatus.STOPPED
        self._browser: Any = None
        self._agent_class: Any = None
        self._browser_class: Any = None
        self._llm: Any = None
        self.on_screenshot: Callable[[str], Any] | None = None

    @property
    def name(self) -> EngineName:
        return EngineName.BROWSER_USE

    @property
    def display_name(self) -> str:
        return "browser-use"

    @property
    def description(self) -> str:
        return "AI browser automation via Playwright. Fast structured extraction and web research."

    def _capabilities(self) -> list[str]:
        return ["navigate", "extract", "click", "type", "screenshot", "summarize"]

    async def initialize(self) -> None:
        """Import browser-use and set up the LLM provider."""
        self._status = EngineStatus.STARTING
        try:
            # Dynamic import -- browser-use is optional
            from browser_use import Agent, Browser

            self._agent_class = Agent
            self._browser_class = Browser

            # Set up LLM based on available BYOK key
            settings = get_settings()
            self._llm = self._create_llm(settings)

            # Pre-initialize browser instance
            self._browser = Browser(
                config=self._get_browser_config(settings)
            )

            self._status = EngineStatus.AVAILABLE
            logger.info("browser-use engine initialized successfully")

        except ImportError:
            self._status = EngineStatus.NOT_INSTALLED
            logger.warning(
                "browser-use not installed. Install with: pip install browser-use"
            )
        except Exception as e:
            self._status = EngineStatus.ERROR
            logger.error(f"browser-use initialization failed: {e}")

    def _create_llm(self, settings: Any) -> Any:
        """Create LLM instance from BYOK keys. Prefers Anthropic, falls back to OpenAI."""
        model = settings.default_model

        if settings.has_anthropic_key and model.startswith("claude"):
            from browser_use.llm import ChatAnthropic
            return ChatAnthropic(
                model=model,
                api_key=settings.anthropic_api_key,
            )
        elif settings.has_openrouter_key:
            from browser_use.llm import ChatOpenRouter
            return ChatOpenRouter(
                model=model,
                api_key=settings.openrouter_api_key,
            )
        elif settings.has_openai_key:
            from browser_use.llm import ChatOpenAI
            return ChatOpenAI(
                model=model if model.startswith("gpt") else "gpt-4o",
                api_key=settings.openai_api_key,
            )
        else:
            raise EngineError(
                EngineName.BROWSER_USE,
                "No API key configured. Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or OPENROUTER_API_KEY in .env",
                recoverable=False,
            )

    def _get_browser_config(self, settings: Any) -> Any:
        """Build browser-use Browser config."""
        from browser_use import BrowserConfig

        return BrowserConfig(
            headless=settings.browser_headless,
            disable_security=True,
            new_context_config={
                "viewport": {"width": 1280, "height": 720},
                "record_video_size": {"width": 1280, "height": 720},
            }
        )

    async def execute_step(self, task: Task, step: TaskStep) -> StepResult:
        """Execute a single step using browser-use.

        For simple actions, we create a micro-task and run the agent.
        """
        if self._status != EngineStatus.AVAILABLE:
            raise EngineError(
                EngineName.BROWSER_USE,
                f"Engine not available (status: {self._status.value})",
            )

        start_time = time.monotonic()

        try:
            # Build a focused micro-prompt for this step
            micro_prompt = self._step_to_prompt(step)

            agent = self._agent_class(
                task=micro_prompt,
                llm=self._llm,
                browser=self._browser,
            )

            history = await agent.run(max_steps=5)

            duration_ms = int((time.monotonic() - start_time) * 1000)

            # Extract structured result from agent history
            return self._extract_step_result(history, duration_ms)

        except Exception as e:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.error(f"browser-use step failed: {e}")
            raise EngineError(EngineName.BROWSER_USE, str(e))

    async def run_task(self, task: Task) -> Task:
        """Run a full task using browser-use's built-in agent loop."""
        if self._status != EngineStatus.AVAILABLE:
            raise EngineError(
                EngineName.BROWSER_USE,
                f"Engine not available (status: {self._status.value})",
            )

        self._status = EngineStatus.RUNNING
        start_time = time.monotonic()

        try:
            settings = get_settings()

            async def step_callback(state: Any):
                if self.on_screenshot and state.results and state.results[-1].extracted_content:
                    # browser-use captures screenshots in history
                    # We can try to get it from the last state
                    if hasattr(state, 'screenshot') and state.screenshot:
                        self.on_screenshot(state.screenshot)

            agent = self._agent_class(
                task=task.prompt,
                llm=self._llm,
                browser=self._browser,
            )

            # Run the agent with configurable step limit
            max_steps = min(settings.max_actions_per_task, 50)
            history = await agent.run(max_steps=max_steps, step_callback=step_callback)

            duration_ms = int((time.monotonic() - start_time) * 1000)

            # Build task result from agent history
            task.result = self._build_task_result(history, duration_ms)
            task.status = TaskStatus.COMPLETE
            task.updated_at = datetime.utcnow()

            logger.info(
                f"Task {task.id} completed via browser-use in {duration_ms}ms"
            )

        except Exception as e:
            task.status = TaskStatus.ERROR
            task.error = str(e)
            task.updated_at = datetime.utcnow()
            logger.error(f"Task {task.id} failed: {e}")

        finally:
            self._status = EngineStatus.AVAILABLE

        return task

    def _step_to_prompt(self, step: TaskStep) -> str:
        """Convert a TaskStep into a browser-use prompt."""
        action = step.action.lower()
        target = step.target

        if action == "navigate":
            return f"Navigate to {target} and extract the main content."
        elif action == "extract":
            return f"On the current page, extract: {target}"
        elif action == "click":
            return f"Click on the element: {target}"
        elif action == "type":
            return f"Type the following text: {target}"
        elif action == "summarize":
            return f"Summarize the content of the current page, focusing on: {target}"
        else:
            return f"{action}: {target}"

    def _extract_step_result(self, history: Any, duration_ms: int) -> StepResult:
        """Extract a StepResult from browser-use agent history."""
        try:
            # browser-use history contains the final result and action history
            final_result = history.final_result() if callable(getattr(history, 'final_result', None)) else str(history)

            # Try to get the last URL from history
            url = ""
            title = ""
            if hasattr(history, 'urls') and history.urls:
                url = history.urls[-1] if history.urls else ""
            if hasattr(history, 'action_results'):
                for ar in reversed(history.action_results or []):
                    if hasattr(ar, 'extracted_content') and ar.extracted_content:
                        title = ar.extracted_content[:100]
                        break

            return StepResult(
                url=url,
                title=title,
                summary=str(final_result)[:2000],  # Cap summary length
                snippets=[str(final_result)[:500]],
                duration_ms=duration_ms,
            )
        except Exception as e:
            logger.warning(f"Error extracting step result: {e}")
            return StepResult(
                summary=f"Step completed but result extraction failed: {e}",
                duration_ms=duration_ms,
            )

    def _build_task_result(self, history: Any, duration_ms: int) -> TaskResult:
        """Build a full TaskResult from browser-use agent history."""
        try:
            final_result = history.final_result() if callable(getattr(history, 'final_result', None)) else str(history)

            # Collect citations from browsed URLs
            citations = []
            if hasattr(history, 'urls'):
                for url in (history.urls or []):
                    citations.append(Citation(url=url))

            # Estimate token usage (browser-use tracks this internally)
            tokens = None
            if hasattr(history, 'total_input_tokens'):
                tokens = TokenUsage(
                    input_tokens=getattr(history, 'total_input_tokens', 0),
                    output_tokens=getattr(history, 'total_output_tokens', 0),
                )

            return TaskResult(
                summary=str(final_result)[:5000],
                citations=citations,
                total_steps=len(history.action_results) if hasattr(history, 'action_results') else 0,
                total_duration_ms=duration_ms,
                engine_used=EngineName.BROWSER_USE,
                tokens_used=tokens,
            )
        except Exception as e:
            logger.warning(f"Error building task result: {e}")
            return TaskResult(
                summary=f"Task completed but result extraction failed: {e}",
                total_duration_ms=duration_ms,
                engine_used=EngineName.BROWSER_USE,
            )

    async def stop(self) -> None:
        """Shut down the browser-use engine and close browser."""
        try:
            if self._browser:
                await self._browser.close()
                self._browser = None
        except Exception as e:
            logger.warning(f"Error closing browser-use browser: {e}")
        finally:
            self._status = EngineStatus.STOPPED
            logger.info("browser-use engine stopped")

    async def get_status(self) -> EngineStatus:
        return self._status
