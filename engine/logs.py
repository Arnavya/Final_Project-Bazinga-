"""Process-wide logging to stdout.

Containers and Kubernetes collect stdout, so that is the only sink. LOG_FORMAT=json emits one
JSON object per line (for `kubectl logs ... | jq`); the default `text` stays readable locally.

Usage:
    from engine.logs import get_logger, log_event
    log = get_logger(__name__)
    log_event(log, "ask.completed", latency_ms=812, grounded=True)
"""
from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any

from engine import config

_CONFIGURED = False
_RESERVED = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """One JSON object per line; extra fields passed via `extra=` are merged in."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
                  + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "version": config.APP_VERSION,
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class TextFormatter(logging.Formatter):
    """Human-readable line with the extra fields appended as key=value."""

    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s: %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = {k: v for k, v in record.__dict__.items()
                  if k not in _RESERVED and not k.startswith("_")}
        if extras:
            base += " " + " ".join(f"{k}={v}" for k, v in extras.items())
        return base


def configure() -> None:
    """Attach a single stdout handler to the root logger (idempotent)."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if config.LOG_FORMAT == "json" else TextFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(getattr(logging, config.LOG_LEVEL, logging.INFO))
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    configure()
    return logging.getLogger(name)


def log_event(logger: logging.Logger, event: str, level: int = logging.INFO, **fields: Any) -> None:
    """Log a named event with structured fields."""
    logger.log(level, event, extra={"event": event, **fields})
