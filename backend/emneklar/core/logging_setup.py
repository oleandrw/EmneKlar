"""Structured, redacted logging.

* Every handler has the :class:`RedactingFilter`, so secrets are removed from
  the final message wherever the log call came from.
* httpx/httpcore request logging is silenced: it logs full URLs, which for
  Canvas file downloads contain signed verifiers.
* The uvicorn access log is disabled: URLs can carry the one-time launch token.
* Logs are local only (``%LOCALAPPDATA%\\EmneKlar\\logs``). No telemetry.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
from pathlib import Path

from emneklar.core.security.redaction import RedactingFilter, redact

_configured = False


class JsonFormatter(logging.Formatter):
    """One JSON object per line – easy to search and to attach to a bug report."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in ("course_id", "job_id", "change_id"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(logs_dir: Path | None, *, level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return
    _configured = True

    root = logging.getLogger()
    root.setLevel(level)
    redactor = RedactingFilter()

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S"))
    console.addFilter(redactor)
    root.addHandler(console)

    if logs_dir is not None:
        logs_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            logs_dir / "emneklar.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(JsonFormatter())
        file_handler.addFilter(redactor)
        root.addHandler(file_handler)

    for noisy in ("httpx", "httpcore", "uvicorn.access", "multipart", "keyring"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    for chatty in ("pypdf", "fontTools", "alembic.runtime.migration"):
        logging.getLogger(chatty).setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").disabled = True
