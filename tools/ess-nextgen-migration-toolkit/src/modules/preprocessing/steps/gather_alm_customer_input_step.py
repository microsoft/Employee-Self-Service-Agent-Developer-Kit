"""Capture and verify the optional preferred solution for writeback."""

from __future__ import annotations

from typing import Any

from core.logging import Logger
from modules.transformation.migration_step import MigrationPipelineStep
from modules.transformation.models import MigrationContext

_GET_PREFERRED_SOLUTION_FUNCTION = "GetPreferredSolution"


class GatherALMCustomerInputStep(MigrationPipelineStep):
    """Prompt for the optional preferred solution and cross-check it live.

    For ALM customers, writeback targets the customer's preferred solution. If
    the customer declares one, cross-check it against the environment's current
    preferred solution (``GetPreferredSolution``) so a typo can't silently point
    writeback at the wrong solution.
    """

    def __init__(self, logger: Logger, supported_modes: tuple[str, ...]) -> None:
        super().__init__(
            description="Capture and verify the optional preferred solution for writeback.",
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
            return context

        self._logger.LogInfo(
            f"Using preferred solution {context.preferred_solution}.",
            pipeline_stage="Input",
            pipeline_step=self.name(),
        )
        self._verify_preferred_solution(context, context.preferred_solution)
        return context

    def _verify_preferred_solution(self, context: MigrationContext, declared: str) -> None:
        if context.dataverse_client is None:
            raise RuntimeError("Dataverse client is not initialized.")

        response = context.dataverse_client.call_function(_GET_PREFERRED_SOLUTION_FUNCTION)
        current = _extract_unique_name(response)
        if current is None:
            self._logger.LogWarning(
                "Could not read the environment's current preferred solution from "
                "GetPreferredSolution; skipping cross-check.",
                pipeline_stage="Input",
                pipeline_step=self.name(),
            )
            return

        if current.casefold() != declared.casefold():
            raise RuntimeError(
                "Preferred solution mismatch: you entered "
                f"'{declared}' but the environment's current preferred solution is "
                f"'{current}'. Set the correct preferred solution before migrating."
            )

        self._logger.LogInfo(
            f"Verified preferred solution '{current}' matches the environment.",
            pipeline_stage="Input",
            pipeline_step=self.name(),
        )


def _extract_unique_name(response: Any) -> str | None:
    """Return the preferred solution's ``uniquename`` from the function response."""
    if not isinstance(response, dict):
        return None
    value = response.get("uniquename")
    return value if isinstance(value, str) and value else None
