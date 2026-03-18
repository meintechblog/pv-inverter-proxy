"""Structured JSON logging configuration using structlog.

All log output is structured JSON to stdout. systemd journal captures stdout
automatically. Fields: timestamp (ISO), level, event, component (when bound).
"""
from __future__ import annotations

import logging
import sys
from typing import IO

import structlog


def configure_logging(level: str = "INFO", output: IO | None = None) -> None:
    """Configure structlog for JSON output.

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR).
        output: Output stream. Defaults to sys.stdout.
    """
    out = output if output is not None else sys.stdout

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=out),
        cache_logger_on_first_use=False,
    )
