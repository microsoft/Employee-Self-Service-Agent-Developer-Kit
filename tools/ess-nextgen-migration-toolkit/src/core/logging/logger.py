"""Dual-channel diagnostics logger with stdout/stderr transcript capture."""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import datetime
from enum import IntEnum
from io import TextIOBase
from pathlib import Path
from types import TracebackType
from typing import TextIO

from core.logging.session_manager import SessionManager
from core.models.execution_context import ChangeEntry, DiagnosticEntry, ExecutionContext


class LogLevel(IntEnum):
    """Engineer-channel log levels ordered by verbosity."""

    TRACE = 10
    DEBUG = 20
    INFO = 30
    WARNING = 40
    ERROR = 50
    FATAL = 60


class TeeStream(TextIOBase):
    """Mirror all text written to a CLI stream into ``session.log``."""

    def __init__(self, original: TextIO, log_file: TextIO) -> None:
        self._original = original
        self._log_file = log_file

    def write(self, text: str) -> int:
        """Write text to the original stream and mirror it to the session log."""
        chars_written = self._original.write(text)
        try:
            self._log_file.write(text)
        except Exception:  # noqa: BLE001 — DIAG-001: diagnostics must never abort execution
            pass
        return chars_written

    def flush(self) -> None:
        """Flush both the original stream and the mirrored session log."""
        self._original.flush()
        try:
            self._log_file.flush()
        except Exception:  # noqa: BLE001 — DIAG-001: diagnostics must never abort execution
            pass

    def isatty(self) -> bool:
        """Delegate terminal detection to the original stream."""
        return bool(self._original.isatty())


class Logger:
    """Single diagnostics I/O boundary for engineer and customer channels.

    Inputs:
        session_manager: Owner of the session bundle folder and file paths.
        context: ExecutionContext report-model collectors for customer output.
        level: Minimum engineer-channel level written to the CLI.

    Outputs:
        Engineer-channel messages are written to the CLI and mirrored into
        ``session.log`` by the installed tee. Customer-channel messages update
        the ExecutionContext collectors only.
    """

    def __init__(
        self,
        session_manager: SessionManager,
        context: ExecutionContext,
        *,
        level: LogLevel = LogLevel.INFO,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_manager = session_manager
        self._context = context
        self._level = level
        self._clock = clock or datetime.now
        self._stdout: TextIO | None = None
        self._stderr: TextIO | None = None
        self._log_file: TextIO | None = None
        self._started = False

    @classmethod
    def start_session(
        cls,
        output_root: Path,
        context: ExecutionContext,
        *,
        level: LogLevel = LogLevel.INFO,
        clock: Callable[[], datetime] | None = None,
    ) -> Logger:
        """Create a session bundle, install the transcript tee, and return Logger."""
        session_manager = SessionManager(output_root, clock=clock)
        logger = cls(session_manager, context, level=level, clock=clock)
        logger.start()
        return logger

    @property
    def session_manager(self) -> SessionManager:
        """Return the session manager that owns this logger's bundle."""
        return self._session_manager

    def start(self) -> None:
        """Install stdout/stderr tee capture for the active Python process."""
        if self._started:
            return

        paths = self._session_manager.create_session()
        self._log_file = paths.log_path.open("w", encoding="utf-8")
        self._stdout = sys.stdout
        self._stderr = sys.stderr
        sys.stdout = TeeStream(self._stdout, self._log_file)
        sys.stderr = TeeStream(self._stderr, self._log_file)
        self._started = True

    def close(self) -> None:
        """Restore process streams and close ``session.log``."""
        if not self._started:
            return

        if self._stdout is not None:
            sys.stdout = self._stdout
        if self._stderr is not None:
            sys.stderr = self._stderr
        if self._log_file is not None:
            try:
                self._log_file.flush()
                self._log_file.close()
            except Exception:  # noqa: BLE001 — DIAG-001: safe teardown
                pass
        self._started = False

    def __enter__(self) -> Logger:
        """Install transcript capture for context-manager usage."""
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Restore process streams when leaving a diagnostics session."""
        self.close()

    def LogDebug(
        self,
        message: str,
        *,
        pipeline_stage: str = "-",
        pipeline_step: str = "-",
    ) -> None:
        """Write a DEBUG engineer-channel message to CLI/session.log."""
        self._write_engineer(LogLevel.DEBUG, message, pipeline_stage, pipeline_step)

    def LogInfo(
        self,
        message: str,
        *,
        pipeline_stage: str = "-",
        pipeline_step: str = "-",
    ) -> None:
        """Write an INFO engineer-channel message to CLI/session.log."""
        self._write_engineer(LogLevel.INFO, message, pipeline_stage, pipeline_step)

    def LogWarning(
        self,
        message: str,
        *,
        pipeline_stage: str = "-",
        pipeline_step: str = "-",
    ) -> None:
        """Write a WARNING engineer-channel message to CLI/session.log."""
        self._write_engineer(LogLevel.WARNING, message, pipeline_stage, pipeline_step)

    def LogError(
        self,
        message: str,
        *,
        pipeline_stage: str = "-",
        pipeline_step: str = "-",
    ) -> None:
        """Write an ERROR engineer-channel message to CLI/session.log."""
        self._write_engineer(LogLevel.ERROR, message, pipeline_stage, pipeline_step)

    def LogAdvisory(
        self,
        message: str,
        *,
        severity: str = "WARNING",
        category: str = "General",
        component: str | None = None,
        recommendation: str | None = None,
    ) -> None:
        """Append a customer-channel manual-review advisory to the report model only."""
        entry = DiagnosticEntry(
            message=message,
            severity=severity,
            timestamp=self._clock(),
            category=category,
            component=component,
            recommendation=recommendation,
        )
        normalized_severity = severity.upper()
        if normalized_severity == "WARNING":
            self._context.Warnings.append(entry)
        elif normalized_severity in {"ERROR", "FATAL"}:
            self._context.Errors.append(entry)
        else:
            self._context.Logs.append(entry)

    def LogChange(
        self,
        message: str,
        *,
        rule_id: str | None = None,
        title: str | None = None,
        component: str | None = None,
        details: tuple[str, ...] = (),
    ) -> None:
        """Append a customer-channel change entry to the report model only."""
        self._context.Changes.append(
            ChangeEntry(
                message=message,
                rule_id=rule_id,
                title=title,
                component=component,
                details=details,
            )
        )

    def _write_engineer(
        self,
        level: LogLevel,
        message: str,
        pipeline_stage: str,
        pipeline_step: str,
    ) -> None:
        timestamp = self._clock().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] [{level.name}] [{pipeline_stage}/{pipeline_step}] {message}\n"

        if level >= self._level:
            # Above console threshold — write to console (TeeStream mirrors to session.log)
            stream = sys.stderr if level >= LogLevel.ERROR else sys.stdout
            stream.write(line)
            stream.flush()
        elif self._log_file is not None:
            # Below console threshold — write directly to session.log only
            try:
                self._log_file.write(line)
                self._log_file.flush()
            except Exception:  # noqa: BLE001 — DIAG-001
                pass
