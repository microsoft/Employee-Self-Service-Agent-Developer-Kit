"""Discover ESS agents in the selected Dataverse environment."""

from __future__ import annotations

from typing import Any

from constants import SUPPORTED_MODES
from core.logging import Logger
from modules.migration.migration_step import MigrationPipelineStep
from modules.migration.models import MigrationContext


class AgentSelectionStep(MigrationPipelineStep):
    """Query Dataverse for agents, prompt for a selection, and store it."""

    def __init__(self, logger: Logger) -> None:
        super().__init__(
            description="Discover available ESS agents and select the migration target.",
            supported_modes=SUPPORTED_MODES,
        )
        self._logger = logger

    def execute(self, context: MigrationContext) -> MigrationContext:
        if context.dataverse_client is None:
            raise RuntimeError("Dataverse client is not initialized.")

        agents = sorted(
            context.dataverse_client.query_all("bots", select="name,botid,statecode"),
            key=_agent_sort_key,
        )
        if not agents:
            raise RuntimeError("No ESS agents were found in the selected environment.")

        self._logger.LogInfo(
            "Available ESS agents:",
            pipeline_stage="Input",
            pipeline_step=self.name(),
        )
        for index, agent in enumerate(agents, start=1):
            self._logger.LogInfo(
                _format_agent(index, agent),
                pipeline_stage="Input",
                pipeline_step=self.name(),
            )

        selection = _prompt_for_selection(len(agents))
        selected = agents[selection - 1]
        context.selected_agent_id = _string_field(selected, "botid")
        context.selected_agent_name = _string_field(selected, "name")

        self._logger.LogInfo(
            f"Selected agent {context.selected_agent_name or '(unnamed agent)'}.",
            pipeline_stage="Input",
            pipeline_step=self.name(),
        )
        return context


def _agent_sort_key(agent: dict[str, Any]) -> tuple[str, str]:
    return (_string_field(agent, "name") or "", _string_field(agent, "botid") or "")


def _format_agent(index: int, agent: dict[str, Any]) -> str:
    name = _string_field(agent, "name") or "(unnamed agent)"
    bot_id = _string_field(agent, "botid") or "(no id)"
    state = str(agent.get("statecode", "unknown"))
    return f"{index}. {name} [{bot_id}] state={state}"


def _prompt_for_selection(count: int) -> int:
    while True:
        choice = input(f"Select agent [1-{count}]: ").strip()
        if choice.isdigit():
            index = int(choice)
            if 1 <= index <= count:
                return index


def _string_field(record: dict[str, Any], field_name: str) -> str | None:
    value = record.get(field_name)
    return value if isinstance(value, str) and value else None
