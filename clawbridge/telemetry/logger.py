"""ClawBridge telemetry and audit logging.

Structured JSON logging for every action the agent takes.
All logs stay local. Sensitive content is redacted before writing.
"""

from __future__ import annotations

import json
import logging
import sys
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

from clawbridge.config import get_settings
from clawbridge.policy.safety import redact_sensitive_content
from clawbridge.shared.schemas import AuditEvent

logger = logging.getLogger(__name__)


class AuditLogger:
    """Structured audit logger that writes JSON events to file and keeps a ring buffer.

    The ring buffer provides the live activity feed for the dashboard.
    The file log provides the persistent audit trail.
    """

    def __init__(self, max_buffer_size: int = 500):
        self._buffer: deque[AuditEvent] = deque(maxlen=max_buffer_size)
        self._log_file: Path | None = None
        self._subscribers: list[Any] = []  # WebSocket subscribers

    def initialize(self) -> None:
        """Set up the log file."""
        settings = get_settings()
        self._log_file = settings.log_dir / "audit.jsonl"
        logger.info(f"Audit log: {self._log_file}")

    def log_event(self, event: AuditEvent) -> None:
        """Log an audit event. Redacts sensitive content before writing."""
        # Redact sensitive content in the detail field
        if event.detail:
            event.detail = redact_sensitive_content(event.detail)

        # Add to ring buffer (for live feed)
        self._buffer.append(event)

        # Write to file
        if self._log_file:
            try:
                with open(self._log_file, "a") as f:
                    f.write(event.model_dump_json() + "\n")
            except Exception as e:
                logger.warning(f"Failed to write audit log: {e}")

        # Notify WebSocket subscribers
        for callback in self._subscribers:
            try:
                callback(event)
            except Exception:
                pass

    def get_recent_events(self, limit: int = 50, task_id: str | None = None) -> list[AuditEvent]:
        """Get recent events from the ring buffer, optionally filtered by task."""
        events = list(self._buffer)
        if task_id:
            events = [e for e in events if e.task_id == task_id]
        return events[-limit:]

    def subscribe(self, callback: Any) -> None:
        """Register a callback for real-time event notifications (WebSocket)."""
        self._subscribers.append(callback)

    def unsubscribe(self, callback: Any) -> None:
        """Remove a callback."""
        try:
            self._subscribers.remove(callback)
        except ValueError:
            pass


# Singleton
_audit_logger: AuditLogger | None = None


def get_audit_logger() -> AuditLogger:
    """Get or create the global audit logger."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
        _audit_logger.initialize()
    return _audit_logger


def setup_logging() -> None:
    """Configure application-wide logging.

    - Structured format for file output.
    - Human-readable format for console.
    - BYOK keys are excluded from all log output by the config.__repr__ override.
    """
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    # Console handler (human-readable)
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%H:%M:%S",
        )
    )

    # File handler (JSON-ish structured)
    log_file = settings.log_dir / "clawbridge.log"
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(level)
    file_handler.setFormatter(
        logging.Formatter(
            '{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )

    # Root logger
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(console)
    root.addHandler(file_handler)

    # Suppress noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
