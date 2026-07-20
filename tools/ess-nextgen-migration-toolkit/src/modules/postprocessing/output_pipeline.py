"""Output Pipeline builder."""

from __future__ import annotations

from core.logging import Logger
from core.pipelines import Pipeline
from modules.migration.migration_step import MigrationPipelineStep
from modules.migration.models import MigrationContext

_SUPPORTED_MODES = ("READONLY", "WRITEBACK")


class _OutputPassthroughStep(MigrationPipelineStep):
    """Temporary pass-through until output behaviors land."""

    def __init__(self, logger: Logger) -> None:
        super().__init__(
            description="Pass through the shared context until output behaviors are implemented.",
            supported_modes=_SUPPORTED_MODES,
        )
        self._logger = logger

    def execute(self, context: MigrationContext) -> MigrationContext:
        self._logger.LogDebug(
            "Output stage is currently a no-op.",
            pipeline_stage="Output",
            pipeline_step=self.name(),
        )
        return context


def build_output_pipeline(logger: Logger) -> Pipeline[MigrationContext, MigrationContext]:
    """Build the output stage pipeline."""
    return (
        Pipeline.builder("Output Pipeline", input_type=MigrationContext)
        .use(_OutputPassthroughStep(logger))
        .build()
    )
