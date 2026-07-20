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
from core.models import ChangeEntry, DiagnosticEntry
from modules.migration.models import MigrationContext

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

    assert "[2026-07-18 14:32:05] [DEBUG] [Migration/DiagnosticsStep] Debug detail" in captured.out
    assert "[2026-07-18 14:32:05] [DEBUG] [Migration/DiagnosticsStep] Debug detail" in session_log


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
        logger.LogAdvisory("Customer note", severity="INFO", category="Summary")
        logger.LogAdvisory(
            "Manual review needed",
            severity="WARNING",
            component="Employee Context",
            recommendation="Move logic into OnConversationStart.",
        )
        logger.LogChange(
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
        ExecutionMode="WRITEBACK",
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
    assert "# Migration Report" in report
    assert "## Summary" in report
    assert "- Execution Mode: WRITEBACK" in report
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


def test_tee_stream_survives_log_file_write_failure(
    workspace: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """TeeStream must never abort migration work if session.log write fails (DIAG-001)."""
    context = MigrationContext()
    logger = Logger.start_session(
        workspace, context, level=LogLevel.DEBUG, clock=lambda: FIXED_TIME
    )
    try:
        # Force-close the log file to simulate disk/handle failure
        logger.session_manager.paths.log_path.open("w").close()
        log_handle = logger._log_file  # noqa: SLF001
        log_handle.close()
        # This must NOT raise — console output should still work
        sys.stdout.write("after-close output\n")
    finally:
        logger.close()

    captured = capsys.readouterr()
    assert "after-close output" in captured.out


def test_log_advisory_default_severity_routes_to_warnings(workspace: Path) -> None:
    """A plain LogAdvisory() must default to WARNING so it appears in the report."""
    context = MigrationContext()
    logger = Logger.start_session(workspace, context, clock=lambda: FIXED_TIME)
    try:
        logger.LogAdvisory("Needs manual review")
    finally:
        logger.close()

    assert len(context.Warnings) == 1
    assert context.Warnings[0].message == "Needs manual review"
    assert context.Warnings[0].severity == "WARNING"
    assert context.Logs == []


def test_session_manager_prunes_old_sessions(workspace: Path) -> None:
    """SessionManager should keep at most max_sessions bundles."""
    times = [datetime(2026, 7, 18, 10, 0, s) for s in range(8)]
    for t in times[:7]:
        mgr = SessionManager(workspace, clock=lambda _t=t: _t, max_sessions=5)
        mgr.create_session()

    session_dirs = sorted(d.name for d in workspace.iterdir() if d.is_dir())
    # 7 created, max_sessions=5 → oldest 2 pruned, 5 remain
    assert len(session_dirs) == 5
    assert "session-2026-07-18_10-00-00" not in session_dirs
    assert "session-2026-07-18_10-00-01" not in session_dirs
    assert "session-2026-07-18_10-00-06" in session_dirs
