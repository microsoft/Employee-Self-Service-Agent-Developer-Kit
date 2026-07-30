"""Retrieve customization dependencies + component layers for the selected agent.

Discovery slice:
1. Resolve the ESS base solution for the selected agent's vertical, then look up
   its ``solutionid`` (GUID).
2. Call ``RetrieveDependenciesForUninstallWithMetadata(SolutionId=<guid>)`` to
   list the dependent components layered on top of the ESS base solution, keeping
   each ``(dependentcomponentobjectid, dependentcomponententitylogicalname)``.
3. Fetch ``msdyn_componentlayers`` one component at a time — the virtual table
   resolves a single ``msdyn_componentid`` paired with its
   ``msdyn_solutioncomponentname`` (OR-ing multiple ids silently drops all but a
   couple), so we issue one query per component and collate the results — then
   classify each component by its layers:

   - **customized OOB** — more than one layer (a managed OOB base plus an
     overlay) → keep.
   - **net-new** — a single layer in a non-OOB solution (e.g. the unmanaged
     ``Active`` layer) → keep.
   - **untouched OOB** — a single layer in an OOB ESS managed solution → drop.

   Kept components are then narrowed to migratable ones: the migrated sub-types
   (``ALLOWED_BOT_COMPONENT_TYPES`` — Topic V2 for now) whose schemaname carries
   an ESS HR/IT agent prefix (``ESS_AGENT_SCHEMANAMES``). Other componenttypes
   (Test Case, Knowledge Source, ...) and other agents' components (e.g. the
   shared ``...core`` agent) are dropped. Each kept component is hydrated into a
   ``CustomizationComponent`` (top-level schemaname/name/componenttype/data plus
   its raw layers).

Only the filtered customization layers propagate to the migration/output
modules via the ``MigrationContext``.

ALM preferred-solution scoping
------------------------------
When the customer declares a **preferred solution** (``context.preferred_solution``,
an unmanaged solution they imported and marked preferred, whose topics are
customizations on top of the managed ESS base), discovery is narrowed to the
components that *belong to that solution*. Unmanaged solutions all share the single
``Active`` layer, so membership can't be read off the component layers (which show
``Active``); it comes from the solution's ``solutioncomponents`` (one row per
contained component, by ``objectid``). This lets an ALM customer run the tool once
per preferred solution and have writeback/transformations touch only that solution's
customizations. With no preferred solution, every discovered customization is kept.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.logging import Logger
from modules.transformation.migration_step import MigrationPipelineStep
from modules.transformation.models import CustomizationComponent, MigrationContext
from service.constants import (
    ALLOWED_BOT_COMPONENT_TYPES,
    BOT_COMPONENT_TYPE_LABELS,
    ESS_AGENT_SCHEMANAMES,
    OOB_ESS_SOLUTIONS,
)
from service.utils import resolve_ess_solution

_DEPENDENCIES_FUNCTION = "RetrieveDependenciesForUninstallWithMetadata"
_SOLUTIONS_ENTITY = "solutions"
# The customer's preferred solution's membership — one solutioncomponent row per
# component the solution contains, joined to the component by ``objectid``. Used to
# scope discovery to the preferred solution (ALM path); the guid filter on the
# ``solutionid`` lookup uses the unquoted ``_solutionid_value`` form.
_SOLUTION_COMPONENTS_ENTITY = "solutioncomponents"
_SOLUTIONCOMPONENT_OBJECT_ID = "objectid"
_SOLUTION_ID_VALUE_FIELD = "_solutionid_value"
_COMPONENT_LAYERS_ENTITY = "msdyn_componentlayers"
# The msdyn_componentlayer virtual table needs the component's source-table name
# (msdyn_solutioncomponentname) to resolve a component; without it the query
# returns empty. We take it per component from the dependency metadata's
# ``dependentcomponententitylogicalname`` (e.g. "botcomponent", "bot").
_OBJECT_ID_FIELD = "dependentcomponentobjectid"
_ENTITY_NAME_FIELD = "dependentcomponententitylogicalname"
_EMPTY_GUID = "00000000-0000-0000-0000-000000000000"
# A component's layers each name the solution they belong to. A lone layer in an
# OOB ESS managed solution (service.constants.OOB_ESS_SOLUTIONS) is untouched OOB;
# a layer in any other solution (e.g. the unmanaged "Active" layer, which reads a
# ~1900 overwritetime even for net-new topics) signals a customer customization.
_SOLUTION_NAME_FIELD = "msdyn_solutionname"
# A layer's componenttype (botcomponent sub-type) lives inside msdyn_componentjson,
# a JSON string with an ``Attributes`` list of ``{"Key", "Value"}`` pairs. The
# componenttype pair's value is itself ``{"Value": <int>}``.
_COMPONENT_JSON_FIELD = "msdyn_componentjson"
_ATTRIBUTES_KEY = "Attributes"
_COMPONENT_TYPE_KEY = "componenttype"
_SCHEMANAME_KEY = "schemaname"
_NAME_KEY = "name"
_DATA_KEY = "data"
_STATECODE_KEY = "statecode"
_STATUSCODE_KEY = "statuscode"
# Pre-writeback snapshot of the in-scope customizations, written into the session
# bundle so the original topic definitions (``data`` YAML) are captured before any
# transformation/writeback — an internal recovery aid for worst-case incidents.
_CUSTOMIZATIONS_FILENAME = "customizations.json"


class RetrieveCustomizationsStep(MigrationPipelineStep):
    """Fetch uninstall dependencies, then classify customization layers."""

    def __init__(self, logger: Logger, supported_modes: tuple[str, ...]) -> None:
        super().__init__(
            description="Retrieve customization dependencies for the selected ESS agent.",
            supported_modes=supported_modes,
        )
        self._logger = logger

    def execute(self, context: MigrationContext) -> MigrationContext:
        if context.dataverse_client is None:
            raise RuntimeError("Dataverse client is not initialized.")
        if not context.selected_agent_schemaname:
            raise RuntimeError("No agent schemaname is available on the context.")

        solution_unique_name = resolve_ess_solution(context.selected_agent_schemaname)
        if solution_unique_name is None:
            raise RuntimeError(
                "Could not resolve an ESS base solution for agent schemaname "
                f"'{context.selected_agent_schemaname}'."
            )
        context.ess_solution_unique_name = solution_unique_name

        # RetrieveDependenciesForUninstallWithMetadata takes a SolutionId (GUID),
        # not the unique name — resolve it from the solutions table.
        solution_id = _resolve_solution_id(context.dataverse_client, solution_unique_name)

        self._logger.LogInfo(
            f"Retrieving customization dependencies for solution "
            f"'{solution_unique_name}' ({solution_id}).",
            pipeline_stage="Input",
            pipeline_step=self.name(),
        )

        response = context.dataverse_client.call_function(
            _DEPENDENCIES_FUNCTION,
            SolutionId=solution_id,
        )
        context.raw_dependencies = response

        dependents = _extract_dependents(response)
        self._logger.LogInfo(
            f"Found {len(dependents)} dependent component(s); fetching component layers.",
            pipeline_stage="Input",
            pipeline_step=self.name(),
        )

        layers_by_component = self._fetch_component_layers(context.dataverse_client, dependents)
        context.component_layers = layers_by_component

        customizations = _select_customizations(layers_by_component)
        customizations = self._narrow_to_preferred_solution(context, customizations)
        context.customizations = customizations
        context.customized_dependencies = _customized_dependencies(response, customizations)
        self._write_customizations_snapshot(customizations)

        total_layers = sum(len(layers) for layers in layers_by_component.values())
        self._logger.LogInfo(
            f"Classified {len(customizations)} customization(s) from "
            f"{total_layers} layer record(s) across {len(layers_by_component)} component(s).",
            pipeline_stage="Input",
            pipeline_step=self.name(),
        )
        return context

    def _fetch_component_layers(
        self, client: Any, dependents: list[tuple[str, str]]
    ) -> dict[str, list[dict[str, Any]]]:
        # One query per component id, each carrying its own
        # msdyn_solutioncomponentname (required by the virtual table, which won't
        # OR multiple ids). Keep each component's layers under its id so the
        # per-component layer set stays intact for classification.
        layers_by_component: dict[str, list[dict[str, Any]]] = {}
        for object_id, entity_name in dependents:
            # Fetch all fields (includes msdyn_componentjson) so downstream
            # modules have the full component payload to transform + write back.
            layers_by_component[object_id] = client.query_all(
                _COMPONENT_LAYERS_ENTITY,
                select=None,
                filter=_layer_filter(object_id, entity_name),
            )
        return layers_by_component

    def _narrow_to_preferred_solution(
        self,
        context: MigrationContext,
        customizations: dict[str, CustomizationComponent],
    ) -> dict[str, CustomizationComponent]:
        """Scope customizations to the customer's preferred solution (ALM path).

        When the customer declares a preferred solution, migrate ONLY the components
        that belong to it — the topics they imported into that unmanaged, preferred
        solution as customizations on top of the managed ESS base. Membership comes
        from the solution's ``solutioncomponents`` (unmanaged solutions share the
        single ``Active`` layer, so it can't be read off the component layers). An
        ALM customer runs the tool once per preferred solution.

        With no preferred solution (non-ALM path), every discovered customization is
        kept unchanged.
        """
        preferred = context.preferred_solution
        if not preferred:
            return customizations

        member_ids = self._fetch_preferred_solution_component_ids(
            context.dataverse_client, preferred
        )
        kept = {
            component_id: component
            for component_id, component in customizations.items()
            if _norm_guid(component_id) in member_ids
        }
        self._logger.LogInfo(
            f"Preferred solution '{preferred}' scoping: kept {len(kept)} of "
            f"{len(customizations)} discovered customization(s) that belong to it "
            f"(dropped {len(customizations) - len(kept)} outside it).",
            pipeline_stage="Input",
            pipeline_step=self.name(),
        )
        return kept

    def _fetch_preferred_solution_component_ids(self, client: Any, unique_name: str) -> set[str]:
        """Return the normalized object-ids of components in the preferred solution.

        Resolves the preferred solution's ``solutionid`` from its unique name, then
        reads its ``solutioncomponents`` — one row per contained component —
        collecting each ``objectid`` (the component's id), normalized for matching
        against the discovered customization ids.

        Confirmed live: a Copilot topic is its own ``solutioncomponents`` row with
        ``objectid`` == its ``botcomponentid`` and ``componenttype`` 10213
        (``botcomponent``), so matching customization ids against ``objectid`` holds.
        """
        solution_id = _resolve_solution_id(client, unique_name)
        rows = client.query_all(
            _SOLUTION_COMPONENTS_ENTITY,
            select=_SOLUTIONCOMPONENT_OBJECT_ID,
            filter=f"{_SOLUTION_ID_VALUE_FIELD} eq {solution_id}",
        )
        return {
            _norm_guid(object_id)
            for row in rows
            if isinstance(row, dict)
            and isinstance((object_id := row.get(_SOLUTIONCOMPONENT_OBJECT_ID)), str)
            and object_id
        }

    def _write_customizations_snapshot(
        self, customizations: dict[str, CustomizationComponent]
    ) -> None:
        """Write a pre-writeback snapshot of the in-scope customizations to the bundle.

        Captures each in-scope topic's **original** definition (its ``data`` YAML plus
        identity/state) into ``customizations.json`` in the session folder, *before* any
        transformation or writeback runs. This is an internal engineering/recovery aid:
        if a run needs to be reverted manually (e.g. a customer incident), the original
        topic YAML can be read back from here. It is written early (input stage) so it
        survives even a later partial failure. Best-effort — never fails the run.
        """
        session_dir = self._session_dir()
        if session_dir is None:
            return
        try:
            path = session_dir / _CUSTOMIZATIONS_FILENAME
            path.write_text(
                json.dumps(_customizations_snapshot(customizations), indent=2),
                encoding="utf-8",
            )
            self._logger.LogInfo(
                f"Captured {len(customizations)} customization(s) to {path.name}.",
                pipeline_stage="Input",
                pipeline_step=self.name(),
            )
        except OSError as exc:
            self._logger.LogWarning(
                f"Could not write {_CUSTOMIZATIONS_FILENAME}: {exc}",
                pipeline_stage="Input",
                pipeline_step=self.name(),
            )

    def _session_dir(self) -> Path | None:
        """The active session bundle directory, or None when unavailable (e.g. tests)."""
        manager = getattr(self._logger, "session_manager", None)
        paths = getattr(manager, "paths", None)
        session_dir = getattr(paths, "session_dir", None)
        return session_dir if isinstance(session_dir, Path) else None


def _customizations_snapshot(
    customizations: dict[str, CustomizationComponent],
) -> dict[str, dict[str, Any]]:
    """Focused, pre-writeback view of each in-scope customization (original data).

    Excludes the raw ``layers`` (verbose Dataverse records) — the recoverable content
    is the original ``data`` (topic YAML) plus identity/state fields.
    """
    return {
        component_id: {
            "component_id": component.component_id,
            "schemaname": component.schemaname,
            "name": component.name,
            "component_type": component.component_type,
            "component_type_label": component.component_type_label,
            "statecode": component.statecode,
            "statuscode": component.statuscode,
            "data": component.data,
        }
        for component_id, component in customizations.items()
    }


def _norm_guid(value: str) -> str:
    """Normalize a Dataverse guid string for id matching (case/brace-insensitive)."""
    return value.strip().strip("{}").lower()


def _resolve_solution_id(client: Any, unique_name: str) -> str:
    """Resolve a solution's ``solutionid`` (GUID) from its unique name.

    ``RetrieveDependenciesForUninstallWithMetadata`` takes a ``SolutionId``
    (Edm.Guid), so the ESS base solution's unique name must be resolved to its id.
    """
    rows = client.query_all(
        _SOLUTIONS_ENTITY,
        select="solutionid",
        filter=f"uniquename eq '{unique_name}'",
    )
    for row in rows:
        if isinstance(row, dict):
            solution_id = row.get("solutionid")
            if isinstance(solution_id, str) and solution_id:
                return solution_id
    raise RuntimeError(
        f"ESS solution '{unique_name}' was not found in this environment "
        "(no matching row in 'solutions')."
    )


def _extract_dependents(response: Any) -> list[tuple[str, str]]:
    """Return unique ``(objectid, entity_logical_name)`` dependent components.

    Skips the all-zero GUID and any entry missing an object id or the entity
    logical name (needed to resolve the component layer).
    """
    infos = _dependency_infos(response)
    seen: set[str] = set()
    dependents: list[tuple[str, str]] = []
    for info in infos:
        if not isinstance(info, dict):
            continue
        object_id = info.get(_OBJECT_ID_FIELD)
        entity_name = info.get(_ENTITY_NAME_FIELD)
        if (
            isinstance(object_id, str)
            and object_id
            and object_id != _EMPTY_GUID
            and isinstance(entity_name, str)
            and entity_name
            and object_id not in seen
        ):
            seen.add(object_id)
            dependents.append((object_id, entity_name))
    return dependents


def _dependency_infos(response: Any) -> list[Any]:
    if not isinstance(response, dict):
        return []
    collection = response.get("DependencyMetadataCollection")
    if not isinstance(collection, dict):
        return []
    infos = collection.get("DependencyMetadataInfoCollection")
    return infos if isinstance(infos, list) else []


def _customized_dependencies(
    response: Any, customizations: dict[str, CustomizationComponent]
) -> list[dict[str, Any]]:
    """Return the raw dependency infos whose component was classified customized.

    Filters ``raw_dependencies`` down to the ``DependencyMetadataInfoCollection``
    entries whose ``dependentcomponentobjectid`` is a key in ``customizations``,
    preserving the original order (and any duplicates) from the response.
    """
    return [
        info
        for info in _dependency_infos(response)
        if isinstance(info, dict) and info.get(_OBJECT_ID_FIELD) in customizations
    ]


def _select_customizations(
    layers_by_component: dict[str, list[dict[str, Any]]],
) -> dict[str, CustomizationComponent]:
    """Return the migratable customized components, hydrated for downstream use.

    Each component's ``msdyn_componentlayers`` query returns one row per solution
    layer, and each row names its solution (``msdyn_solutionname``). A component
    (keyed by ``msdyn_componentid``) is kept when it is both customized AND
    migratable, and is hydrated into a :class:`CustomizationComponent` (top-level
    schemaname/name/componenttype/data plus its raw layers):

    - **Customized** — more than one layer (a managed OOB base plus an overlay),
      or a lone layer in a non-OOB solution (e.g. the unmanaged ``Active`` layer
      of a net-new component). A lone layer in an OOB ESS managed solution
      (``service.constants.OOB_ESS_SOLUTIONS``) is untouched OOB and is dropped.
    - **Migratable** — its componenttype is in
      ``service.constants.ALLOWED_BOT_COMPONENT_TYPES`` (Topic V2 for now) AND its
      schemaname contains an ESS HR/IT agent prefix
      (``service.constants.ESS_AGENT_SCHEMANAMES``). Other sub-types (Test Case,
      Knowledge Source, ...) and components owned by other agents (e.g. the shared
      ``...core`` agent) are dropped.

    Only the kept components propagate to the migration/output modules.
    """
    customizations: dict[str, CustomizationComponent] = {}
    for component_id, layers in layers_by_component.items():
        if not _is_customized(layers):
            continue
        attributes = _component_attributes(layers)
        if not _is_migratable(attributes):
            continue
        customizations[component_id] = _hydrate_component(component_id, layers, attributes)
    return customizations


def _is_customized(layers: list[dict[str, Any]]) -> bool:
    """A component is customized if it has multiple layers, or a single non-OOB layer.

    More than one layer means a managed OOB base plus an overlay. A lone layer
    counts as a customization unless it belongs to an OOB ESS managed solution
    (the untouched base); anything else — including the unmanaged ``Active`` layer
    of a net-new component — is a customer change.
    """
    if len(layers) > 1:
        return True
    return any(layer.get(_SOLUTION_NAME_FIELD) not in OOB_ESS_SOLUTIONS for layer in layers)


def _is_migratable(attributes: dict[str, Any]) -> bool:
    """Whether the component is an allow-listed sub-type owned by an ESS HR/IT agent."""
    return _component_type(attributes) in ALLOWED_BOT_COMPONENT_TYPES and _has_ess_agent_schemaname(
        attributes
    )


def _hydrate_component(
    component_id: str, layers: list[dict[str, Any]], attributes: dict[str, Any]
) -> CustomizationComponent:
    """Build a hydrated ``CustomizationComponent`` from a component's attributes."""
    component_type = _component_type(attributes)
    label = BOT_COMPONENT_TYPE_LABELS.get(component_type) if component_type is not None else None
    return CustomizationComponent(
        component_id=component_id,
        schemaname=_attr_str(attributes, _SCHEMANAME_KEY),
        name=_attr_str(attributes, _NAME_KEY),
        component_type=component_type,
        component_type_label=label,
        data=_attr_str(attributes, _DATA_KEY),
        statecode=_attr_int(attributes, _STATECODE_KEY),
        statuscode=_attr_int(attributes, _STATUSCODE_KEY),
        layers=layers,
    )


def _component_type(attributes: dict[str, Any]) -> int | None:
    return _attr_int(attributes, _COMPONENT_TYPE_KEY)


def _attr_int(attributes: dict[str, Any], key: str) -> int | None:
    """Read an int attribute whose value is wrapped as ``{"Value": <int>}``."""
    value = attributes.get(key)
    inner = value.get("Value") if isinstance(value, dict) else None
    return inner if isinstance(inner, int) else None


def _attr_str(attributes: dict[str, Any], key: str) -> str | None:
    value = attributes.get(key)
    return value if isinstance(value, str) else None


def _has_ess_agent_schemaname(attributes: dict[str, Any]) -> bool:
    schemaname = attributes.get(_SCHEMANAME_KEY)
    if not isinstance(schemaname, str):
        return False
    lowered = schemaname.lower()
    return any(prefix in lowered for prefix in ESS_AGENT_SCHEMANAMES)


def _component_attributes(layers: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the botcomponent ``Attributes`` (Key -> Value) for a component.

    All of a component's layers describe the same component, so the first layer
    with a parseable ``msdyn_componentjson`` carrying an ``Attributes`` list wins.
    Returns an empty dict when none can be parsed.
    """
    for layer in layers:
        raw = layer.get(_COMPONENT_JSON_FIELD)
        if not isinstance(raw, str):
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        attributes = parsed.get(_ATTRIBUTES_KEY) if isinstance(parsed, dict) else None
        if not isinstance(attributes, list):
            continue
        return {
            attribute["Key"]: attribute.get("Value")
            for attribute in attributes
            if isinstance(attribute, dict) and isinstance(attribute.get("Key"), str)
        }
    return {}


def _layer_filter(component_id: str, solution_component_name: str) -> str:
    """Build the msdyn_componentlayers $filter for a single component.

    Pairs the ``msdyn_componentid`` with the required
    ``msdyn_solutioncomponentname`` (the component's entity logical name) — the
    virtual table needs it to resolve the component, so an id-only filter is empty,
    and it resolves only one id at a time (OR-ing ids drops all but a couple).
    """
    return (
        f"msdyn_componentid eq '{component_id}'"
        f" and msdyn_solutioncomponentname eq '{solution_component_name}'"
    )
