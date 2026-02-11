"""Tests for clawbridge.telemetry.logger -- audit events, ring buffer, redaction."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from clawbridge.shared.schemas import AuditEvent, EngineName
from clawbridge.telemetry.logger import AuditLogger


@pytest.fixture
def audit_logger(tmp_path):
    """Create an AuditLogger that writes to a temp directory."""
    logger = AuditLogger(max_buffer_size=10)
    logger._log_file = tmp_path / "audit.jsonl"
    return logger


@pytest.fixture
def sample_event():
    return AuditEvent(task_id="task-1", event_type="task_created", detail="Test event")


# ── Ring Buffer ──────────────────────────────────────────────────────────────


class TestRingBuffer:
    def test_event_added_to_buffer(self, audit_logger, sample_event):
        audit_logger.log_event(sample_event)
        events = audit_logger.get_recent_events()
        assert len(events) == 1
        assert events[0].task_id == "task-1"

    def test_buffer_respects_max_size(self, tmp_path):
        logger = AuditLogger(max_buffer_size=3)
        logger._log_file = tmp_path / "audit.jsonl"

        for i in range(5):
            logger.log_event(
                AuditEvent(task_id=f"task-{i}", event_type="test")
            )

        events = logger.get_recent_events()
        assert len(events) == 3
        # Should contain the last 3 events
        assert events[0].task_id == "task-2"
        assert events[1].task_id == "task-3"
        assert events[2].task_id == "task-4"

    def test_get_recent_with_limit(self, audit_logger):
        for i in range(5):
            audit_logger.log_event(
                AuditEvent(task_id=f"task-{i}", event_type="test")
            )

        events = audit_logger.get_recent_events(limit=2)
        assert len(events) == 2
        # Should return the last 2
        assert events[0].task_id == "task-3"
        assert events[1].task_id == "task-4"

    def test_filter_by_task_id(self, audit_logger):
        audit_logger.log_event(AuditEvent(task_id="task-a", event_type="created"))
        audit_logger.log_event(AuditEvent(task_id="task-b", event_type="created"))
        audit_logger.log_event(AuditEvent(task_id="task-a", event_type="completed"))

        events = audit_logger.get_recent_events(task_id="task-a")
        assert len(events) == 2
        assert all(e.task_id == "task-a" for e in events)

    def test_filter_by_nonexistent_task_id(self, audit_logger, sample_event):
        audit_logger.log_event(sample_event)
        events = audit_logger.get_recent_events(task_id="nonexistent")
        assert events == []


# ── File Persistence ─────────────────────────────────────────────────────────


class TestFilePersistence:
    def test_writes_to_file(self, audit_logger, sample_event):
        audit_logger.log_event(sample_event)
        assert audit_logger._log_file.exists()

        content = audit_logger._log_file.read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 1

        data = json.loads(lines[0])
        assert data["task_id"] == "task-1"

    def test_appends_multiple_events(self, audit_logger):
        for i in range(3):
            audit_logger.log_event(
                AuditEvent(task_id=f"task-{i}", event_type="test")
            )

        content = audit_logger._log_file.read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 3

    def test_no_crash_if_no_log_file(self):
        logger = AuditLogger()
        logger._log_file = None
        # Should not raise
        logger.log_event(AuditEvent(task_id="t1", event_type="test"))
        events = logger.get_recent_events()
        assert len(events) == 1


# ── Redaction ────────────────────────────────────────────────────────────────


class TestRedaction:
    def test_redacts_credential_in_detail(self, audit_logger):
        event = AuditEvent(
            task_id="t1",
            event_type="test",
            detail="Found password=supersecret123 in page",
        )
        audit_logger.log_event(event)

        events = audit_logger.get_recent_events()
        assert "supersecret123" not in events[0].detail
        assert "[REDACTED_CREDENTIAL]" in events[0].detail

    def test_redacts_api_key_in_detail(self, audit_logger):
        event = AuditEvent(
            task_id="t1",
            event_type="test",
            detail="api_key=abc123xyz",
        )
        audit_logger.log_event(event)

        events = audit_logger.get_recent_events()
        assert "abc123xyz" not in events[0].detail

    def test_preserves_clean_detail(self, audit_logger):
        event = AuditEvent(
            task_id="t1",
            event_type="test",
            detail="Task completed successfully",
        )
        audit_logger.log_event(event)

        events = audit_logger.get_recent_events()
        assert events[0].detail == "Task completed successfully"

    def test_empty_detail_not_redacted(self, audit_logger):
        event = AuditEvent(task_id="t1", event_type="test", detail="")
        audit_logger.log_event(event)

        events = audit_logger.get_recent_events()
        assert events[0].detail == ""


# ── Subscribers ──────────────────────────────────────────────────────────────


class TestSubscribers:
    def test_subscriber_notified(self, audit_logger, sample_event):
        callback = MagicMock()
        audit_logger.subscribe(callback)
        audit_logger.log_event(sample_event)

        callback.assert_called_once()
        received_event = callback.call_args[0][0]
        assert received_event.task_id == "task-1"

    def test_multiple_subscribers(self, audit_logger, sample_event):
        cb1 = MagicMock()
        cb2 = MagicMock()
        audit_logger.subscribe(cb1)
        audit_logger.subscribe(cb2)
        audit_logger.log_event(sample_event)

        cb1.assert_called_once()
        cb2.assert_called_once()

    def test_unsubscribe(self, audit_logger, sample_event):
        callback = MagicMock()
        audit_logger.subscribe(callback)
        audit_logger.unsubscribe(callback)
        audit_logger.log_event(sample_event)

        callback.assert_not_called()

    def test_unsubscribe_nonexistent_no_error(self, audit_logger):
        callback = MagicMock()
        # Should not raise
        audit_logger.unsubscribe(callback)

    def test_failing_subscriber_does_not_break_logging(self, audit_logger, sample_event):
        bad_callback = MagicMock(side_effect=RuntimeError("callback failed"))
        good_callback = MagicMock()

        audit_logger.subscribe(bad_callback)
        audit_logger.subscribe(good_callback)
        audit_logger.log_event(sample_event)

        # Good callback still receives the event despite bad one failing
        good_callback.assert_called_once()
        # Event still in buffer
        assert len(audit_logger.get_recent_events()) == 1
