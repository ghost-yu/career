from __future__ import annotations

import json
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from app.core.config import settings


class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "time": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
        }
        message = record.getMessage()
        if isinstance(message, str):
            try:
                parsed = json.loads(message)
                if isinstance(parsed, dict):
                    payload.update(parsed)
                else:
                    payload["message"] = message
            except Exception:
                payload["message"] = message
        else:
            payload["message"] = str(message)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _ensure_parent(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def _build_handler(path: str) -> RotatingFileHandler:
    _ensure_parent(path)
    handler = RotatingFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    handler.setFormatter(JsonLineFormatter())
    return handler


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if getattr(root, "_career_logging_ready", False):
        return

    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(JsonLineFormatter())
    root.addHandler(console)
    root.addHandler(_build_handler(settings.app_log_path))

    audit_logger = logging.getLogger("llm.audit")
    audit_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    audit_logger.handlers.clear()
    audit_logger.addHandler(_build_handler(settings.llm_audit_log_path))
    audit_logger.propagate = True

    root._career_logging_ready = True  # type: ignore[attr-defined]


_audit_logger = logging.getLogger("llm.audit")


def emit_audit_event(event: dict[str, Any]) -> None:
    _audit_logger.info(json.dumps(event, ensure_ascii=False))
