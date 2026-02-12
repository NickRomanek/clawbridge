"""ClawBridge safety policy engine.

Classifies actions, detects sensitive fields, redacts credentials,
and decides whether to auto-run or prompt the user.

Design principle: safe enough for unattended local use, not so restrictive
that it blocks normal research workflows.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from clawbridge.config import get_settings
from clawbridge.shared.schemas import (
    ActionClass,
    PolicyDecision,
    PolicyMode,
    TaskStep,
)

logger = logging.getLogger(__name__)


# ─── Patterns for sensitive content detection ─────────────────────────────────

# Credential patterns (never extract or return these)
CREDENTIAL_PATTERNS = [
    re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*\S+"),
    re.compile(r"(?i)(api[_-]?key|apikey|secret[_-]?key)\s*[:=]\s*\S+"),
    re.compile(r"(?i)(access[_-]?token|auth[_-]?token|bearer)\s*[:=]\s*\S+"),
    re.compile(r"(?i)(private[_-]?key)\s*[:=]\s*\S+"),
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),  # OpenAI-style keys
    re.compile(r"sk-ant-[a-zA-Z0-9-]{20,}"),  # Anthropic-style keys
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),  # GitHub personal access tokens
    re.compile(r"xox[bsapr]-[a-zA-Z0-9-]+"),  # Slack tokens
]

# Sensitive PII patterns
PII_PATTERNS = [
    re.compile(r"\b\d{3}[-.]?\d{2}[-.]?\d{4}\b"),  # SSN
    re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"),  # Credit card
]

# Password input selectors (HTML patterns that indicate credential fields)
PASSWORD_FIELD_INDICATORS = [
    'type="password"',
    "type='password'",
    'autocomplete="current-password"',
    'autocomplete="new-password"',
    "name=\"password\"",
    "name=\"passwd\"",
    "name=\"pwd\"",
]

# Domains that always trigger sensitive_write or higher
SENSITIVE_DOMAINS = {
    "accounts.google.com",
    "login.microsoftonline.com",
    "github.com/login",
    "signin.aws.amazon.com",
    "console.cloud.google.com",
}

# Domains that always trigger high_risk
HIGH_RISK_DOMAINS = {
    "bank", "banking", "paypal.com", "venmo.com",
    "stripe.com/dashboard",
}


# ─── Classification ──────────────────────────────────────────────────────────


def classify_action(step: TaskStep) -> ActionClass:
    """Classify a task step into an action security class.

    Rules:
    - navigate, read, extract, summarize -> safe_read
    - click submit, type in forms -> sensitive_write
    - file upload/download, clipboard, external app -> high_risk
    - Any action targeting a sensitive domain -> bumped up one level
    - Any action involving password fields -> high_risk
    """
    action = step.action.lower()
    target = step.target.lower()

    # Start with base classification
    if action in ("navigate", "read", "extract", "summarize", "screenshot"):
        action_class = ActionClass.SAFE_READ
    elif action in ("click", "type", "submit", "select"):
        action_class = ActionClass.SENSITIVE_WRITE
    elif action in ("upload", "download", "clipboard", "exec", "launch"):
        action_class = ActionClass.HIGH_RISK
    # Computer-use actions: full desktop control is always high-risk
    elif action in ("mouse_move", "left_click", "right_click", "double_click",
                    "left_click_drag", "cursor_position", "desktop_screenshot",
                    "key_press", "desktop_type", "computer_action"):
        action_class = ActionClass.HIGH_RISK
    else:
        # Unknown action -> treat as sensitive
        action_class = ActionClass.SENSITIVE_WRITE

    # Bump up if targeting sensitive domain
    domain = _extract_domain(target)
    if domain and _is_high_risk_domain(domain):
        action_class = ActionClass.HIGH_RISK
    elif domain and _is_sensitive_domain(domain):
        if action_class == ActionClass.SAFE_READ:
            action_class = ActionClass.SENSITIVE_WRITE

    # Bump to high_risk if password field detected
    if _has_password_indicators(target):
        action_class = ActionClass.HIGH_RISK

    return action_class


def evaluate_policy(step: TaskStep) -> PolicyDecision:
    """Evaluate whether a step should be auto-run or requires user approval.

    Returns a PolicyDecision with the allow/prompt verdict.
    """
    settings = get_settings()
    action_class = classify_action(step)
    step.action_class = action_class  # Update the step with classification

    # Detect sensitive content in the target
    sensitive_fields = detect_sensitive_content(step.target)

    # Determine policy based on mode
    mode = settings.policy_mode

    if mode == PolicyMode.PERMISSIVE:
        # Trust mode: auto-run everything locally
        return PolicyDecision(
            step_id=step.id,
            action=step.action,
            action_class=action_class,
            allowed=True,
            requires_user_approval=False,
            reason="Permissive mode -- all actions auto-approved",
            sensitive_fields_detected=sensitive_fields,
        )

    elif mode == PolicyMode.STRICT:
        # Strict mode: only safe_read auto-runs
        needs_approval = action_class != ActionClass.SAFE_READ
        return PolicyDecision(
            step_id=step.id,
            action=step.action,
            action_class=action_class,
            allowed=not needs_approval,
            requires_user_approval=needs_approval,
            reason=(
                "Auto-approved (safe read)"
                if not needs_approval
                else f"Requires approval: {action_class.value} action in strict mode"
            ),
            sensitive_fields_detected=sensitive_fields,
        )

    else:
        # Guarded mode (default): safe_read auto-runs, others prompt
        needs_approval = action_class in (
            ActionClass.SENSITIVE_WRITE,
            ActionClass.HIGH_RISK,
        )

        # If sensitive content detected, always prompt regardless of action class
        if sensitive_fields:
            needs_approval = True

        return PolicyDecision(
            step_id=step.id,
            action=step.action,
            action_class=action_class,
            allowed=not needs_approval,
            requires_user_approval=needs_approval,
            reason=(
                "Auto-approved (safe read, no sensitive content)"
                if not needs_approval
                else f"Requires approval: {action_class.value}"
                + (f" + sensitive fields: {sensitive_fields}" if sensitive_fields else "")
            ),
            sensitive_fields_detected=sensitive_fields,
        )


# ─── Content Scanning ────────────────────────────────────────────────────────


def detect_sensitive_content(text: str) -> list[str]:
    """Scan text for credential patterns, API keys, PII.

    Returns list of detected pattern types (never the actual values).
    """
    detected = []

    for pattern in CREDENTIAL_PATTERNS:
        if pattern.search(text):
            detected.append("credential_pattern")
            break

    for pattern in PII_PATTERNS:
        if pattern.search(text):
            detected.append("pii_pattern")
            break

    if _has_password_indicators(text):
        detected.append("password_field")

    return detected


def redact_sensitive_content(text: str) -> str:
    """Redact credentials and PII from text before logging or returning.

    Replaces matches with [REDACTED] while preserving surrounding context.
    """
    result = text

    for pattern in CREDENTIAL_PATTERNS:
        result = pattern.sub("[REDACTED_CREDENTIAL]", result)

    for pattern in PII_PATTERNS:
        result = pattern.sub("[REDACTED_PII]", result)

    return result


# ─── Prompt Injection Defense ─────────────────────────────────────────────────


PROMPT_INJECTION_PATTERNS = [
    re.compile(r"(?i)ignore\s+(previous|above|all)\s+(instructions?|prompts?|rules?)"),
    re.compile(r"(?i)you\s+are\s+now\s+"),
    re.compile(r"(?i)system\s*:\s*"),
    re.compile(r"(?i)forget\s+(everything|all|your)\s+"),
    re.compile(r"(?i)disregard\s+(previous|above|all)\s+"),
    re.compile(r"(?i)new\s+instructions?\s*:"),
    re.compile(r"(?i)override\s+(previous|system)\s+"),
]


def scan_for_prompt_injection(text: str) -> list[str]:
    """Scan extracted web content for prompt injection attempts.

    Returns list of detected injection pattern descriptions.
    Does NOT block -- just flags for the orchestrator to handle.
    """
    detected = []

    for pattern in PROMPT_INJECTION_PATTERNS:
        if pattern.search(text):
            detected.append(f"injection_pattern: {pattern.pattern[:50]}")

    return detected


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _extract_domain(text: str) -> str:
    """Extract domain from a URL or text containing a URL."""
    try:
        if "://" in text:
            return urlparse(text).netloc.lower()
        elif "." in text and " " not in text.split(".")[0]:
            return text.split("/")[0].lower()
    except Exception:
        pass
    return ""


def _is_sensitive_domain(domain: str) -> bool:
    """Check if domain is in the sensitive list."""
    return any(sd in domain for sd in SENSITIVE_DOMAINS)


def _is_high_risk_domain(domain: str) -> bool:
    """Check if domain matches high-risk patterns."""
    return any(hrd in domain for hrd in HIGH_RISK_DOMAINS)


def _has_password_indicators(text: str) -> bool:
    """Check if text contains password field HTML indicators."""
    text_lower = text.lower()
    return any(indicator in text_lower for indicator in PASSWORD_FIELD_INDICATORS)
