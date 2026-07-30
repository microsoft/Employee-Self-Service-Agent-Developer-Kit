"""Output Pipeline builder."""

from __future__ import annotations

from core.logging import Logger
from core.pipelines import Pipeline
from modules.postprocessing.steps import (
    GenerateMigrationReportStep,
    ValidateMigrationStep,
    WritebackStep,
)
from modules.transformation.models import MigrationContext


def build_output_pipeline(
    logger: Logger, supported_modes: tuple[str, ...]
) -> Pipeline[MigrationContext, MigrationContext]:
    """Build the output stage pipeline."""
    del supported_modes
    return (
        Pipeline.builder("Output Pipeline", input_type=MigrationContext)
        .use(ValidateMigrationStep(logger))
        .use(WritebackStep(logger))
        .use(GenerateMigrationReportStep(logger))
        .build()
    )
