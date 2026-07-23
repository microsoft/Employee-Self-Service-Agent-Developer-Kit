"""Transformation Pipeline builder."""

from __future__ import annotations

from core.logging import Logger
from core.pipelines import Pipeline
from modules.transformation.models import MigrationContext
from modules.transformation.steps import (
    ApplyDaCompatibilityStep,
    HandleAnswerQuestionWithAINodeStep,
    HandleConversationHistoryNodeStep,
    HandleGeneratedResponseTopicStep,
    HandleIncludeSelectedTopicsNodeStep,
    HandleInvokeAIBuilderModelActionNodeStep,
    HandleOnActivityTopicStep,
    HandleOnEscalateTopicStep,
    HandleOnPlanCompleteTopicStep,
    HandleOnSelectIntentTopicStep,
    HandleOnSystemRedirectTopicStep,
    HandleOnUnknownIntentTopicStep,
    HandleRecognizeIntentNodeStep,
    HandleSearchAndSummarizeContentNodeStep,
    HandleTransferConversationV2NodeStep,
    ReplaceEndConversationStep,
)


def build_transformation_pipeline(
    logger: Logger, supported_modes: tuple[str, ...]
) -> Pipeline[MigrationContext, MigrationContext]:
    """Build the transformation stage pipeline (one step per migration rule)."""
    return (
        Pipeline.builder("Transformation Pipeline", input_type=MigrationContext)
        .use(ApplyDaCompatibilityStep(logger, supported_modes))
        # RULE-002 — replace unsupported node in-place
        .use(ReplaceEndConversationStep(logger))
        # RULE-003 / RULE-004 — ESS-OOB unsupported triggers
        .use(HandleOnActivityTopicStep(logger))
        .use(HandleGeneratedResponseTopicStep(logger))
        # RULE-006 — additional unsupported triggers
        .use(HandleOnUnknownIntentTopicStep(logger))
        .use(HandleOnPlanCompleteTopicStep(logger))
        .use(HandleOnSystemRedirectTopicStep(logger))
        .use(HandleOnSelectIntentTopicStep(logger))
        .use(HandleOnEscalateTopicStep(logger))
        # RULE-007 — unsupported nodes
        .use(HandleAnswerQuestionWithAINodeStep(logger))
        .use(HandleRecognizeIntentNodeStep(logger))
        .use(HandleSearchAndSummarizeContentNodeStep(logger))
        .use(HandleTransferConversationV2NodeStep(logger))
        .use(HandleConversationHistoryNodeStep(logger))
        .use(HandleInvokeAIBuilderModelActionNodeStep(logger))
        .use(HandleIncludeSelectedTopicsNodeStep(logger))
        .build()
    )
