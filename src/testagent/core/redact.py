"""Redaction helpers so connection strings and secrets never reach logs or responses."""

from __future__ import annotations

import logging
import re

_DSN = re.compile(r"(postgres(?:ql)?(?:\+\w+)?://)([^:/@\s]+)(?::[^@\s]*)?@", re.IGNORECASE)
_KV = re.compile(r"(?i)\b(password|api_key|authorization)(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|\S+)")


def redact(text: str, secrets: tuple[str, ...] = ()) -> str:
    text = _DSN.sub(r"\1\2:***@", text)
    text = _KV.sub(lambda m: f"{m.group(1)}{m.group(2)}***", text)
    for value in secrets:
        if value:
            text = text.replace(value, "***")
    return text


def describe_dsn(dsn: str) -> str:
    """Host/port/dbname only, for status output."""
    from psycopg.conninfo import conninfo_to_dict

    try:
        parts = conninfo_to_dict(dsn)
    except Exception:
        return "invalid"
    return f"{parts.get('host', 'localhost')}:{parts.get('port', '5432')}/{parts.get('dbname', '')}"


class RedactingFilter(logging.Filter):
    def __init__(self, secrets_provider=lambda: ()):
        super().__init__()
        self._secrets = secrets_provider

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        record.msg = redact(message, tuple(self._secrets()))
        record.args = ()
        return True
