"""Output Pipeline builder."""

from __future__ import annotations

from core.logging import Logger
from core.pipelines import Pipeline
from modules.migration.migration_step import MigrationPipelineStep
from modules.migration.models import MigrationContext


class _OutputPassthroughStep(MigrationPipelineStep):
    """Placeholder: validation/writeback/report steps (TASK-007) will replace this."""

    def __init__(self, logger: Logger, supported_modes: tuple[str, ...]) -> None:
        super().__init__(
            description="No-op placeholder until output behaviors are implemented.",
            supported_modes=supported_modes,
        )
        self._logger = logger

    def execute(self, context: MigrationContext) -> MigrationContext:
        # TODO: ValidateMigration, Writeback (WRITEBACK-only), and
        # GenerateMigrationReport steps will replace this once TASK-007 lands.
        self._logger.LogDebug(
            "Output stage is currently a no-op.",
            pipeline_stage="Output",
            pipeline_step=self.name(),
        )
        return context


def build_output_pipeline(
    logger: Logger, supported_modes: tuple[str, ...]
) -> Pipeline[MigrationContext, MigrationContext]:
    """Build the output stage pipeline."""
    return (
        Pipeline.builder("Output Pipeline", input_type=MigrationContext)
        .use(_OutputPassthroughStep(logger, supported_modes))
        .build()
    )
