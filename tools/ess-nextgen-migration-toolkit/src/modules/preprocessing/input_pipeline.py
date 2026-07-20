"""Input Pipeline builder."""

from __future__ import annotations

from core.logging import Logger
from core.pipelines import Pipeline
from modules.migration.models import MigrationContext
from modules.preprocessing.steps import (
    AgentSelectionStep,
    GatherInputWithAuthStep,
    GatherPreferredSolutionStep,
)


def build_input_pipeline(logger: Logger) -> Pipeline[MigrationContext, MigrationContext]:
    """Build the input stage pipeline."""
    return (
        Pipeline.builder("Input Pipeline", input_type=MigrationContext)
        .use(GatherInputWithAuthStep(logger))
        .use(AgentSelectionStep(logger))
        .use(GatherPreferredSolutionStep(logger))
        .build()
    )
