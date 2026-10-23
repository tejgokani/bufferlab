"""Structured (key=value) logging to a rotating file.

Logging never goes to stderr/stdout: the TUI owns the terminal.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

from bufferlab.utils.paths import log_path

_configured = False


class _KeyValueFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = (
            f"ts={self.formatTime(record, '%Y-%m-%dT%H:%M:%S')} level={record.levelname} "
            f"logger={record.name} msg={record.getMessage()!r}"
        )
        extra = getattr(record, "fields", None)
        if extra:
            base += " " + " ".join(f"{k}={v!r}" for k, v in extra.items())
        if record.exc_info:
            base += " exc=" + repr(self.formatException(record.exc_info))
        return base


def get_logger(name: str = "bufferlab") -> logging.Logger:
    global _configured
    logger = logging.getLogger("bufferlab")
    if not _configured:
        _configured = True
        logger.setLevel(os.environ.get("BUFFERLAB_LOG", "INFO").upper())
        try:
            handler: logging.Handler = RotatingFileHandler(
                log_path(), maxBytes=512_000, backupCount=2, encoding="utf-8"
            )
            handler.setFormatter(_KeyValueFormatter())
            logger.addHandler(handler)
        except OSError:
            logger.addHandler(logging.NullHandler())
        logger.propagate = False
    return logger if name == "bufferlab" else logger.getChild(name)


def log_event(logger: logging.Logger, msg: str, **fields: object) -> None:
    logger.info(msg, extra={"fields": fields})
