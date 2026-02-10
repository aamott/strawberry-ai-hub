"""Logging configuration utilities for the Hub."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path


DEFAULT_LOG_FILENAME = "hub.log"


ANSI_RESET = "\x1b[0m"
ANSI_COLORS = {
    logging.DEBUG: "\x1b[36m",
    logging.INFO: "\x1b[32m",
    logging.WARNING: "\x1b[33m",
    logging.ERROR: "\x1b[31m",
    logging.CRITICAL: "\x1b[35m",
}


def _purge_old_logs(log_dir: Path, log_file: Path, retention_days: int) -> int:
    """Remove rotated log files that exceed the retention window.

    Args:
        log_dir: Directory containing log files.
        log_file: Active log file path.
        retention_days: Maximum number of days to keep rotated logs.

    Returns:
        The number of files removed.
    """
    if retention_days <= 0:
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    removed = 0
    for path in log_dir.glob(f"{log_file.name}*"):
        if path == log_file:
            continue
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if mtime < cutoff:
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
    return removed


class CleanupRotatingFileHandler(RotatingFileHandler):
    """Rotating file handler with periodic retention cleanup."""

    def __init__(
        self,
        filename: Path,
        max_bytes: int,
        retention_days: int,
        cleanup_interval_seconds: int = 3600,
    ) -> None:
        super().__init__(
            filename,
            maxBytes=max_bytes,
            backupCount=1000,
            encoding="utf-8",
        )
        self._retention_days = retention_days
        self._cleanup_interval_seconds = cleanup_interval_seconds
        self._last_cleanup_ts = 0.0

    def emit(self, record: logging.LogRecord) -> None:
        """Emit a log record and purge old logs periodically.

        Args:
            record: The log record to emit.
        """
        now = time.time()
        if (
            self._retention_days > 0
            and now - self._last_cleanup_ts >= self._cleanup_interval_seconds
        ):
            self._last_cleanup_ts = now
            _purge_old_logs(
                Path(self.baseFilename).parent,
                Path(self.baseFilename),
                self._retention_days,
            )
        super().emit(record)


class ColorFormatter(logging.Formatter):
    """Formatter that adds ANSI colors to log levels."""

    def __init__(self, fmt: str, use_color: bool = True) -> None:
        super().__init__(fmt)
        self._use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        """Format the record with color if enabled.

        Args:
            record: The log record to format.

        Returns:
            The formatted log message.
        """
        original_levelname = record.levelname
        if self._use_color:
            color = ANSI_COLORS.get(record.levelno)
            if color:
                record.levelname = f"{color}{record.levelname}{ANSI_RESET}"
        try:
            return super().format(record)
        finally:
            record.levelname = original_levelname


def configure_logging(
    log_dir: Path,
    log_max_bytes: int,
    log_retention_days: int,
    debug: bool,
    uvicorn_log_level: str = "info",
) -> Path:
    """Configure Hub logging to write to file and stdout.

    Args:
        log_dir: Directory to store log files.
        log_max_bytes: Maximum size of a log file before rotation.
        log_retention_days: Days to keep rotated log files.
        debug: Whether to enable debug-level logging.
        uvicorn_log_level: Log level for uvicorn loggers (default: info).

    Returns:
        The path to the active log file.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / DEFAULT_LOG_FILENAME
    log_level = logging.DEBUG if debug else logging.INFO

    format_string = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    formatter = logging.Formatter(format_string)

    file_handler = CleanupRotatingFileHandler(
        filename=log_file,
        max_bytes=log_max_bytes,
        retention_days=log_retention_days,
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(log_level)

    stream_handler = logging.StreamHandler()
    stream_supports_color = False
    if hasattr(stream_handler.stream, "isatty"):
        stream_supports_color = stream_handler.stream.isatty()
    stream_handler.setFormatter(
        ColorFormatter(format_string, use_color=stream_supports_color)
    )
    stream_handler.setLevel(log_level)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)

    # Tone down noisy dependency loggers while preserving debug elsewhere.
    sqlalchemy_level = logging.INFO if debug else logging.WARNING
    for logger_name in ("sqlalchemy.engine", "sqlalchemy.pool"):
        logging.getLogger(logger_name).setLevel(sqlalchemy_level)

    aiosqlite_level = logging.INFO if debug else logging.WARNING
    logging.getLogger("aiosqlite").setLevel(aiosqlite_level)

    uvi_level = getattr(logging, uvicorn_log_level.upper(), logging.INFO)
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.propagate = True
        logger.setLevel(uvi_level)

    removed = _purge_old_logs(log_dir, log_file, log_retention_days)
    if removed:
        logging.getLogger(__name__).info(
            "Purged %s old log files from %s", removed, log_dir
        )

    return log_file
