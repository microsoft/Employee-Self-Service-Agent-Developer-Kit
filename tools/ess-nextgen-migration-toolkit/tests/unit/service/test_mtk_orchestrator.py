"""Unit tests for orchestrator wiring."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.pipelines import Pipeline, PipelineStep
from modules.migration.models import MigrationContext
from service import mtk_orchestrator


@dataclass
class StageContext(MigrationContext):
    events: list[str] = field(default_factory=list)


class RecordingStageStep(PipelineStep[MigrationContext, MigrationContext]):
    def __init__(self, event: str) -> None:
        super().__init__(input_type=MigrationContext, output_type=MigrationContext, name=event)
        self._event = event

    def execute(self, context: MigrationContext) -> MigrationContext:
        if isinstance(context, StageContext):
            context.events.append(self._event)
        return context


def _stage(event: str) -> Pipeline[MigrationContext, MigrationContext]:
    return (
        Pipeline.builder(f"{event}-pipeline", input_type=MigrationContext)
        .use(
            RecordingStageStep(event),
        )
        .build()
    )


def test_main_runs_stage_pipelines_and_writes_two_bundle_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    created_contexts: list[MigrationContext] = []

    def build_context(*, ExecutionMode: object) -> StageContext:
        context = StageContext(ExecutionMode=ExecutionMode)
        created_contexts.append(context)
        return context

    monkeypatch.setattr(mtk_orchestrator, "OUTPUT_ROOT", tmp_path)
    monkeypatch.setattr(mtk_orchestrator, "MigrationContext", build_context)
    monkeypatch.setattr(mtk_orchestrator, "build_input_pipeline", lambda logger: _stage("input"))
    monkeypatch.setattr(
        mtk_orchestrator,
        "build_migration_pipeline",
        lambda logger: _stage("migration"),
    )
    monkeypatch.setattr(mtk_orchestrator, "build_output_pipeline", lambda logger: _stage("output"))

    mtk_orchestrator.main()

    assert len(created_contexts) == 1
    assert created_contexts[0].ExecutionMode == "READONLY"
    assert created_contexts[0].events == ["input", "migration", "output"]

    session_dirs = sorted(path for path in tmp_path.iterdir() if path.is_dir())
    assert len(session_dirs) == 1
    assert sorted(path.name for path in session_dirs[0].iterdir()) == [
        "migration_report.md",
        "session.log",
    ]


def test_main_closes_logger_when_pipeline_execution_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    closed = False

    class FakeLogger:
        session_manager = SimpleNamespace(paths=SimpleNamespace(session_dir=tmp_path / "session"))

        def LogInfo(self, message: str, **_: object) -> None:
            del message

        def close(self) -> None:
            nonlocal closed
            closed = True

    def fail_stage(logger: object) -> Pipeline[MigrationContext, MigrationContext]:
        del logger

        class FailingStep(PipelineStep[MigrationContext, MigrationContext]):
            def __init__(self) -> None:
                super().__init__(
                    input_type=MigrationContext,
                    output_type=MigrationContext,
                    name="fail",
                )

            def execute(self, context: MigrationContext) -> MigrationContext:
                raise RuntimeError("boom")

        return Pipeline.builder("failing", input_type=MigrationContext).use(FailingStep()).build()

    monkeypatch.setattr(
        mtk_orchestrator.Logger,
        "start_session",
        lambda output_root, context: FakeLogger(),
    )
    monkeypatch.setattr(mtk_orchestrator.Reporter, "render", lambda self, context: None)
    monkeypatch.setattr(mtk_orchestrator, "build_input_pipeline", fail_stage)
    monkeypatch.setattr(mtk_orchestrator, "build_migration_pipeline", lambda logger: _stage("m"))
    monkeypatch.setattr(mtk_orchestrator, "build_output_pipeline", lambda logger: _stage("o"))

    with pytest.raises(RuntimeError, match="boom"):
        mtk_orchestrator.main()

    assert closed is True
