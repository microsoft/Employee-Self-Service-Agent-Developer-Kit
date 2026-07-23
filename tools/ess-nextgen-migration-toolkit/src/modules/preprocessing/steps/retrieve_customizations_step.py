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
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
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
# TEMP debug aid (remove later): dump the filtered customizations to .local so the
# maker can navigate them. .local is gitignored; skipped under pytest.
_TOOLKIT_ROOT = Path(__file__).resolve().parents[4]
_CUSTOMIZATIONS_DUMP_PATH = _TOOLKIT_ROOT / ".local" / "customizations.json"


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
        context.customizations = customizations
        context.customized_dependencies = _customized_dependencies(response, customizations)
        self._dump_customizations(customizations)

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

    def _dump_customizations(self, customizations: dict[str, CustomizationComponent]) -> None:
        # TEMP (remove later): write the filtered customizations to .local for the
        # maker to navigate. Best-effort — never fail the run on a dump error; and
        # skip under pytest so unit runs don't litter the working tree.
        if "PYTEST_CURRENT_TEST" in os.environ:
            return
        try:
            serializable = {cid: asdict(component) for cid, component in customizations.items()}
            _CUSTOMIZATIONS_DUMP_PATH.parent.mkdir(parents=True, exist_ok=True)
            _CUSTOMIZATIONS_DUMP_PATH.write_text(
                json.dumps(serializable, indent=2), encoding="utf-8"
            )
            self._logger.LogInfo(
                f"[temp] Wrote {len(customizations)} customization(s) to "
                f"{_CUSTOMIZATIONS_DUMP_PATH}.",
                pipeline_stage="Input",
                pipeline_step=self.name(),
            )
        except OSError as exc:
            self._logger.LogWarning(
                f"[temp] Could not write customizations dump: {exc}",
                pipeline_stage="Input",
                pipeline_step=self.name(),
            )


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
