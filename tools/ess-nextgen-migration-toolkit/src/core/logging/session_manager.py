"""Diagnostics session bundle management."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_DEFAULT_MAX_SESSIONS = 3
# Generic, product-agnostic default. Domain callers (e.g. the ESS toolkit) pass
# their own report filename via ``report_filename``.
DEFAULT_REPORT_FILENAME = "telemetry_report.md"
_LOG_FILENAME = "session.log"


@dataclass(frozen=True)
class SessionPaths:
    """Resolved paths for the two-file diagnostics session bundle."""

    session_dir: Path
    report_path: Path
    log_path: Path


class SessionManager:
    """Owns creation and path tracking for one diagnostics session bundle.

    The report filename is a constructor argument so the generic framework does
    not hardcode any product-specific name; it defaults to the neutral
    ``telemetry_report.md``. Domain layers pass their own (the ESS toolkit uses
    ``migration_report.md``). The ``output_root`` base folder is caller-supplied
    and used as-is.
    """

    def __init__(
        self,
        output_root: Path,
        *,
        report_filename: str = DEFAULT_REPORT_FILENAME,
        clock: Callable[[], datetime] | None = None,
        max_sessions: int = _DEFAULT_MAX_SESSIONS,
    ) -> None:
        self._output_root = output_root
        self._report_filename = report_filename
        self._clock = clock or datetime.now
        self._paths: SessionPaths | None = None
        self._max_sessions = max_sessions

    @property
    def paths(self) -> SessionPaths:
        """Return the active session paths after session creation."""
        if self._paths is None:
            msg = "Diagnostics session has not been created."
            raise RuntimeError(msg)
        return self._paths

    def create_session(self) -> SessionPaths:
        """Create one ``output/session-YYYY-MM-DD_HH-MM-SS`` bundle folder."""
        if self._paths is not None:
            return self._paths

        timestamp = self._clock().strftime("%Y-%m-%d_%H-%M-%S")
        session_dir = self._output_root / f"session-{timestamp}"
        session_dir.mkdir(parents=True, exist_ok=False)
        self._paths = SessionPaths(
            session_dir=session_dir,
            report_path=session_dir / self._report_filename,
            log_path=session_dir / _LOG_FILENAME,
        )
        self._prune_old_sessions()
        return self._paths

    def _prune_old_sessions(self) -> None:
        """Remove oldest session bundles when count exceeds ``max_sessions``."""
        session_dirs = sorted(
            (
                d
                for d in self._output_root.iterdir()
                if d.is_dir() and d.name.startswith("session-")
            ),
            key=lambda d: d.name,
        )
        while len(session_dirs) > self._max_sessions:
            oldest = session_dirs.pop(0)
            if self._paths and oldest == self._paths.session_dir:
                continue
            shutil.rmtree(oldest, ignore_errors=True)
