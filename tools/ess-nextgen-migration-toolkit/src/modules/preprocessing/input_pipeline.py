"""Input Pipeline builder."""

from __future__ import annotations

from core.logging import Logger
from core.pipelines import Pipeline
from modules.preprocessing.steps import (
    AgentSelectionStep,
    GatherALMCustomerInputStep,
    GatherInputWithAuthStep,
    RetrieveAgentConfigurationStep,
    RetrieveCustomizationsStep,
)
from modules.transformation.models import MigrationContext


def build_input_pipeline(
    logger: Logger,
    supported_modes: tuple[str, ...],
    *,
    is_dev_mode: bool = False,
) -> Pipeline[MigrationContext, MigrationContext]:
    """Build the input stage pipeline."""
    return (
        Pipeline.builder("Input Pipeline", input_type=MigrationContext)
        .use(GatherInputWithAuthStep(logger, supported_modes, is_dev_mode=is_dev_mode))
        .use(AgentSelectionStep(logger, supported_modes))
        .use(GatherALMCustomerInputStep(logger, supported_modes))
        .use(RetrieveAgentConfigurationStep(logger, supported_modes))
        .use(RetrieveCustomizationsStep(logger, supported_modes))
        .build()
    )
