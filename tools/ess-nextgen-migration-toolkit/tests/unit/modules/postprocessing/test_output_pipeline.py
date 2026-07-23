"""Unit tests for the output/postprocessing pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import pytest

from core.logging import Logger
from core.pipelines import Pipeline
from modules.postprocessing.output_pipeline import build_output_pipeline
from modules.postprocessing.steps import (
    GenerateMigrationReportStep,
    ValidateMigrationStep,
    WritebackStep,
)
from modules.postprocessing.steps.validate_migration_step import MigrationValidationError
from modules.transformation.migration_step import MigrationPipelineStep
from modules.transformation.models import ExecutionMode, MigrationContext

FIXED_TIME = datetime(2026, 7, 18, 14, 32, 5)


class FakeLogger:
    def __init__(self) -> None:
        self.infos: list[str] = []

    def LogInfo(self, message: str, **_: object) -> None:
        self.infos.append(message)


class FakeDataverseClient:
    def __init__(self) -> None:
        self.update_calls: list[tuple[str, str, dict[str, Any], dict[str, str] | None]] = []

    def update(
        self,
        entity_set: str,
        record_id: str,
        data: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.update_calls.append((entity_set, record_id, data, headers))


@dataclass
class InvalidPendingWritesContext(MigrationContext):
    @property
    def pending_writes(self) -> list[dict[str, Any]]:
        return [{"entity_set": "bots", "record_id": "", "changes": {}}]


def test_output_pipeline_uses_validate_writeback_and_report_steps() -> None:
    pipeline = build_output_pipeline(cast(Logger, FakeLogger()), ("READONLY", "WRITEBACK"))

    assert [step.name() for step in pipeline.steps] == [
        "ValidateMigration",
        "Writeback",
        "GenerateMigrationReport",
    ]
    assert all(isinstance(step, MigrationPipelineStep) for step in pipeline.steps)
    assert [step.supported_modes() for step in pipeline.steps] == [
        frozenset({"READONLY", "WRITEBACK"}),
        frozenset({"WRITEBACK"}),
        frozenset({"READONLY", "WRITEBACK"}),
    ]


def test_validate_migration_accepts_well_formed_pending_writes() -> None:
    context = MigrationContext()
    context.writeback.target("bots", "bot-1", original={"template": "default"}).set(
        "template",
        "gptagent-1.0.0",
    )

    result = ValidateMigrationStep(cast(Logger, FakeLogger())).execute(context)

    assert result is context


def test_validate_migration_rejects_malformed_pending_write() -> None:
    step = ValidateMigrationStep(cast(Logger, FakeLogger()))

    with pytest.raises(MigrationValidationError, match="record_id"):
        step.execute(InvalidPendingWritesContext())


def test_writeback_applies_each_pending_write_exactly_once() -> None:
    client = FakeDataverseClient()
    context = MigrationContext(mode=ExecutionMode.WRITEBACK, dataverse_client=client)
    context.writeback.target("bots", "bot-1", original={"template": "default"}).set(
        "template",
        "gptagent-1.0.0",
    )
    context.writeback.target("botcomponents", "component-1", original={"data": "old"}).set(
        "data",
        "new",
    )

    result = WritebackStep(cast(Logger, FakeLogger())).execute(context)

    assert result is context
    assert client.update_calls == [
        ("bots", "bot-1", {"template": "gptagent-1.0.0"}, None),
        ("botcomponents", "component-1", {"data": "new"}, None),
    ]


def test_writeback_is_skipped_in_readonly_by_mode_gate() -> None:
    client = FakeDataverseClient()
    context = MigrationContext(mode=ExecutionMode.READONLY, dataverse_client=client)
    context.writeback.target("bots", "bot-1", original={"template": "default"}).set(
        "template",
        "gptagent-1.0.0",
    )
    pipeline = (
        Pipeline.builder("writeback-mode-gate", input_type=MigrationContext)
        .use(WritebackStep(cast(Logger, FakeLogger())))
        .build()
    )

    result = pipeline.run(context)

    assert result is context
    assert client.update_calls == []


def test_writeback_targets_preferred_solution_header_when_set() -> None:
    client = FakeDataverseClient()
    context = MigrationContext(
        mode=ExecutionMode.WRITEBACK,
        dataverse_client=client,
        preferred_solution="contoso_preferred",
    )
    context.writeback.target("bots", "bot-1", original={"template": "default"}).set(
        "template",
        "gptagent-1.0.0",
    )

    WritebackStep(cast(Logger, FakeLogger())).execute(context)

    assert client.update_calls == [
        (
            "bots",
            "bot-1",
            {"template": "gptagent-1.0.0"},
            {"MSCRM.SolutionUniqueName": "contoso_preferred"},
        )
    ]


def test_writeback_no_ops_on_empty_pending_writes() -> None:
    client = FakeDataverseClient()
    context = MigrationContext(mode=ExecutionMode.WRITEBACK, dataverse_client=client)

    result = WritebackStep(cast(Logger, FakeLogger())).execute(context)

    assert result is context
    assert client.update_calls == []


def test_generate_migration_report_renders_two_file_bundle(tmp_path: Path) -> None:
    context = MigrationContext(mode=ExecutionMode.READONLY)
    logger = Logger.start_session(
        tmp_path,
        context,
        report_filename="migration_report.md",
        clock=lambda: FIXED_TIME,
    )
    try:
        result = GenerateMigrationReportStep(logger).execute(context)
    finally:
        logger.close()

    assert result is context
    bundle_files = sorted(path.name for path in logger.session_manager.paths.session_dir.iterdir())
    assert bundle_files == ["migration_report.md", "session.log"]
    report = logger.session_manager.paths.report_path.read_text(encoding="utf-8")
    assert "# Migration Readiness Report" in report
