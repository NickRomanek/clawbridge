"""Tests for clawbridge.shared.schemas -- model validation, enums, serialization."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from pydantic import ValidationError

from clawbridge.shared.schemas import (
    ActionClass,
    ApprovalRequest,
    ApprovalResponse,
    AuditEvent,
    Citation,
    EngineInfo,
    EngineName,
    EngineStatus,
    PolicyDecision,
    PolicyMode,
    StepResult,
    Task,
    TaskResult,
    TaskStatus,
    TaskStep,
    TokenUsage,
    WSMessage,
)


# ── Enum Tests ───────────────────────────────────────────────────────────────


class TestTaskStatus:
    def test_all_values_present(self):
        expected = {"pending", "running", "extracting", "synthesizing",
                    "complete", "error", "paused", "cancelled"}
        assert {s.value for s in TaskStatus} == expected

    def test_string_coercion(self):
        assert TaskStatus("pending") == TaskStatus.PENDING
        assert TaskStatus("error") == TaskStatus.ERROR

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            TaskStatus("invalid")


class TestEngineName:
    def test_all_values(self):
        assert {e.value for e in EngineName} == {"browser_use", "computer_use", "openclaw", "auto"}

    def test_auto_is_default_for_task(self):
        task = Task(prompt="test")
        assert task.engine == EngineName.AUTO


class TestActionClass:
    def test_all_values(self):
        assert {a.value for a in ActionClass} == {"safe_read", "sensitive_write", "high_risk"}


class TestPolicyMode:
    def test_all_values(self):
        assert {p.value for p in PolicyMode} == {"guarded", "permissive", "strict"}


class TestEngineStatus:
    def test_all_values(self):
        expected = {"available", "starting", "running", "stopped", "error", "not_installed"}
        assert {s.value for s in EngineStatus} == expected


# ── Task Model ───────────────────────────────────────────────────────────────


class TestTask:
    def test_default_creation(self):
        task = Task(prompt="Research AI agents")
        assert task.prompt == "Research AI agents"
        assert task.status == TaskStatus.PENDING
        assert task.engine == EngineName.AUTO
        assert task.result is None
        assert task.steps == []
        assert task.error is None
        assert task.metadata == {}

    def test_id_is_uuid(self):
        task = Task(prompt="test")
        uuid.UUID(task.id)  # Raises if not valid UUID

    def test_unique_ids(self):
        t1 = Task(prompt="test1")
        t2 = Task(prompt="test2")
        assert t1.id != t2.id

    def test_created_at_is_set(self):
        task = Task(prompt="test")
        assert isinstance(task.created_at, datetime)

    def test_prompt_required(self):
        with pytest.raises(ValidationError):
            Task()  # No prompt

    def test_explicit_engine(self):
        task = Task(prompt="test", engine=EngineName.BROWSER_USE)
        assert task.engine == EngineName.BROWSER_USE

    def test_explicit_status(self):
        task = Task(prompt="test", status=TaskStatus.RUNNING)
        assert task.status == TaskStatus.RUNNING

    def test_metadata_dict(self):
        task = Task(prompt="test", metadata={"source": "api", "priority": 1})
        assert task.metadata["source"] == "api"
        assert task.metadata["priority"] == 1

    def test_json_serialization(self):
        task = Task(prompt="test")
        data = task.model_dump(mode="json")
        assert isinstance(data, dict)
        assert data["prompt"] == "test"
        assert data["status"] == "pending"
        assert data["engine"] == "auto"

    def test_json_round_trip(self):
        task = Task(prompt="test", engine=EngineName.OPENCLAW)
        data = task.model_dump(mode="json")
        restored = Task(**data)
        assert restored.prompt == task.prompt
        assert restored.id == task.id
        assert restored.engine == task.engine


# ── TaskStep Model ───────────────────────────────────────────────────────────


class TestTaskStep:
    def test_default_creation(self):
        step = TaskStep(action="navigate")
        assert step.action == "navigate"
        assert step.target == ""
        assert step.action_class == ActionClass.SAFE_READ
        assert step.status == TaskStatus.PENDING
        assert step.started_at is None
        assert step.completed_at is None
        assert step.result is None
        assert step.error is None

    def test_with_target(self):
        step = TaskStep(action="navigate", target="https://example.com")
        assert step.target == "https://example.com"

    def test_action_required(self):
        with pytest.raises(ValidationError):
            TaskStep()

    def test_id_is_uuid(self):
        step = TaskStep(action="click")
        uuid.UUID(step.id)

    def test_explicit_action_class(self):
        step = TaskStep(action="click", action_class=ActionClass.SENSITIVE_WRITE)
        assert step.action_class == ActionClass.SENSITIVE_WRITE

    def test_json_serialization(self):
        step = TaskStep(action="extract", target="main content")
        data = step.model_dump(mode="json")
        assert data["action"] == "extract"
        assert data["target"] == "main content"
        assert data["action_class"] == "safe_read"


# ── StepResult Model ─────────────────────────────────────────────────────────


class TestStepResult:
    def test_default_creation(self):
        result = StepResult()
        assert result.url == ""
        assert result.title == ""
        assert result.summary == ""
        assert result.snippets == []
        assert result.fields == {}
        assert result.duration_ms == 0

    def test_with_data(self):
        result = StepResult(
            url="https://example.com",
            title="Example",
            summary="A test page",
            snippets=["snippet1", "snippet2"],
            fields={"author": "test"},
            duration_ms=150,
        )
        assert result.url == "https://example.com"
        assert len(result.snippets) == 2
        assert result.fields["author"] == "test"
        assert result.duration_ms == 150


# ── TaskResult Model ─────────────────────────────────────────────────────────


class TestTaskResult:
    def test_creation(self):
        result = TaskResult(summary="AI agents are useful for automation")
        assert result.summary == "AI agents are useful for automation"
        assert result.citations == []
        assert result.total_steps == 0
        assert result.total_duration_ms == 0
        assert result.engine_used == EngineName.AUTO
        assert result.tokens_used is None

    def test_summary_required(self):
        with pytest.raises(ValidationError):
            TaskResult()

    def test_with_citations(self):
        result = TaskResult(
            summary="test",
            citations=[Citation(url="https://example.com", title="Example")],
        )
        assert len(result.citations) == 1
        assert result.citations[0].url == "https://example.com"

    def test_with_token_usage(self):
        result = TaskResult(
            summary="test",
            tokens_used=TokenUsage(input_tokens=100, output_tokens=50, estimated_cost_usd=0.002),
        )
        assert result.tokens_used.input_tokens == 100
        assert result.tokens_used.estimated_cost_usd == 0.002


# ── Citation Model ───────────────────────────────────────────────────────────


class TestCitation:
    def test_url_required(self):
        with pytest.raises(ValidationError):
            Citation()

    def test_defaults(self):
        c = Citation(url="https://example.com")
        assert c.title == ""
        assert c.snippet == ""

    def test_full_citation(self):
        c = Citation(url="https://example.com", title="Example", snippet="Some text")
        assert c.title == "Example"


# ── TokenUsage Model ─────────────────────────────────────────────────────────


class TestTokenUsage:
    def test_defaults(self):
        t = TokenUsage()
        assert t.input_tokens == 0
        assert t.output_tokens == 0
        assert t.estimated_cost_usd == 0.0

    def test_with_values(self):
        t = TokenUsage(input_tokens=500, output_tokens=200, estimated_cost_usd=0.01)
        assert t.input_tokens == 500


# ── EngineInfo Model ─────────────────────────────────────────────────────────


class TestEngineInfo:
    def test_required_fields(self):
        info = EngineInfo(
            name=EngineName.BROWSER_USE,
            display_name="browser-use",
            status=EngineStatus.AVAILABLE,
        )
        assert info.name == EngineName.BROWSER_USE
        assert info.description == ""
        assert info.version is None
        assert info.capabilities == []
        assert info.error is None

    def test_missing_required_raises(self):
        with pytest.raises(ValidationError):
            EngineInfo(name=EngineName.BROWSER_USE)  # missing display_name and status


# ── PolicyDecision Model ─────────────────────────────────────────────────────


class TestPolicyDecision:
    def test_creation(self):
        pd = PolicyDecision(
            step_id="step-1",
            action="navigate",
            action_class=ActionClass.SAFE_READ,
            allowed=True,
            reason="Auto-approved",
        )
        assert pd.allowed is True
        assert pd.requires_user_approval is False
        assert pd.sensitive_fields_detected == []

    def test_with_sensitive_fields(self):
        pd = PolicyDecision(
            step_id="step-1",
            action="type",
            action_class=ActionClass.HIGH_RISK,
            allowed=False,
            requires_user_approval=True,
            reason="Password field detected",
            sensitive_fields_detected=["password_field", "credential_pattern"],
        )
        assert pd.allowed is False
        assert len(pd.sensitive_fields_detected) == 2


# ── AuditEvent Model ─────────────────────────────────────────────────────────


class TestAuditEvent:
    def test_minimal_creation(self):
        event = AuditEvent(task_id="task-1", event_type="task_created")
        assert event.task_id == "task-1"
        assert event.event_type == "task_created"
        assert isinstance(event.timestamp, datetime)
        uuid.UUID(event.id)

    def test_full_creation(self):
        event = AuditEvent(
            task_id="task-1",
            step_id="step-1",
            event_type="step_completed",
            engine=EngineName.BROWSER_USE,
            action="navigate",
            action_class=ActionClass.SAFE_READ,
            target_url="https://example.com",
            target_domain="example.com",
            duration_ms=250,
            status="complete",
            detail="Navigated successfully",
        )
        assert event.engine == EngineName.BROWSER_USE
        assert event.duration_ms == 250

    def test_json_serialization(self):
        event = AuditEvent(task_id="t1", event_type="test")
        data = event.model_dump(mode="json")
        assert isinstance(data["timestamp"], str)
        assert data["task_id"] == "t1"


# ── WSMessage Model ──────────────────────────────────────────────────────────


class TestWSMessage:
    def test_creation(self):
        msg = WSMessage(type="task_update", payload={"id": "123", "status": "running"})
        assert msg.type == "task_update"
        assert msg.payload["id"] == "123"

    def test_empty_payload(self):
        msg = WSMessage(type="ping")
        assert msg.payload == {}


# ── ApprovalRequest / Response ───────────────────────────────────────────────


class TestApprovalRequest:
    def test_creation(self):
        req = ApprovalRequest(
            task_id="t1",
            step_id="s1",
            action="click",
            action_class=ActionClass.SENSITIVE_WRITE,
            target="Submit button",
            reason="Form submission detected",
        )
        assert req.action_class == ActionClass.SENSITIVE_WRITE

    def test_required_fields(self):
        with pytest.raises(ValidationError):
            ApprovalRequest(task_id="t1")  # missing other required fields


class TestApprovalResponse:
    def test_approve(self):
        resp = ApprovalResponse(step_id="s1", approved=True)
        assert resp.approved is True
        assert resp.trust_domain is False

    def test_approve_and_trust(self):
        resp = ApprovalResponse(step_id="s1", approved=True, trust_domain=True)
        assert resp.trust_domain is True

    def test_deny(self):
        resp = ApprovalResponse(step_id="s1", approved=False)
        assert resp.approved is False
