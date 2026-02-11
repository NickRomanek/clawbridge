"""ClawBridge shared schemas -- the contracts between all modules."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

_UTC = timezone.utc


# ─── Enums ────────────────────────────────────────────────────────────────────


class TaskStatus(str, Enum):
    """Lifecycle states for a task."""
    PENDING = "pending"
    RUNNING = "running"
    EXTRACTING = "extracting"
    SYNTHESIZING = "synthesizing"
    COMPLETE = "complete"
    ERROR = "error"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class EngineName(str, Enum):
    """Available agent engines."""
    BROWSER_USE = "browser_use"
    OPENCLAW = "openclaw"
    AUTO = "auto"  # Let orchestrator decide


class ActionClass(str, Enum):
    """Security classification for browser actions."""
    SAFE_READ = "safe_read"           # navigate, read, extract, summarize
    SENSITIVE_WRITE = "sensitive_write"  # click submit, type in forms
    HIGH_RISK = "high_risk"           # file upload/download, clipboard, external app


class PolicyMode(str, Enum):
    """User-configured policy strictness."""
    GUARDED = "guarded"       # Prompt for sensitive + high_risk
    PERMISSIVE = "permissive" # Auto-run everything (local trust mode)
    STRICT = "strict"         # Prompt for everything except safe_read


class EngineStatus(str, Enum):
    """Runtime status of an engine."""
    AVAILABLE = "available"
    STARTING = "starting"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"
    NOT_INSTALLED = "not_installed"


# ─── Core Models ──────────────────────────────────────────────────────────────


class Task(BaseModel):
    """A user-submitted task for the agent to execute."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    prompt: str = Field(..., description="User's task description or question")
    engine: EngineName = Field(default=EngineName.AUTO, description="Which engine to use")
    status: TaskStatus = Field(default=TaskStatus.PENDING)
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=_UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=_UTC))
    result: TaskResult | None = None
    steps: list[TaskStep] = Field(default_factory=list)
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskStep(BaseModel):
    """A single step in the agent's execution plan."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    action: str = Field(..., description="Action type: navigate, extract, click, type, summarize")
    target: str = Field(default="", description="URL, selector, or description")
    action_class: ActionClass = Field(default=ActionClass.SAFE_READ)
    status: TaskStatus = Field(default=TaskStatus.PENDING)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: StepResult | None = None
    error: str | None = None


class StepResult(BaseModel):
    """Structured result from a single step execution."""
    url: str = ""
    title: str = ""
    summary: str = ""
    snippets: list[str] = Field(default_factory=list)
    fields: dict[str, Any] = Field(default_factory=dict)
    duration_ms: int = 0


class TaskResult(BaseModel):
    """Final synthesized result for a completed task."""
    summary: str = Field(..., description="LLM-synthesized response to the user's prompt")
    citations: list[Citation] = Field(default_factory=list)
    total_steps: int = 0
    total_duration_ms: int = 0
    engine_used: EngineName = EngineName.AUTO
    tokens_used: TokenUsage | None = None


class Citation(BaseModel):
    """A source reference from agent browsing."""
    url: str
    title: str = ""
    snippet: str = ""


class TokenUsage(BaseModel):
    """LLM token consumption for a task."""
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0


# ─── Engine Info ──────────────────────────────────────────────────────────────


class EngineInfo(BaseModel):
    """Status information for an agent engine."""
    name: EngineName
    display_name: str
    status: EngineStatus
    description: str = ""
    version: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    error: str | None = None


# ─── Policy ───────────────────────────────────────────────────────────────────


class PolicyDecision(BaseModel):
    """Result of the policy engine evaluating an action."""
    step_id: str
    action: str
    action_class: ActionClass
    allowed: bool
    requires_user_approval: bool = False
    reason: str = ""
    sensitive_fields_detected: list[str] = Field(default_factory=list)


# ─── Telemetry / Audit ───────────────────────────────────────────────────────


class AuditEvent(BaseModel):
    """Structured audit log entry for every action the agent takes."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=_UTC))
    task_id: str
    step_id: str | None = None
    event_type: str  # "task_created", "step_started", "step_completed", "policy_decision", etc.
    engine: EngineName | None = None
    action: str | None = None
    action_class: ActionClass | None = None
    target_url: str | None = None
    target_domain: str | None = None
    duration_ms: int | None = None
    status: str | None = None
    detail: str = ""
    redacted: bool = False


# ─── WebSocket Messages ──────────────────────────────────────────────────────


class WSMessage(BaseModel):
    """Message sent over WebSocket to dashboard."""
    type: str  # "task_update", "step_update", "audit_event", "engine_status", "approval_request"
    payload: dict[str, Any] = Field(default_factory=dict)


class ApprovalRequest(BaseModel):
    """Sent to dashboard when policy requires user approval for an action."""
    task_id: str
    step_id: str
    action: str
    action_class: ActionClass
    target: str
    reason: str


class ApprovalResponse(BaseModel):
    """User's response to an approval request."""
    step_id: str
    approved: bool
    trust_domain: bool = False  # If true, auto-approve future actions on this domain
