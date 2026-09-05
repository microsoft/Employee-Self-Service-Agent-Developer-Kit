"""Run-scoped telemetry (spec §8 observability).

Emits a single structured "run summary" event keyed by a local ``correlation_id`` with
per-kind / per-environment counts and the per-scope complete/incomplete gate. The
correlation id is a log/trace aid only -- it is never sent to inventory or stamped on
rows (no per-run watermark). Deliberately logs no identifiers/PII beyond audit needs --
the submitter/admin identity is EUPI (server-side privacy model). Natural keys and
attribute values are **not** emitted.
"""

from __future__ import annotations

import logging
from typing import Protocol

from .models import RunSummary, ScopeReport

logger = logging.getLogger("tenant_inventory_discovery")


class TelemetrySink(Protocol):
    """Where run summaries go (stdout log, App Insights, etc.)."""

    def emit_run_summary(self, summary: RunSummary) -> None: ...


def _scope_row(report: ScopeReport) -> dict[str, object]:
    return {
        "environmentId": report.scope.environment_id,  # opaque id, not PII
        "kind": report.scope.kind.discriminator,
        "enumerated": report.enumerated,
        "mapped": report.mapped,
        "skippedInvalid": report.skipped_invalid,
        "complete": report.complete,
        # Whether absence in this scope was allowed to mean deletion. The single most
        # useful field when a retirement needs explaining after the fact.
        "authoritative": report.authoritative,
        "capped": report.capped,
        "hasError": report.error is not None,
    }


class LoggingTelemetrySink:
    """Default sink: one structured log record per run (spec §8)."""

    def emit_run_summary(self, summary: RunSummary) -> None:
        payload = {
            "event": "discovery.run_summary",
            "correlationId": summary.correlation_id,
            "aborted": summary.aborted,
            "synced": summary.synced_ok,
            "syncBlocked": bool(summary.sync_blocked_reason),
            "authoritativeScopeCount": len(summary.authoritative_scopes),
            "completedScopeCount": len(summary.completed_scopes),
            "submittedCount": len(summary.payload),
            "carriedForward": summary.carried_forward,
            "retiredCounts": summary.retired_counts,
            "scopes": [_scope_row(s) for s in summary.scopes],
        }
        logger.info("discovery.run_summary", extra={"discovery": payload})
