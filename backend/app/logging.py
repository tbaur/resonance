# Copyright (c) 2026 tbaur
#
# Licensed under the Apache License, Version 2.0
# See LICENSE file for full license text

"""Structured JSON logging with request correlation support."""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get("-"),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        for key in (
            "device_id",
            "device_ip",
            "op",
            "duration_ms",
            "outcome",
            "http_method",
            "http_path",
            "http_status",
            "action",
            "succeeded",
            "failed",
            "role",
            "target_count",
            "skipped_muted",
            "scoped",
            "redirect_host",
            "url",
            "failure_kind",
            "failure_detail",
        ):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload, default=str)


# uvicorn installs plain-text handlers on these loggers and stops them propagating.
# Removing those handlers sends uvicorn's lines through the JSON root handler too.
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)
    for name in _UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    # The middleware writes its own http_request line for every request.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("zeroconf").setLevel(logging.WARNING)
