"""Render the terminal customer-facing migration report."""

from __future__ import annotations

from core.logging import Logger
from modules.transformation.migration_step import MigrationPipelineStep
from modules.transformation.models import MigrationContext
from service.reporter import Reporter

_SUPPORTED_MODES = ("READONLY", "WRITEBACK")


class GenerateMigrationReportStep(MigrationPipelineStep):
    """Render ``migration_report.md`` from MigrationContext collectors."""

    def __init__(self, logger: Logger) -> None:
        super().__init__(
            name="GenerateMigrationReport",
            description="Render the customer-facing migration report.",
            supported_modes=_SUPPORTED_MODES,
        )
        self._logger = logger

    def execute(self, context: MigrationContext) -> MigrationContext:
        Reporter(self._logger.session_manager).render(context)
        self._logger.LogInfo(
            "Rendered migration_report.md.",
            pipeline_stage="Output",
            pipeline_step=self.name(),
        )
        return context
