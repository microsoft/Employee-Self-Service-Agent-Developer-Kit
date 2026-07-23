"""Transformation Pipeline builder."""

from __future__ import annotations

from core.logging import Logger
from core.pipelines import Pipeline
from modules.transformation.models import MigrationContext
from modules.transformation.steps import (
    ApplyDaCompatibilityStep,
    DisableUnsupportedNodeTopicsStep,
    DisableUnsupportedTriggerTopicsStep,
    HandleGeneratedResponseTopicStep,
    HandleOnActivityTopicStep,
    ReplaceEndConversationStep,
)


def build_transformation_pipeline(
    logger: Logger, supported_modes: tuple[str, ...]
) -> Pipeline[MigrationContext, MigrationContext]:
    """Build the transformation stage pipeline."""
    return (
        Pipeline.builder("Transformation Pipeline", input_type=MigrationContext)
        .use(ApplyDaCompatibilityStep(logger, supported_modes))
        .use(ReplaceEndConversationStep(logger))
        .use(HandleOnActivityTopicStep(logger))
        .use(HandleGeneratedResponseTopicStep(logger))
        .use(DisableUnsupportedTriggerTopicsStep(logger))
        .use(DisableUnsupportedNodeTopicsStep(logger))
        .build()
    )
