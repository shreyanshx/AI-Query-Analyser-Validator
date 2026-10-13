"""Logging helpers with credential redaction.

The redaction logic scrubs passwords, connection strings, API keys, and known
sensitive keys from log messages so that database credentials and AI provider
keys can never be written to logs (CloudWatch or otherwise).
"""

from __future__ import annotations

import logging
import re

REDACTED = "***REDACTED***"

# Keys whose values must always be redacted when found in key=value or JSON form.
SENSITIVE_KEYS = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "api_key",
    "apikey",
    "access_key",
    "secret_key",
    "token",
    "authorization",
    "gemini_api_key",
    "openai_api_key",
    "anthropic_api_key",
)

# key=value or key: value or "key": "value" patterns.
_KV_PATTERN = re.compile(
    r"(?i)(\b(?:" + "|".join(SENSITIVE_KEYS) + r")\b\s*[:=]\s*)" r'("[^"]*"|\'[^\']*\'|[^\s,;)]+)'
)

# Connection strings such as postgresql://user:password@host:5432/db
_CONN_STRING_PATTERN = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://[^:/\s]+:)([^@/\s]+)(@)")

# Bearer tokens in Authorization headers.
_BEARER_PATTERN = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+")


def redact(text: str) -> str:
    """Return ``text`` with sensitive values replaced by a redaction marker."""
    if not text:
        return text
    text = _CONN_STRING_PATTERN.sub(rf"\1{REDACTED}\3", text)
    text = _BEARER_PATTERN.sub(rf"\1{REDACTED}", text)
    text = _KV_PATTERN.sub(rf"\1{REDACTED}", text)
    return text


class RedactionFilter(logging.Filter):
    """Logging filter that redacts sensitive values from formatted records."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - never let logging raise
            return True
        redacted = redact(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def configure_logging(level: int = logging.INFO) -> None:
    """Configure root logging with the redaction filter attached."""
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        root.addHandler(handler)
    redaction = RedactionFilter()
    for handler in root.handlers:
        if not any(isinstance(f, RedactionFilter) for f in handler.filters):
            handler.addFilter(redaction)


def get_logger(name: str) -> logging.Logger:
    """Return a logger that is guaranteed to redact sensitive values."""
    configure_logging()
    return logging.getLogger(name)
