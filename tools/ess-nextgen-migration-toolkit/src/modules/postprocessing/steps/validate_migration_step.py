"""Validate output-stage postconditions before writeback/reporting."""

from __future__ import annotations

from typing import Any

from core.logging import Logger
from modules.transformation.migration_step import MigrationPipelineStep
from modules.transformation.models import MigrationContext

_SUPPORTED_MODES = ("READONLY", "WRITEBACK")


class MigrationValidationError(ValueError):
    """Raised when migrated output state fails postcondition validation."""


class ValidateMigrationStep(MigrationPipelineStep):
    """Verify pending writeback entries are well-formed before persistence."""

    def __init__(self, logger: Logger) -> None:
        super().__init__(
            name="ValidateMigration",
            description="Validate migrated output postconditions.",
            supported_modes=_SUPPORTED_MODES,
        )
        self._logger = logger

    def execute(self, context: MigrationContext) -> MigrationContext:
        pending_writes = context.pending_writes
        for index, pending_write in enumerate(pending_writes):
            _validate_pending_write(pending_write, index)

        self._logger.LogInfo(
            f"Validated {len(pending_writes)} pending write(s).",
            pipeline_stage="Output",
            pipeline_step=self.name(),
        )
        return context


def _validate_pending_write(pending_write: dict[str, Any], index: int) -> None:
    entity_set = pending_write.get("entity_set")
    if not isinstance(entity_set, str) or not entity_set:
        raise MigrationValidationError(f"Pending write #{index + 1} has no entity_set.")

    record_id = pending_write.get("record_id")
    if not isinstance(record_id, str) or not record_id:
        raise MigrationValidationError(f"Pending write #{index + 1} has no record_id.")

    changes = pending_write.get("changes")
    if not isinstance(changes, dict) or not changes:
        raise MigrationValidationError(f"Pending write #{index + 1} has no changes.")
