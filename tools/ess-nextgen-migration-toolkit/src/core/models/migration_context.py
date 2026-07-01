"""Canonical migration context models used by diagnostics.

The migration context is the shared execution state passed through the toolkit.
This module intentionally defines only the diagnostic collectors required by
the diagnostics framework; later pipeline tasks can extend the same canonical
model with additional domain state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class DiagnosticEntry:
    """Structured diagnostic entry accumulated for customer reports."""

    message: str
    severity: str = "INFO"
    timestamp: datetime | None = None
    category: str = "General"
    component: str | None = None
    pipeline_stage: str | None = None
    pipeline_step: str | None = None
    recommendation: str | None = None


@dataclass(frozen=True)
class ChangeEntry:
    """Structured customer-facing change accumulated for report rendering."""

    message: str
    rule_id: str | None = None
    title: str | None = None
    component: str | None = None
    details: tuple[str, ...] = ()


@dataclass
class MigrationContext:
    """Shared execution context with diagnostics report-model collectors.

    Inputs:
        ExecutionMode: Current toolkit mode, such as DISCOVER, PREVIEW, or MIGRATE.
        Logs, Warnings, Errors, Changes: Mutable collectors populated by
            diagnostics and migration steps.

    Outputs:
        The same context instance is rendered by the Reporter into
        ``migration_report.md``.
    """

    ExecutionMode: str = "DISCOVER"
    Logs: list[DiagnosticEntry] = field(default_factory=list)
    Warnings: list[DiagnosticEntry] = field(default_factory=list)
    Errors: list[DiagnosticEntry] = field(default_factory=list)
    Changes: list[ChangeEntry] = field(default_factory=list)
