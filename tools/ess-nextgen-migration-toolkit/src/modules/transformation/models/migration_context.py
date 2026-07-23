"""ESS Migration Context — domain-specific extension of ExecutionContext."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.models import ExecutionContext
from modules.transformation.models.customization_component import CustomizationComponent
from modules.transformation.models.execution_mode import ExecutionMode
from modules.transformation.models.writeback_plan import WritebackPlan


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
    # All ESS agents discovered in the environment during selection (lightweight
    # dicts: name/botid/statecode/schemaname), retained for the migration report.
    discovered_agents: list[dict[str, Any]] = field(default_factory=list, repr=False)
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
    # All component layers fetched for the dependent components, keyed by
    # msdyn_componentid -> that component's list of layer records (raw).
    component_layers: dict[str, list[dict[str, Any]]] = field(default_factory=dict, repr=False)
    # Customized components the toolkit migrates — the subset of component_layers
    # that are customer changes (>1 layer, or a single non-OOB layer) of a migrated
    # sub-type (Topic V2) owned by an ESS HR/IT agent. Keyed by msdyn_componentid
    # -> a hydrated CustomizationComponent (top-level schemaname/name/type/data plus
    # its raw layers). Propagates to the migration/output modules.
    customizations: dict[str, CustomizationComponent] = field(default_factory=dict, repr=False)
    # The raw_dependencies metadata infos for the customized components only —
    # each DependencyMetadataInfoCollection entry whose dependentcomponentobjectid
    # is a customization. Carries the richer dependency metadata for those.
    customized_dependencies: list[dict[str, Any]] = field(default_factory=list, repr=False)
    # Coalescing, no-op-guarded accumulator for writeback. Transformation steps
    # stage field edits here (per record); ``pending_writes`` derives the writes.
    writeback: WritebackPlan = field(default_factory=WritebackPlan, repr=False)

    @property
    def pending_writes(self) -> list[dict[str, Any]]:
        """Writeback payloads for the output module, derived from ``writeback``.

        Each entry is ``{"entity_set", "record_id", "changes"}``, coalesced to one
        per record and containing only fields that genuinely changed (so an
        unchanged record produces no write — no needless overlay).
        """
        return self.writeback.pending_writes()
