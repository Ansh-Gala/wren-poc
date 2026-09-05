"""Logging with credential redaction.

Benchmark logs are meant to be pasted into reports and issues, so no formatter
here may ever emit a password. Secrets are registered once at startup and
scrubbed from every record, including exception text.
"""

from __future__ import annotations

import logging
import sys

_SECRETS: list[str] = []
_CONFIGURED = False


def register_secrets(values: list[str]) -> None:
    """Register values that must never appear in log output."""
    for v in values:
        if v and v not in _SECRETS:
            _SECRETS.append(v)


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        for secret in _SECRETS:
            if secret in text:
                text = text.replace(secret, "***")
        return text


def get_logger(name: str, debug: bool = False) -> logging.Logger:
    global _CONFIGURED
    if not _CONFIGURED:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(RedactingFormatter("%(levelname)-7s %(name)s | %(message)s"))
        root = logging.getLogger("wrenpoc")
        root.addHandler(handler)
        root.propagate = False
        _CONFIGURED = True
    logger = logging.getLogger(f"wrenpoc.{name}")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    return logger
