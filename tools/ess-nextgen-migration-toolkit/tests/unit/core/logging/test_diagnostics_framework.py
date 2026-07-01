"""Unit tests for diagnostics logging, sessions, and reporting."""

from __future__ import annotations

import re
import shutil
import sys
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest

from core.logging import Logger, LogLevel, Reporter, SessionManager
from core.models import ChangeEntry, DiagnosticEntry, MigrationContext

FIXED_TIME = datetime(2026, 7, 18, 14, 32, 5)


@pytest.fixture
def workspace(request: pytest.FixtureRequest) -> Iterator[Path]:
    safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "-", request.node.name)
    path = Path.cwd() / ".pytest-diagnostics-workspace" / safe_name
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        if path.exists():
            shutil.rmtree(path)


def test_session_manager_creates_timestamped_session_folder(workspace: Path) -> None:
    manager = SessionManager(workspace, clock=lambda: FIXED_TIME)

    paths = manager.create_session()

    assert paths.session_dir == workspace / "session-2026-07-18_14-32-05"
    assert paths.session_dir.is_dir()
    assert paths.report_path == paths.session_dir / "migration_report.md"
    assert paths.log_path == paths.session_dir / "session.log"


def test_transcript_tee_captures_stdout_and_stderr(
    workspace: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    context = MigrationContext()
    logger = Logger.start_session(
        workspace,
        context,
        level=LogLevel.DEBUG,
        clock=lambda: FIXED_TIME,
    )
    try:
        sys.stdout.write("incidental stdout\n")
        sys.stderr.write("incidental stderr\n")
    finally:
        logger.close()

    captured = capsys.readouterr()
    session_log = logger.session_manager.paths.log_path.read_text(encoding="utf-8")

    assert "incidental stdout" in captured.out
    assert "incidental stderr" in captured.err
    assert "incidental stdout" in session_log
    assert "incidental stderr" in session_log


def test_engineer_channel_writes_console_and_session_log(
    workspace: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    context = MigrationContext()
    logger = Logger.start_session(
        workspace,
        context,
        level=LogLevel.DEBUG,
        clock=lambda: FIXED_TIME,
    )
    try:
        logger.LogDebug(
            "Debug detail",
            pipeline_stage="Migration",
            pipeline_step="DiagnosticsStep",
        )
    finally:
        logger.close()

    captured = capsys.readouterr()
    session_log = logger.session_manager.paths.log_path.read_text(encoding="utf-8")

    assert "2026-07-18 14:32:05 DEBUG Migration DiagnosticsStep Debug detail" in captured.out
    assert "2026-07-18 14:32:05 DEBUG Migration DiagnosticsStep Debug detail" in session_log


def test_customer_channel_updates_report_model_only(
    workspace: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    context = MigrationContext()
    logger = Logger.start_session(
        workspace,
        context,
        level=LogLevel.DEBUG,
        clock=lambda: FIXED_TIME,
    )
    try:
        logger.LogCustomer("Customer note", category="Summary")
        logger.LogCustomer(
            "Manual review needed",
            severity="WARNING",
            component="Employee Context",
            recommendation="Move logic into OnConversationStart.",
        )
        logger.LogFancy(
            "Runtime Provider CA → DA",
            rule_id="RULE-001",
            title="Updated Agent Metadata",
            component="ESS HR Agent",
        )
    finally:
        logger.close()

    captured = capsys.readouterr()
    session_log = logger.session_manager.paths.log_path.read_text(encoding="utf-8")

    assert captured.out == ""
    assert captured.err == ""
    assert session_log == ""
    assert context.Logs == [
        DiagnosticEntry(
            message="Customer note",
            severity="INFO",
            timestamp=FIXED_TIME,
            category="Summary",
        )
    ]
    assert context.Warnings == [
        DiagnosticEntry(
            message="Manual review needed",
            severity="WARNING",
            timestamp=FIXED_TIME,
            component="Employee Context",
            recommendation="Move logic into OnConversationStart.",
        )
    ]
    assert context.Changes == [
        ChangeEntry(
            message="Runtime Provider CA → DA",
            rule_id="RULE-001",
            title="Updated Agent Metadata",
            component="ESS HR Agent",
        )
    ]


def test_reporter_renders_customer_report_from_context_collectors(workspace: Path) -> None:
    context = MigrationContext(
        ExecutionMode="PREVIEW",
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
    manager = SessionManager(workspace, clock=lambda: FIXED_TIME)
    manager.create_session()

    Reporter(manager).render(context)

    report = manager.paths.report_path.read_text(encoding="utf-8")
    assert "# Migration Preview Report" in report
    assert "## Summary" in report
    assert "- Execution Mode: PREVIEW" in report
    assert "## Changes" in report
    assert "### RULE-001 — Updated Agent Metadata" in report
    assert "Template           CA → DA" in report
    assert "## Warnings — Manual Review Required" in report
    assert "Recommendation     Move logic into OnConversationStart." in report


def test_logger_and_reporter_leave_exactly_two_bundle_files(workspace: Path) -> None:
    context = MigrationContext()
    logger = Logger.start_session(workspace, context, clock=lambda: FIXED_TIME)
    logger.close()

    Reporter(logger.session_manager).render(context)

    bundle_files = sorted(path.name for path in logger.session_manager.paths.session_dir.iterdir())
    assert bundle_files == ["migration_report.md", "session.log"]
