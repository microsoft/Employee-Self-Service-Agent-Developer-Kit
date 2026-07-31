"""Fetch the selected agent's bot record and gpt.default botcomponent.

These are the base agent artifacts the migration module rewrites for DA
compatibility as its very first step:

- ``bots({botid})`` — carries ``template`` (``default-2.1.0`` -> ``gptagent-1.0.0``)
  and the configuration blob (``recognizer/aISettings.model`` gains a
  ``MicrosoftCopilotModels`` kind).
- ``{schema}.gpt.default`` botcomponent — its ``data`` YAML carries
  ``aISettings.model.kind: PreviewModels`` (-> ``MicrosoftCopilotModels``).

Both are stored raw on the ``MigrationContext`` and propagate downstream.
"""

from __future__ import annotations

from typing import Any

from core.logging import Logger
from modules.transformation.migration_step import MigrationPipelineStep
from modules.transformation.models import MigrationContext

_BOTS_ENTITY = "bots"
_BOTCOMPONENTS_ENTITY = "botcomponents"
_GPT_DEFAULT_SUFFIX = ".gpt.default"


class RetrieveAgentConfigurationStep(MigrationPipelineStep):
    """Fetch the bot record + gpt.default component for the selected agent."""

    def __init__(self, logger: Logger, supported_modes: tuple[str, ...]) -> None:
        super().__init__(
            description="Retrieve the selected agent's configuration and metadata.",
            supported_modes=supported_modes,
        )
        self._logger = logger

    def execute(self, context: MigrationContext) -> MigrationContext:
        if context.dataverse_client is None:
            raise RuntimeError("Dataverse client is not initialized.")
        if not context.selected_agent_id:
            raise RuntimeError("No agent id is available on the context.")
        if not context.selected_agent_schemaname:
            raise RuntimeError("No agent schemaname is available on the context.")

        client = context.dataverse_client

        # Full bot record (all fields) — includes template + configuration.
        context.agent_bot_record = client.get(f"{_BOTS_ENTITY}({context.selected_agent_id})")
        self._logger.LogInfo(
            f"Fetched bot record for agent id {context.selected_agent_id}.",
            pipeline_stage="Input",
            pipeline_step=self.name(),
        )

        gpt_schemaname = f"{context.selected_agent_schemaname}{_GPT_DEFAULT_SUFFIX}"
        gpt_components = client.query_all(
            _BOTCOMPONENTS_ENTITY,
            select=None,
            filter=f"schemaname eq '{gpt_schemaname}'",
        )
        context.agent_gpt_component = _first(gpt_components)
        if context.agent_gpt_component is None:
            self._logger.LogWarning(
                f"No gpt.default botcomponent found for schemaname '{gpt_schemaname}'.",
                pipeline_stage="Input",
                pipeline_step=self.name(),
            )
        else:
            self._logger.LogInfo(
                f"Fetched gpt.default botcomponent '{gpt_schemaname}'.",
                pipeline_stage="Input",
                pipeline_step=self.name(),
            )
        return context


def _first(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    return records[0] if records else None
