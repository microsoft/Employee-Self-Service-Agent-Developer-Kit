"""Unit tests for MigrationPipelineStep mode-gating."""

from __future__ import annotations

from core.models import ExecutionMode
from core.pipelines import Pipeline
from modules.migration.migration_step import MigrationPipelineStep
from modules.migration.models import MigrationContext


class DiscoverOnlyStep(MigrationPipelineStep):
    def __init__(self) -> None:
        super().__init__(name="readonly-only", supported_modes=("READONLY",))

    def execute(self, context: MigrationContext) -> MigrationContext:
        context.Logs.append(None)  # type: ignore[arg-type]  # marker
        return context


class MigrateOnlyStep(MigrationPipelineStep):
    def __init__(self) -> None:
        super().__init__(name="writeback-only", supported_modes=("WRITEBACK",))

    def execute(self, context: MigrationContext) -> MigrationContext:
        context.Warnings.append(None)  # type: ignore[arg-type]  # marker
        return context


class AllModesStep(MigrationPipelineStep):
    """No supported_modes declared — should run in every mode."""

    def __init__(self) -> None:
        super().__init__(name="all-modes")

    def execute(self, context: MigrationContext) -> MigrationContext:
        context.Changes.append(None)  # type: ignore[arg-type]  # marker
        return context


def test_mode_gated_step_runs_only_in_declared_mode() -> None:
    pipeline = (
        Pipeline.builder("mode-test", input_type=MigrationContext)
        .use(DiscoverOnlyStep())
        .use(MigrateOnlyStep())
        .build()
    )

    discover_ctx = MigrationContext(ExecutionMode=ExecutionMode.READONLY)
    result = pipeline.run(discover_ctx)
    assert len(result.Logs) == 1  # discover-only ran
    assert len(result.Warnings) == 0  # migrate-only skipped

    migrate_ctx = MigrationContext(ExecutionMode=ExecutionMode.WRITEBACK)
    result = pipeline.run(migrate_ctx)
    assert len(result.Logs) == 0  # discover-only skipped
    assert len(result.Warnings) == 1  # migrate-only ran


def test_empty_supported_modes_runs_in_all_modes() -> None:
    pipeline = Pipeline.builder("always", input_type=MigrationContext).use(AllModesStep()).build()

    for mode in (ExecutionMode.READONLY, ExecutionMode.WRITEBACK):
        ctx = MigrationContext(ExecutionMode=mode)
        result = pipeline.run(ctx)
        assert len(result.Changes) == 1


def test_subclass_can_override_can_execute_with_super() -> None:
    """A step can add richer conditions while preserving mode gating via super()."""

    class ConditionalStep(MigrationPipelineStep):
        def __init__(self) -> None:
            super().__init__(name="conditional", supported_modes=("WRITEBACK",))

        def can_execute(self, context: MigrationContext) -> bool:
            if not super().can_execute(context):
                return False
            return len(context.Changes) > 0

        def execute(self, context: MigrationContext) -> MigrationContext:
            context.Logs.append(None)  # type: ignore[arg-type]
            return context

    pipeline = Pipeline.builder("cond", input_type=MigrationContext).use(ConditionalStep()).build()

    # Right mode but no changes — skipped by subclass condition
    ctx = MigrationContext(ExecutionMode=ExecutionMode.WRITEBACK)
    result = pipeline.run(ctx)
    assert len(result.Logs) == 0

    # Right mode AND has changes — runs
    ctx = MigrationContext(ExecutionMode=ExecutionMode.WRITEBACK, Changes=[None])  # type: ignore[list-item]
    result = pipeline.run(ctx)
    assert len(result.Logs) == 1

    # Wrong mode — skipped by super() mode gate
    ctx = MigrationContext(ExecutionMode=ExecutionMode.READONLY, Changes=[None])  # type: ignore[list-item]
    result = pipeline.run(ctx)
    assert len(result.Logs) == 0
