"""Pipeline execution context — base model for all toolkit contexts.

This module defines ``ExecutionContext``, the base dataclass that any
toolkit context must extend.  It carries the execution mode and diagnostic
collectors that ``core/logging`` (Logger, Reporter) depend on.

Domain-specific state (e.g. ComponentSet, agent metadata for ESS migrations)
belongs in subclass contexts defined in the modules layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class ExecutionMode(StrEnum):
    """Toolkit execution modes — intent-revealing, not domain-specific.

    Extensible: future consumers can subclass to add modes.
    Being a StrEnum, values compare equal to their string form
    (e.g. ``ExecutionMode.READONLY == "READONLY"``).
    """

    READONLY = "READONLY"
    WRITEBACK = "WRITEBACK"


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
class ExecutionContext:
    """Base execution context with mode and diagnostic collectors.

    All toolkit contexts must extend this class so that the Logger and
    Reporter (in ``core/logging``) can operate generically.

    Inputs:
        ExecutionMode: Current toolkit mode, such as DISCOVER, PREVIEW, or MIGRATE.
        Logs, Warnings, Errors, Changes: Mutable collectors populated by
            diagnostics and pipeline steps.

    Outputs:
        The same context instance is rendered by the Reporter into
        ``migration_report.md``.
    """

    ExecutionMode: ExecutionMode = field(default=ExecutionMode.READONLY)
    Logs: list[DiagnosticEntry] = field(default_factory=list)
    Warnings: list[DiagnosticEntry] = field(default_factory=list)
    Errors: list[DiagnosticEntry] = field(default_factory=list)
    Changes: list[ChangeEntry] = field(default_factory=list)
