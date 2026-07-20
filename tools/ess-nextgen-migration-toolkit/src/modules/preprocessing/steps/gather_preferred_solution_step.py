"""Capture the optional preferred solution for writeback."""

from __future__ import annotations

from core.logging import Logger
from modules.migration.migration_step import MigrationPipelineStep
from modules.migration.models import MigrationContext


class GatherPreferredSolutionStep(MigrationPipelineStep):
    """Prompt for the optional preferred solution unique name."""

    def __init__(self, logger: Logger, supported_modes: tuple[str, ...]) -> None:
        super().__init__(
            description="Capture the optional preferred solution for writeback.",
            supported_modes=supported_modes,
        )
        self._logger = logger

    def execute(self, context: MigrationContext) -> MigrationContext:
        preferred_solution = input(
            "Do you have a preferred solution for writeback? "
            "(Enter solution unique name, or press Enter to skip) ",
        ).strip()

        context.preferred_solution = preferred_solution or None
        if context.preferred_solution is None:
            self._logger.LogInfo(
                "No preferred solution provided; writeback will use the default solution.",
                pipeline_stage="Input",
                pipeline_step=self.name(),
            )
        else:
            self._logger.LogInfo(
                f"Using preferred solution {context.preferred_solution}.",
                pipeline_stage="Input",
                pipeline_step=self.name(),
            )
        return context
