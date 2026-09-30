# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Resolve selected-agent Workday OAuth connection parameters.

The shipping Workday Declarative Agent is flow-based: enabled topics invoke
Power Automate flows, flow detail names each bound physical connection, and the
PowerApps Admin connection record exposes non-secret
``connectionParametersSet.values``. AgentBuilder component payloads do not
provide a validated Workday parameter contract, so verdict-producing checks
must use this flow-to-connection join instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ._agent_connection_refs import build_active_agent_connection_bindings


WORKDAY_CONNECTOR = "shared_workdaysoap"
WORKDAY_OAUTH_PARAMETER_SET = "oauth"


@dataclass(frozen=True)
class WorkdayOAuthConnection:
    """One selected-agent, flow-bound Workday OAuth connection."""

    name: str
    display_name: str
    values: dict[str, str]


@dataclass(frozen=True)
class WorkdayOAuthResolution:
    """Grounded Workday connection evidence for the selected agent."""

    has_workday_binding: bool
    connections: tuple[WorkdayOAuthConnection, ...]
    unresolved_bindings: tuple[str, ...]
    ignored_non_oauth_bindings: tuple[str, ...]


def _parameter_values(connection: dict[str, Any]) -> dict[str, str]:
    props = connection.get("properties") or {}
    param_set = props.get("connectionParametersSet") or {}
    raw_values = param_set.get("values") or {}
    if not isinstance(raw_values, dict):
        return {}

    values: dict[str, str] = {}
    for key, raw_value in raw_values.items():
        if not isinstance(key, str):
            continue
        value = raw_value.get("value") if isinstance(raw_value, dict) else raw_value
        if value is None:
            continue
        values[key] = str(value).strip()
    return values


def _binding_label(logical_name: str, connection_name: str) -> str:
    return connection_name or logical_name or "(unnamed Workday binding)"


def resolve_active_workday_oauth_connections(
    runner,
) -> WorkdayOAuthResolution | None:
    """Join the selected agent's Workday flow bindings to physical connections.

    Returns ``None`` when required clients or selected-agent configuration are
    unavailable. Raises on permission/API failures so callers can surface an
    honest WARNING. Results are cached on the runner because WD-ENV-001 and
    WD-REST-001 consume the same evidence during a full FlightCheck run.
    """
    cached = getattr(runner, "_active_workday_oauth_resolution", None)
    if isinstance(cached, WorkdayOAuthResolution):
        return cached

    bindings = build_active_agent_connection_bindings(runner)
    if bindings is None:
        return None

    workday_bindings = tuple(
        binding for binding in bindings if binding.connector == WORKDAY_CONNECTOR
    )
    if not workday_bindings:
        resolution = WorkdayOAuthResolution(
            has_workday_binding=False,
            connections=(),
            unresolved_bindings=(),
            ignored_non_oauth_bindings=(),
        )
        runner._active_workday_oauth_resolution = resolution
        return resolution

    pp = getattr(runner, "pp_admin", None)
    env_id = getattr(runner, "env_id", None)
    try:
        inventory = pp.get_connections(env_id)
    except Exception as exc:
        raise RuntimeError(
            f"Power Platform Admin connection inventory failed: {exc}"
        ) from exc
    if isinstance(inventory, dict) and inventory.get("_error"):
        raise RuntimeError(
            "Power Platform Admin connection inventory failed: "
            f"{inventory.get('_error')}"
        )
    if not isinstance(inventory, list):
        raise RuntimeError(
            "Power Platform Admin connection inventory returned an invalid response."
        )

    by_name = {
        str(connection.get("name") or ""): connection
        for connection in inventory
        if isinstance(connection, dict) and connection.get("name")
    }
    connections: dict[str, WorkdayOAuthConnection] = {}
    unresolved: set[str] = set()
    ignored: set[str] = set()

    for binding in workday_bindings:
        label = _binding_label(binding.logical_name, binding.connection_name)
        if not binding.connection_name:
            unresolved.add(label)
            continue
        connection = by_name.get(binding.connection_name)
        if connection is None:
            unresolved.add(label)
            continue

        props = connection.get("properties") or {}
        api_id = str(props.get("apiId") or "").casefold().rstrip("/")
        if not api_id.endswith(f"/apis/{WORKDAY_CONNECTOR}"):
            unresolved.add(label)
            continue

        param_set = props.get("connectionParametersSet") or {}
        auth_name = str(param_set.get("name") or "").strip()
        if auth_name.casefold() != WORKDAY_OAUTH_PARAMETER_SET:
            if auth_name:
                ignored.add(f"{label} ({auth_name})")
            else:
                unresolved.add(label)
            continue

        display_name = str(props.get("displayName") or binding.connection_name)
        connections[binding.connection_name] = WorkdayOAuthConnection(
            name=binding.connection_name,
            display_name=display_name,
            values=_parameter_values(connection),
        )

    resolution = WorkdayOAuthResolution(
        has_workday_binding=True,
        connections=tuple(connections[name] for name in sorted(connections)),
        unresolved_bindings=tuple(sorted(unresolved)),
        ignored_non_oauth_bindings=tuple(sorted(ignored)),
    )
    runner._active_workday_oauth_resolution = resolution
    return resolution
