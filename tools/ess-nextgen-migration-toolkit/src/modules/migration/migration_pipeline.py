"""Migration Pipeline builder."""

from __future__ import annotations

from core.logging import Logger
from core.pipelines import Pipeline
from modules.migration.migration_step import MigrationPipelineStep
from modules.migration.models import MigrationContext


class _MigrationPassthroughStep(MigrationPipelineStep):
    """Placeholder: migration-rule steps (TASK-010+) will replace this."""

    def __init__(self, logger: Logger, supported_modes: tuple[str, ...]) -> None:
        super().__init__(
            description="No-op placeholder until migration rules are implemented.",
            supported_modes=supported_modes,
        )
        self._logger = logger

    def execute(self, context: MigrationContext) -> MigrationContext:
        # TODO: Migration-rule steps will replace this pass-through.
        self._logger.LogDebug(
            "Migration stage is currently a no-op.",
            pipeline_stage="Migration",
            pipeline_step=self.name(),
        )
        return context


def build_migration_pipeline(
    logger: Logger, supported_modes: tuple[str, ...]
) -> Pipeline[MigrationContext, MigrationContext]:
    """Build the migration stage pipeline."""
    return (
        Pipeline.builder("Migration Pipeline", input_type=MigrationContext)
        .use(_MigrationPassthroughStep(logger, supported_modes))
        .build()
    )
