# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Read-only readiness checks for AgentBuilder-native declarative agents."""

from __future__ import annotations

import uuid
from typing import Any

from agentbuilder import AgentBuilderHTTPError
from setup_existing_da import validate_existing_dev_connection

from ..runner import CheckResult, Priority, Role, Status
from .connections import get_connection_status


def _result(
    checkpoint_id: str,
    status: str,
    description: str,
    result: str,
    remediation: str = "",
) -> CheckResult:
    return CheckResult(
        checkpoint_id=checkpoint_id,
        category="Native Agent",
        priority=Priority.HIGH.value,
        status=status,
        description=description,
        result=result,
        remediation=remediation,
        roles=[
            Role.ESS_MAKER.value,
            Role.POWER_PLATFORM_ADMIN.value,
        ],
    )


def _active_agent(config: dict[str, Any]) -> dict[str, Any]:
    agents = config.get("agents") or []
    active_slug = config.get("activeAgent") or (config.get("agent") or {}).get(
        "slug"
    )
    if active_slug:
        active = next(
            (
                agent
                for agent in agents
                if isinstance(agent, dict) and agent.get("slug") == active_slug
            ),
            None,
        )
        if active is not None:
            return active
    single = config.get("agent")
    if isinstance(single, dict) and single:
        return single
    return next(
        (agent for agent in agents if isinstance(agent, dict)),
        {},
    )


def _normalize_connector_id(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.rstrip("/").rsplit("/", 1)[-1].casefold()


def _connection_references(changeset: dict[str, Any]) -> list[dict[str, str]]:
    references: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    changes = changeset.get("connectionReferenceChanges")
    if changes is None:
        return references
    if not isinstance(changes, list):
        raise ValueError(
            "Component fetch returned invalid connectionReferenceChanges."
        )
    for change in changes:
        item = change.get("connectionReference") if isinstance(change, dict) else None
        if not isinstance(item, dict):
            continue
        connector = _normalize_connector_id(item.get("connectorId"))
        if not connector:
            continue
        connection_id = str(item.get("connectionId") or "").strip()
        key = (connector, connection_id.casefold())
        if key in seen:
            continue
        seen.add(key)
        references.append(
            {
                "connector": connector,
                "connection_id": connection_id,
            }
        )
    return references


def _matching_connections(
    connections: list[dict[str, Any]],
    connector: str,
) -> list[dict[str, Any]]:
    return [
        connection
        for connection in connections
        if _normalize_connector_id(
            (connection.get("properties") or {}).get("apiId")
        )
        == connector
    ]


def _classify_reference(
    reference: dict[str, str],
    connections: list[dict[str, Any]],
    checkpoint_id: str,
) -> CheckResult:
    connector = reference["connector"]
    expected_id = reference["connection_id"]
    candidates = _matching_connections(connections, connector)

    if expected_id:
        exact = next(
            (
                candidate
                for candidate in candidates
                if str(candidate.get("name") or "").casefold()
                == expected_id.casefold()
            ),
            None,
        )
        if exact is None:
            return _result(
                checkpoint_id,
                Status.FAILED.value,
                f"Native connection reference: {connector}",
                "The agent names a physical connection that is not visible in "
                "this environment.",
                "Repair the agent connection, then rerun FlightCheck.",
            )
        status = get_connection_status(exact)
        display_name = (exact.get("properties") or {}).get(
            "displayName", connector
        )
        return _result(
            checkpoint_id,
            (
                Status.PASSED.value
                if status == "Connected"
                else Status.FAILED.value
            ),
            f"Native connection reference: {connector}",
            f"Exact mapped connection '{display_name}' status: {status}.",
            (
                f"Re-authenticate '{display_name}' in Power Platform."
                if status != "Connected"
                else ""
            ),
        )

    connected = [
        candidate
        for candidate in candidates
        if get_connection_status(candidate) == "Connected"
    ]
    if not candidates:
        return _result(
            checkpoint_id,
            Status.NOT_CONFIGURED.value,
            f"Native connection reference: {connector}",
            "The agent declares this logical connector, but no matching "
            "physical connection is visible in the environment.",
            "Create and authenticate a matching Power Platform connection, "
            "then rerun FlightCheck.",
        )
    if not connected:
        return _result(
            checkpoint_id,
            Status.FAILED.value,
            f"Native connection reference: {connector}",
            f"{len(candidates)} matching environment connection(s) were found, "
            "but none is Connected. AgentBuilder did not expose an exact "
            "physical mapping.",
            "Re-authenticate a matching Power Platform connection, then rerun "
            "FlightCheck.",
        )
    if len(connected) == 1:
        display_name = (connected[0].get("properties") or {}).get(
            "displayName", connector
        )
        return _result(
            checkpoint_id,
            Status.PASSED.value,
            f"Native connection reference: {connector}",
            f"One Connected environment candidate ('{display_name}') is ready. "
            "AgentBuilder did not expose the agent-to-physical-connection "
            "mapping, so exact binding remains unverified.",
        )
    return _result(
        checkpoint_id,
        Status.WARNING.value,
        f"Native connection reference: {connector}",
        f"{len(connected)} Connected environment candidates were found. "
        "AgentBuilder did not expose the agent-to-physical-connection mapping, "
        "so FlightCheck cannot identify which candidate the agent uses.",
        "Review the agent's Connection settings if an exact binding attestation "
        "is required.",
    )


def _connection_summary(details: list[CheckResult]) -> CheckResult:
    statuses = {detail.status for detail in details}
    if Status.FAILED.value in statuses:
        status = Status.FAILED.value
    elif Status.ERROR.value in statuses:
        status = Status.ERROR.value
    elif Status.WARNING.value in statuses:
        status = Status.WARNING.value
    elif Status.NOT_CONFIGURED.value in statuses:
        status = Status.NOT_CONFIGURED.value
    else:
        status = Status.PASSED.value
    exact = sum("Exact mapped connection" in detail.result for detail in details)
    unverified = len(details) - exact
    return _result(
        "DA-CONN-001",
        status,
        "Native agent connection readiness",
        f"{len(details)} logical connector reference(s): {exact} exact mapping(s), "
        f"{unverified} mapping(s) not exposed by AgentBuilder.",
        (
            "Resolve the actionable connection rows below, then rerun "
            "FlightCheck."
            if status
            in {
                Status.FAILED.value,
                Status.ERROR.value,
                Status.NOT_CONFIGURED.value,
            }
            else ""
        ),
    )


def run_native_agent_checks(runner) -> list[CheckResult]:
    """Validate exact Dev-agent access, content, and native connections."""
    config = getattr(runner, "config", {}) or {}
    environment_id = getattr(runner, "env_id", None) or config.get(
        "environmentId"
    )
    agent = _active_agent(config)
    agent_id = agent.get("botId")
    client = getattr(runner, "agentbuilder", None)
    connectivity = getattr(runner, "connectivity", None)

    if not environment_id or not agent_id:
        return [
            _result(
                "DA-AGENT-001",
                Status.FAILED.value,
                "Native Dev agent access",
                "The native environment or active agent identity is missing "
                "from .local/config.json.",
                "Run /setup again to attach the exact Dev agent.",
            )
        ]
    if client is None:
        return [
            _result(
                "DA-AGENT-001",
                Status.ERROR.value,
                "Native Dev agent access",
                "AgentBuilder authentication is unavailable.",
                "Sign in to the native Power Platform environment and rerun "
                "FlightCheck.",
            ),
            _result(
                "DA-CONTENT-001",
                Status.ERROR.value,
                "Native agent component footprint",
                "AgentBuilder authentication is unavailable.",
                "Sign in to the native Power Platform environment and rerun "
                "FlightCheck.",
            ),
            _result(
                "DA-CONN-001",
                Status.ERROR.value,
                "Native agent connection readiness",
                "AgentBuilder authentication is unavailable.",
                "Sign in to the native Power Platform environment and rerun "
                "FlightCheck.",
            ),
        ]

    try:
        connection = validate_existing_dev_connection(
            client,
            environment_id=environment_id,
            agent_id=agent_id,
            selection_source="flightcheck",
            require_alm_family=False,
            expected_schema_name=str(
                runner.config.get("agent", {}).get("schemaName") or ""
            )
            or None,
        )
    except AgentBuilderHTTPError as exc:
        status = (
            Status.FAILED.value
            if exc.status_code in {403, 404}
            else Status.ERROR.value
        )
        return [
            _result(
                "DA-AGENT-001",
                status,
                "Native Dev agent access",
                str(exc),
                "Verify access to the exact Dev agent, then rerun FlightCheck.",
            )
        ]
    except (ValueError, RuntimeError) as exc:
        return [
            _result(
                "DA-AGENT-001",
                Status.FAILED.value,
                "Native Dev agent access",
                str(exc),
                "Repair the saved native agent identity with /setup, then "
                "rerun FlightCheck.",
            )
        ]

    results = [
        _result(
            "DA-AGENT-001",
            Status.PASSED.value,
            "Native Dev agent access",
            f"Exact Dev agent '{connection['agent']['name']}' is accessible.",
        )
    ]

    try:
        changeset = client.fetch_components(str(uuid.UUID(str(agent_id))))
        bot = changeset.get("bot")
        fetched_id = (
            bot.get("cdsBotId") or bot.get("componentIdUnique")
            if isinstance(bot, dict)
            else None
        )
        if str(uuid.UUID(str(fetched_id))).casefold() != str(
            uuid.UUID(str(agent_id))
        ).casefold():
            raise ValueError(
                "Component fetch returned content for a different agent."
            )
        components = changeset.get("botComponentChanges")
        if not isinstance(components, list):
            raise ValueError(
                "Component fetch did not return botComponentChanges."
            )
    except AgentBuilderHTTPError as exc:
        results.append(
            _result(
                "DA-CONTENT-001",
                Status.ERROR.value,
                "Native agent component footprint",
                str(exc),
                "Retry the read-only component fetch after verifying service "
                "availability and access.",
            )
        )
        return results
    except (TypeError, ValueError) as exc:
        results.append(
            _result(
                "DA-CONTENT-001",
                Status.FAILED.value,
                "Native agent component footprint",
                str(exc),
                "Run /setup again to refresh the exact native agent workspace.",
            )
        )
        return results

    results.append(
        _result(
            "DA-CONTENT-001",
            (
                Status.PASSED.value
                if components
                else Status.FAILED.value
            ),
            "Native agent component footprint",
            f"Fetched {len(components)} authored component(s) for the exact agent.",
            (
                "Add or restore the agent's authored components before "
                "continuing."
                if not components
                else ""
            ),
        )
    )

    try:
        references = _connection_references(changeset)
    except ValueError as exc:
        results.append(
            _result(
                "DA-CONN-001",
                Status.ERROR.value,
                "Native agent connection readiness",
                str(exc),
                "Refresh the agent content and rerun FlightCheck.",
            )
        )
        return results

    connector_filter = {
        _normalize_connector_id(value)
        for value in (
            getattr(runner, "native_connector_filter", None) or ()
        )
        if _normalize_connector_id(value)
    }
    if connector_filter:
        references = [
            reference
            for reference in references
            if reference["connector"] in connector_filter
        ]
    if not references:
        explicit_target = bool(connector_filter)
        results.append(
            _result(
                "DA-CONN-001",
                (
                    Status.NOT_CONFIGURED.value
                    if explicit_target
                    else Status.SKIPPED.value
                ),
                "Native agent connection readiness",
                (
                    "The agent does not declare a logical reference for the "
                    "selected connector."
                    if explicit_target
                    else "The agent declares no native logical connector "
                    "references."
                ),
                (
                    "Add the selected integration to the agent, then rerun "
                    "FlightCheck."
                    if explicit_target
                    else ""
                ),
            )
        )
        return results
    if connectivity is None:
        results.append(
            _result(
                "DA-CONN-001",
                Status.ERROR.value,
                "Native agent connection readiness",
                "Power Platform connection inventory authentication is "
                "unavailable.",
                "Sign in with access to the environment's connections, then "
                "rerun FlightCheck.",
            )
        )
        return results

    try:
        connections = connectivity.list_connections(environment_id)
    except AgentBuilderHTTPError as exc:
        status = (
            Status.FAILED.value
            if exc.status_code in {401, 403}
            else Status.ERROR.value
        )
        results.append(
            _result(
                "DA-CONN-001",
                status,
                "Native agent connection readiness",
                str(exc),
                "Verify connection-read access to the environment, then rerun "
                "FlightCheck.",
            )
        )
        return results
    except RuntimeError as exc:
        results.append(
            _result(
                "DA-CONN-001",
                Status.ERROR.value,
                "Native agent connection readiness",
                str(exc),
                "Retry the read-only connection inventory operation.",
            )
        )
        return results

    details = [
        _classify_reference(reference, connections, f"DA-CONN-{index:03d}")
        for index, reference in enumerate(references, start=2)
    ]
    results.append(_connection_summary(details))
    results.extend(details)
    return results
