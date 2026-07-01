"""Diagnostics session bundle management."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class SessionPaths:
    """Resolved paths for the two-file diagnostics session bundle."""

    session_dir: Path
    report_path: Path
    log_path: Path


class SessionManager:
    """Owns creation and path tracking for one diagnostics session bundle."""

    def __init__(
        self,
        output_root: Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._output_root = output_root
        self._clock = clock or datetime.now
        self._paths: SessionPaths | None = None

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
            report_path=session_dir / "migration_report.md",
            log_path=session_dir / "session.log",
        )
        return self._paths
