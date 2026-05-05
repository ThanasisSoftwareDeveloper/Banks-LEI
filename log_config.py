"""
Structured JSON logging for FindLEI.
In production every log line is a JSON object → parseable by Loki/Datadog/ELK.
In development it stays human-readable (set LOG_FORMAT=text).
"""

import json
import logging
import os
import sys
import time
from typing import Any, Dict


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record."""

    LEVEL_MAP = {
        logging.DEBUG:    "debug",
        logging.INFO:     "info",
        logging.WARNING:  "warning",
        logging.ERROR:    "error",
        logging.CRITICAL: "critical",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "ts":      time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level":   self.LEVEL_MAP.get(record.levelno, "info"),
            "logger":  record.name,
            "msg":     record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # Merge any extra kwargs passed via logger.info("...", extra={...})
        for key, val in record.__dict__.items():
            if key not in (
                "msg", "args", "levelname", "levelno", "pathname", "filename",
                "module", "exc_info", "exc_text", "stack_info", "lineno",
                "funcName", "created", "msecs", "relativeCreated", "thread",
                "threadName", "processName", "process", "name", "message",
            ):
                payload[key] = val
        return json.dumps(payload, default=str)


def setup_logging() -> None:
    """
    Configure root logger.
    LOG_LEVEL env var controls verbosity (default: INFO).
    LOG_FORMAT=text → human-readable; anything else → JSON (default in prod).
    """
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level      = getattr(logging, level_name, logging.INFO)
    fmt        = os.getenv("LOG_FORMAT", "json").lower()

    handler = logging.StreamHandler(sys.stdout)

    if fmt == "text":
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
    else:
        handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Silence noisy third-party loggers
    for noisy in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
