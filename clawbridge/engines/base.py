"""Abstract base class for all ClawBridge agent engines.

Every engine (browser-use, OpenClaw, future additions) implements this interface.
The orchestrator only talks to engines through this contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from clawbridge.shared.schemas import (
    EngineInfo,
    EngineName,
    EngineStatus,
    Task,
    TaskStep,
    StepResult,
)


class EngineBase(ABC):
    """Base interface for an agent engine."""

    @property
    @abstractmethod
    def name(self) -> EngineName:
        """Unique engine identifier."""
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable engine name."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Short description of the engine's capabilities."""
        ...

    @abstractmethod
    async def initialize(self) -> None:
        """Start up the engine (launch browser, connect to service, etc.).

        Called once when ClawBridge starts. Should be idempotent.
        """
        ...

    @abstractmethod
    async def execute_step(self, task: Task, step: TaskStep) -> StepResult:
        """Execute a single browsing/extraction step.

        Args:
            task: The parent task for context.
            step: The specific step to execute (navigate, extract, click, etc.).

        Returns:
            StepResult with structured extraction data.

        Raises:
            EngineError: If the step fails.
        """
        ...

    @abstractmethod
    async def run_task(self, task: Task) -> Task:
        """Execute a full task end-to-end using this engine's agent loop.

        Some engines (like browser-use) have their own planning/execution loop.
        This method lets the engine handle the full task if the orchestrator
        delegates to it.

        Args:
            task: The task to execute.

        Returns:
            Updated task with results.
        """
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully shut down the engine."""
        ...

    @abstractmethod
    async def get_status(self) -> EngineStatus:
        """Return current engine runtime status."""
        ...

    async def get_info(self) -> EngineInfo:
        """Return full engine info for the dashboard."""
        status = await self.get_status()
        return EngineInfo(
            name=self.name,
            display_name=self.display_name,
            status=status,
            description=self.description,
            capabilities=self._capabilities(),
        )

    def _capabilities(self) -> list[str]:
        """Override to declare engine capabilities."""
        return ["navigate", "extract", "summarize"]


class EngineError(Exception):
    """Raised when an engine encounters an error during execution."""

    def __init__(self, engine: EngineName, message: str, recoverable: bool = True):
        self.engine = engine
        self.message = message
        self.recoverable = recoverable
        super().__init__(f"[{engine.value}] {message}")
