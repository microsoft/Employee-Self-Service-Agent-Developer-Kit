"""Apply coalesced pending writes to Dataverse."""

from __future__ import annotations

from typing import Any, cast

from core.logging import Logger
from modules.transformation.migration_step import MigrationPipelineStep
from modules.transformation.models import MigrationContext

_SOLUTION_UNIQUE_NAME_HEADER = "MSCRM.SolutionUniqueName"


class WritebackError(RuntimeError):
    """Raised when output writeback cannot be executed."""


class WritebackStep(MigrationPipelineStep):
    """Persist ``context.pending_writes`` in WRITEBACK mode."""

    def __init__(self, logger: Logger) -> None:
        super().__init__(
            name="Writeback",
            description="Apply pending Dataverse writes.",
            supported_modes=("WRITEBACK",),
        )
        self._logger = logger

    def execute(self, context: MigrationContext) -> MigrationContext:
        pending_writes = context.pending_writes
        if not pending_writes:
            self._logger.LogInfo(
                "No pending writes to apply.",
                pipeline_stage="Output",
                pipeline_step=self.name(),
            )
            return context

        client = context.dataverse_client
        if client is None:
            raise WritebackError("Dataverse client is not initialized.")

        solution_headers = _solution_headers(context.preferred_solution)
        for pending_write in pending_writes:
            entity_set = cast(str, pending_write["entity_set"])
            record_id = cast(str, pending_write["record_id"])
            changes = cast(dict[str, Any], pending_write["changes"])
            if solution_headers is None:
                client.update(entity_set, record_id, changes)
            else:
                client.update(entity_set, record_id, changes, headers=solution_headers)

        self._logger.LogInfo(
            f"Applied {len(pending_writes)} pending write(s) to Dataverse.",
            pipeline_stage="Output",
            pipeline_step=self.name(),
        )
        return context


def _solution_headers(preferred_solution: str | None) -> dict[str, str] | None:
    if not preferred_solution:
        return None
    return {_SOLUTION_UNIQUE_NAME_HEADER: preferred_solution}
