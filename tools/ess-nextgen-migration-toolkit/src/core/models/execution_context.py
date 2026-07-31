"""Pipeline execution context — base model for all toolkit contexts.

This module defines ``ExecutionContext``, the base dataclass that any
toolkit context must extend.  It carries a generic, opaque execution ``mode``
string and the diagnostic collectors that the ``core/logging`` Logger and the
service-layer Reporter consume.

The base is intentionally product-agnostic: it does not define what the ``mode``
values mean. Domain layers supply their own vocabulary (e.g. the ESS
``ExecutionMode`` StrEnum in ``modules/transformation/models``), whose string
values slot directly into ``mode``.

Domain-specific state (e.g. ComponentSet, agent metadata for ESS migrations)
belongs in subclass contexts defined in the modules layer.
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
    component_type: str | None = None
    details: tuple[str, ...] = ()


@dataclass
class ExecutionContext:
    """Base execution context with a generic mode and diagnostic collectors.

    All toolkit contexts must extend this class so that the ``core/logging``
    Logger and the service-layer Reporter can operate generically.

    Inputs:
        mode: Opaque execution-mode string. The framework does not interpret it;
            domain layers assign meaning (e.g. ``"READONLY"`` / ``"WRITEBACK"``).
            Empty string means no mode was declared.
        Logs, Warnings, Errors, Changes: Mutable collectors populated by
            diagnostics and pipeline steps.

    Outputs:
        The same context instance is rendered by the service-layer Reporter into
        the session report.
    """

    mode: str = ""
    Logs: list[DiagnosticEntry] = field(default_factory=list)
    Warnings: list[DiagnosticEntry] = field(default_factory=list)
    Errors: list[DiagnosticEntry] = field(default_factory=list)
    Changes: list[ChangeEntry] = field(default_factory=list)
