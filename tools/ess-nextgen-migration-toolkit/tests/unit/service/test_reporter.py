"""Unit tests for the ESS service-layer migration Reporter."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from core.logging import Logger, SessionManager
from core.models import ChangeEntry, DiagnosticEntry
from modules.transformation.models import ExecutionMode, MigrationContext
from service.reporter import Reporter

FIXED_TIME = datetime(2026, 7, 18, 14, 32, 5)


def test_reporter_renders_customer_report_from_context_collectors(tmp_path: Path) -> None:
    context = MigrationContext(
        mode=ExecutionMode.WRITEBACK,
        Changes=[
            ChangeEntry(
                message="Runtime Provider CA → DA",
                rule_id="RULE-001",
                title="Updated Agent Metadata",
                component="ESS HR Agent",
                details=("Template           CA → DA",),
            )
        ],
        Warnings=[
            DiagnosticEntry(
                message="OnActivity trigger unsupported.",
                severity="WARNING",
                component="Employee Context",
                recommendation="Move logic into OnConversationStart.",
            )
        ],
    )
    manager = SessionManager(tmp_path, clock=lambda: FIXED_TIME)
    manager.create_session()

    Reporter(manager).render(context)

    report = manager.paths.report_path.read_text(encoding="utf-8")
    assert "# Migration Report" in report
    assert "## Summary" in report
    assert "- Execution Mode: WRITEBACK" in report
    assert "## Changes" in report
    assert "### RULE-001 — Updated Agent Metadata" in report
    assert "Template           CA → DA" in report
    assert "## Warnings — Manual Review Required" in report
    assert "Recommendation     Move logic into OnConversationStart." in report


def test_logger_and_reporter_leave_exactly_two_bundle_files(tmp_path: Path) -> None:
    context = MigrationContext()
    logger = Logger.start_session(
        tmp_path, context, report_filename="migration_report.md", clock=lambda: FIXED_TIME
    )
    logger.close()

    Reporter(logger.session_manager).render(context)

    bundle_files = sorted(path.name for path in logger.session_manager.paths.session_dir.iterdir())
    assert bundle_files == ["migration_report.md", "session.log"]
