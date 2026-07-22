"""Retrieve customization dependencies + component layers for the selected agent.

Discovery slice:
1. Resolve the ESS base solution for the selected agent's vertical.
2. Call ``RetrieveDependenciesForUninstallWithMetadata`` to list the dependent
   components layered on top of the ESS base solution.
3. Bulk-fetch ``msdyn_componentlayers`` for those dependent components (chunked
   + paginated), then classify each component by its layers:

   - **untouched OOB** — every layer is the ~1900 managed base sentinel → drop.
   - **net-new** — a single non-sentinel layer → keep it.
   - **customized OOB** — a ~1900 base layer plus a recent overlay → keep the
     latest non-sentinel overlay layer.

Only the filtered customization layers propagate to the migration/output
modules via the ``MigrationContext``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from core.logging import Logger
from modules.transformation.migration_step import MigrationPipelineStep
from modules.transformation.models import MigrationContext
from service.utils import resolve_ess_solution

_DEPENDENCIES_FUNCTION = "RetrieveDependenciesForUninstallWithMetadata"
_COMPONENT_LAYERS_ENTITY = "msdyn_componentlayers"
# Keep each $filter under Dataverse URL limits by chunking the id OR-groups.
_LAYER_ID_CHUNK_SIZE = 20
_EMPTY_GUID = "00000000-0000-0000-0000-000000000000"
# Managed base layers carry a ~1900 sentinel overwrite time; anything on/before
# this year is treated as the untouched base, not a customization.
_SENTINEL_YEAR = 1900
_MIN_DT = datetime.min.replace(tzinfo=UTC)


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

        self._logger.LogInfo(
            f"Retrieving customization dependencies for solution '{solution_unique_name}'.",
            pipeline_stage="Input",
            pipeline_step=self.name(),
        )

        response = context.dataverse_client.call_function(
            _DEPENDENCIES_FUNCTION,
            SolutionUniqueName=solution_unique_name,
        )
        context.raw_dependencies = response

        dependent_ids = _extract_dependent_ids(response)
        self._logger.LogInfo(
            f"Found {len(dependent_ids)} dependent component(s); fetching component layers.",
            pipeline_stage="Input",
            pipeline_step=self.name(),
        )

        layers = self._fetch_component_layers(context.dataverse_client, dependent_ids)
        context.component_layers = layers

        customizations = _select_customizations(layers)
        context.customizations = customizations

        self._logger.LogInfo(
            f"Classified {len(customizations)} customization(s) from "
            f"{len(layers)} layer record(s) across {len(dependent_ids)} component(s).",
            pipeline_stage="Input",
            pipeline_step=self.name(),
        )
        return context

    def _fetch_component_layers(
        self, client: Any, component_ids: list[str]
    ) -> list[dict[str, Any]]:
        layers: list[dict[str, Any]] = []
        for chunk in _chunk(component_ids, _LAYER_ID_CHUNK_SIZE):
            # Fetch all fields (includes msdyn_componentjson) so downstream
            # modules have the full component payload to transform + write back.
            layers.extend(
                client.query_all(
                    _COMPONENT_LAYERS_ENTITY,
                    select=None,
                    filter=_layer_filter(chunk),
                )
            )
        return layers


def _extract_dependent_ids(response: Any) -> list[str]:
    """Return unique, non-empty ``dependentcomponentobjectid`` values."""
    infos = _dependency_infos(response)
    seen: set[str] = set()
    ids: list[str] = []
    for info in infos:
        if not isinstance(info, dict):
            continue
        object_id = info.get("dependentcomponentobjectid")
        if (
            isinstance(object_id, str)
            and object_id
            and object_id != _EMPTY_GUID
            and object_id not in seen
        ):
            seen.add(object_id)
            ids.append(object_id)
    return ids


def _dependency_infos(response: Any) -> list[Any]:
    if not isinstance(response, dict):
        return []
    collection = response.get("DependencyMetadataCollection")
    if not isinstance(collection, dict):
        return []
    infos = collection.get("DependencyMetadataInfoCollection")
    return infos if isinstance(infos, list) else []


def _select_customizations(layers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return one winning customization layer per truly-customized component.

    Classification logic (per ``msdyn_componentid`` group of layers), where the
    managed base layer carries a ~1900 sentinel ``msdyn_overwritetime`` and any
    customer edit/overlay carries a recent (non-1900) time:

    - **Untouched OOB** — the group has a single layer whose ``overwritetime``
      is the ~1900 sentinel. Nothing was customized -> **drop** it.
    - **Customized OOB** — the group has two (or more) layers: the ~1900 managed
      base layer plus a recent overlay. The recent (latest non-sentinel) layer
      IS the customer's customization -> **keep that overlay** (drop the base).
    - **Net-new** — the group has a single layer whose ``overwritetime`` is
      recent (not ~1900). The customer created this component from scratch
      (e.g. a brand-new topic) -> **keep** that single layer.

    These three cases collapse into one rule: keep the *latest non-sentinel*
    layer per component; if every layer is a ~1900 sentinel, the component is
    untouched OOB and is dropped. Only the kept layers propagate to the
    migration/output modules.
    """
    customizations: list[dict[str, Any]] = []
    for group in _group_by_component(layers).values():
        winner = _latest_non_sentinel_layer(group)
        if winner is not None:
            customizations.append(winner)
    return customizations


def _group_by_component(layers: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for layer in layers:
        component_id = layer.get("msdyn_componentid")
        if isinstance(component_id, str) and component_id:
            grouped.setdefault(component_id, []).append(layer)
    return grouped


def _latest_non_sentinel_layer(layers: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates: list[tuple[datetime, dict[str, Any]]] = []
    for layer in layers:
        overwrite_time = _parse_overwrite_time(layer)
        if _is_sentinel(overwrite_time):
            continue
        candidates.append((overwrite_time or _MIN_DT, layer))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0])
    return candidates[-1][1]


def _parse_overwrite_time(layer: dict[str, Any]) -> datetime | None:
    raw = layer.get("msdyn_overwritetime")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_sentinel(overwrite_time: datetime | None) -> bool:
    return overwrite_time is not None and overwrite_time.year <= _SENTINEL_YEAR


def _layer_filter(component_ids: list[str]) -> str:
    return " or ".join(f"msdyn_componentid eq '{cid}'" for cid in component_ids)


def _chunk(items: list[str], size: int) -> Iterator[list[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]
