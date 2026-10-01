"""Structured JSON-lines logging per service, with rotation, outside the repository.

Log records carry `chat_id`, `task_id`, and `event_id` when passed through `extra=`.
Never log request headers, API keys, or tokens.
"""

import json
import logging
import logging.handlers
import pathlib
from datetime import UTC, datetime

CONTEXT_FIELDS = ("chat_id", "task_id", "event_id", "project_id")


class JsonLineFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "service": self._service,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for name in CONTEXT_FIELDS:
            value = getattr(record, name, None)
            if value is not None:
                entry[name] = value
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def configure_logging(service: str, directory: pathlib.Path, level: str = "INFO", *, console: bool = True) -> None:
    """Send the root logger to a rotating file (10 MB x 5) and, unless `console` is off, to stderr.

    A program with its own terminal output for people (the launcher) turns the console copy off.
    """
    formatter = JsonLineFormatter(service)
    handlers: list[logging.Handler] = [
        logging.handlers.RotatingFileHandler(
            directory / f"{service}.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
    ]
    if console:
        handlers.append(logging.StreamHandler())
    for handler in handlers:
        handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers[:] = handlers
    root.setLevel(level.upper())
    # httpx logs full URLs at INFO; keep it quiet.
    logging.getLogger("httpx").setLevel(logging.WARNING)
