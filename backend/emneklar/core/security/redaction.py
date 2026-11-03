"""Redaction of secrets from anything that may be logged or shown.

Two layers:

* pattern-based redaction of things that *look* like credentials
  (Authorization headers, bearer tokens, Canvas tokens, provider API keys,
  signed download URLs);
* exact-value redaction of every secret EmneKlar has loaded from the
  credential store (registered via :func:`register_secret`).
"""

from __future__ import annotations

import logging
import re
import threading

_lock = threading.Lock()
_known_secrets: set[str] = set()

REDACTED = "[SKJULT]"

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Authorization: Bearer xyz / api-key: xyz / x-api-key: xyz
    (
        re.compile(
            r"(?i)(authorization|x-api-key|api-key|proxy-authorization)(\"?\s*[:=]\s*\"?)[^\s\",}]+(\s+[^\s\",}]+)?"
        ),
        r"\1\2" + REDACTED,
    ),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"), "Bearer " + REDACTED),
    # Canvas access tokens: "<digits>~<long alnum>"
    (re.compile(r"\b\d{1,8}~[A-Za-z0-9]{20,}\b"), REDACTED),
    # Anthropic / OpenAI style keys
    (re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{16,}\b"), REDACTED),
    # Canvas file verifiers and other signed query parameters
    (
        re.compile(
            r"(?i)([?&](?:verifier|access_token|sig|signature|x-amz-signature|x-amz-credential|token|api-key|key)=)"
            r"[^&\s\"']+"
        ),
        r"\1" + REDACTED,
    ),
]


def register_secret(value: str | None) -> None:
    """Remember a secret value so it is redacted wherever it appears."""
    if value and len(value) >= 6:
        with _lock:
            _known_secrets.add(value)


def unregister_secret(value: str | None) -> None:
    if value:
        with _lock:
            _known_secrets.discard(value)


def known_secrets() -> list[str]:
    with _lock:
        return list(_known_secrets)


def redact(text: str) -> str:
    if not text:
        return text
    for secret in known_secrets():
        if secret in text:
            text = text.replace(secret, REDACTED)
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def contains_secret(text: str) -> bool:
    """True if ``text`` contains a registered secret or a credential-like string."""
    if not text:
        return False
    if any(secret in text for secret in known_secrets()):
        return True
    return any(pattern.search(text) for pattern, _ in _PATTERNS[1:4])


class RedactingFilter(logging.Filter):
    """Logging filter that redacts secrets from the final formatted message."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - logging must never crash the app
            return True
        redacted = redact(message)
        if record.exc_info and record.exc_info[1] is not None:
            exc = record.exc_info[1]
            exc.args = tuple(redact(str(a)) if isinstance(a, str) else a for a in exc.args)
        if redacted != message:
            record.msg = redacted
            record.args = None
        return True
