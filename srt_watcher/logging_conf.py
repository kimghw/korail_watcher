from __future__ import annotations

import json
import logging
import logging.config
from pathlib import Path

class StructuredFormatter(logging.Formatter):
    """Formatter that tolerates missing ``extra`` payloads."""

    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        extra_value = getattr(record, "extra", "")
        formatted_extra = ""
        if isinstance(extra_value, dict):
            try:
                rendered = json.dumps(extra_value, ensure_ascii=False, sort_keys=True)
            except (TypeError, ValueError):
                rendered = str(extra_value)
            formatted_extra = f" | {rendered}"
        elif extra_value:
            formatted_extra = f" | {extra_value}"

        record.__dict__["extra"] = formatted_extra
        return super().format(record)


def build_logging_dict(log_dir: Path, level: str) -> dict:
    log_file = log_dir / "srt_watcher.log"
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "console": {
                "format": "%(asctime)s %(levelname)s %(name)s: %(message)s",
            },
            "structured": {
                "()": "srt_watcher.logging_conf.StructuredFormatter",
                "format": "%(asctime)s %(levelname)s %(name)s %(message)s%(extra)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": level,
                "formatter": "console",
            },
            "rotating_file": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": level,
                "formatter": "structured",
                "filename": str(log_file),
                "maxBytes": 10 * 1024 * 1024,
                "backupCount": 5,
                "encoding": "utf-8",
            },
        },
        "root": {
            "level": level,
            "handlers": ["console", "rotating_file"],
        },
    }


def configure_logging(log_dir: Path, level: str) -> None:
    """
    Initialize logging using dictConfig.

    Creates the log directory if missing, builds the dictConfig from logging_config.py,
    and applies it. `level` may be "INFO", "DEBUG", etc. (case-insensitive).
    """
    # Ensure directory exists
    log_dir.mkdir(parents=True, exist_ok=True)

    # Normalize level (e.g., "info" -> "INFO")
    level_str = str(level).upper()

    # Build and apply configuration
    cfg = build_logging_dict(log_dir, level_str)
    logging.config.dictConfig(cfg)


__all__ = ["configure_logging", "StructuredFormatter", "build_logging_dict"]