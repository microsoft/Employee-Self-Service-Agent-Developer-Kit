"""ESS Migration Context — domain-specific extension of ExecutionContext."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.models import ExecutionContext
from modules.transformation.models.execution_mode import ExecutionMode


@dataclass
class MigrationContext(ExecutionContext):
    """ESS migration-specific execution context.

    Extends the base ``ExecutionContext`` (which carries the generic opaque
    ``mode`` string and diagnostic collectors) with ESS domain state.  The ESS
    domain gives ``mode`` its meaning via the ``ExecutionMode`` StrEnum and
    defaults it to ``READONLY``.  Migration-rule tasks add fields here
    (e.g. agent metadata, customizations) as they land.

    All ESS migration steps operate on this type via ``MigrationPipelineStep``.
    """

    mode: str = ExecutionMode.READONLY
    tid: str | None = None
    oid: str | None = None
    upn: str | None = None
    environment_url: str | None = None
    preferred_solution: str | None = None
    selected_agent_id: str | None = None
    selected_agent_name: str | None = None
    selected_agent_schemaname: str | None = None
    ess_solution_unique_name: str | None = None
    dataverse_client: Any = field(default=None, repr=False)
    # Raw ``bots({botid})`` record for the selected agent (holds template +
    # configuration that migration rewrites for DA compatibility).
    agent_bot_record: dict[str, Any] | None = field(default=None, repr=False)
    # Raw ``{schema}.gpt.default`` botcomponent (its ``data`` YAML holds the
    # aISettings.model kind that migration rewrites to MicrosoftCopilotModels).
    agent_gpt_component: dict[str, Any] | None = field(default=None, repr=False)
    # Raw dependencies-for-uninstall response captured during discovery.
    raw_dependencies: Any = field(default=None, repr=False)
    # All component layers fetched for the dependent components (raw).
    component_layers: list[dict[str, Any]] = field(default_factory=list, repr=False)
    # Filtered customization layers (one winning layer per truly-customized
    # component) that propagate to the migration/output modules.
    customizations: list[dict[str, Any]] = field(default_factory=list, repr=False)
    # Writeback payloads produced by the transformation module and applied by the
    # output module. Each entry: {"entity_set", "record_id", "changes"}.
    pending_writes: list[dict[str, Any]] = field(default_factory=list, repr=False)
