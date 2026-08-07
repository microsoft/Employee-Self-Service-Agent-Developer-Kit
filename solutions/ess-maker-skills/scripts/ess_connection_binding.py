# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Validate and bind connections required by ESS agent installations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import quote

from auth import authenticate, discover_tenant, query_all, update_record
from flightcheck.pp_admin_client import PPAdminClient, derive_environment_id
from install_ess_agent import CONFIG_PATH, load_installation_config


PREFLIGHT_MARKER = "ESS_CONNECTION_PREFLIGHT_JSON:"
BINDING_MARKER = "ESS_CONNECTION_BINDING_JSON:"
DEFAULT_SETUP_STATE_PATH = Path(".local/setup/config.json")


def _connector_api_name(value: str | None) -> str:
    return (value or "").rstrip("/").rsplit("/", 1)[-1].casefold()


def _connection_status(connection: dict) -> str:
    statuses = (connection.get("properties") or {}).get("statuses") or []
    if not statuses or not isinstance(statuses[0], dict):
        return "Unknown"
    return str(statuses[0].get("status") or "Unknown")


def connection_option(connection: dict) -> dict:
    properties = connection.get("properties") or {}
    created_by = properties.get("createdBy") or {}
    return {
        "name": connection.get("name"),
        "displayName": properties.get("displayName") or connection.get("name"),
        "accountName": (
            properties.get("accountName")
            or created_by.get("userPrincipalName")
            or created_by.get("displayName")
        ),
        "status": _connection_status(connection),
    }


def matching_connections(connections: list[dict], connector_api_name: str) -> list[dict]:
    matches = []
    expected = connector_api_name.casefold()
    for connection in connections:
        properties = connection.get("properties") or {}
        if _connector_api_name(properties.get("apiId")) != expected:
            continue
        if _connection_status(connection).casefold() != "connected":
            continue
        if connection.get("name"):
            matches.append(connection_option(connection))
    return matches


def build_preflight_result(
    installation: dict,
    connections: list[dict],
    environment_id: str,
) -> dict:
    requirement = installation.get("requiredConnection")
    if requirement is None:
        return {
            "required": False,
            "status": "not-required",
            "environmentId": environment_id,
            "connections": [],
        }

    options = matching_connections(
        connections,
        requirement["connectorApiName"],
    )
    status = (
        "missing" if not options
        else "ready" if len(options) == 1
        else "selection-required"
    )
    return {
        "required": True,
        "status": status,
        "environmentId": environment_id,
        "connectorApiName": requirement["connectorApiName"],
        "displayName": requirement["displayName"],
        "referenceLogicalName": requirement["referenceLogicalName"],
        "creationGuidance": requirement["creationGuidance"],
        "connections": options,
        "selectedConnection": options[0] if len(options) == 1 else None,
    }


def _installation(config: dict, experience: str, vertical: str) -> dict:
    return config["installations"][f"{experience}.{vertical}"]


def _persist_setup_status(
    installation: dict,
    binding_result: dict,
    state_path: Path = DEFAULT_SETUP_STATE_PATH,
) -> None:
    from setup_state import persist_product_installation_status

    attestation_required = bool(binding_result.get("attestationRequired"))
    persist_product_installation_status(
        installation["configKey"],
        (
            "connection-attestation-required"
            if attestation_required
            else "bound"
        ),
        connection_name=binding_result.get("connectionName"),
        schema_name=installation["solution"]["parentUniqueName"],
        requires_connection_attestation=attestation_required,
        agent_id=binding_result.get("agentId"),
        agent_name=binding_result.get("agentName"),
        connection_settings_url=binding_result.get("connectionSettingsUrl"),
        state_path=state_path,
    )


def inspect_connections(
    env_url: str,
    experience: str,
    vertical: str,
    *,
    config_path: Path = CONFIG_PATH,
    pp_admin_client_factory=PPAdminClient,
) -> dict:
    env_url = env_url.rstrip("/")
    config = load_installation_config(config_path)
    installation = _installation(config, experience, vertical)
    if installation.get("requiredConnection") is None:
        return build_preflight_result(installation, [], "")

    tenant_id = discover_tenant(env_url)
    client = pp_admin_client_factory(tenant_id)
    client.authenticate(include_flow=False)
    environment_id = derive_environment_id(env_url, "", client)
    if not environment_id:
        raise RuntimeError(
            "Could not resolve the selected Dataverse URL to a Power Platform "
            "environment ID."
        )
    connections = client.get_connections(environment_id)
    if isinstance(connections, dict) and connections.get("_error"):
        raise RuntimeError(
            "Your account cannot read connections for this environment. "
            "Use a Power Platform administrator account."
        )
    return build_preflight_result(
        installation,
        connections,
        environment_id,
    )


def _assert_reference_in_solution(
    env_url: str,
    token: str,
    reference_id: str,
    solution_unique_name: str,
) -> None:
    components = query_all(
        env_url,
        token,
        "solutioncomponents",
        "objectid,_solutionid_value",
        filter_expr=f"objectid eq {reference_id}",
    )
    solution_ids = {
        component.get("_solutionid_value")
        for component in components
        if component.get("_solutionid_value")
    }
    if not solution_ids:
        raise RuntimeError(
            "The required connection reference is not registered in a solution."
        )

    id_filter = " or ".join(
        f"solutionid eq {solution_id}" for solution_id in sorted(solution_ids)
    )
    escaped_name = solution_unique_name.replace("'", "''")
    solutions = query_all(
        env_url,
        token,
        "solutions",
        "solutionid,uniquename",
        filter_expr=f"({id_filter}) and uniquename eq '{escaped_name}'",
    )
    if not solutions:
        raise RuntimeError(
            f"The required connection reference does not belong to solution "
            f"'{solution_unique_name}'."
        )


def _installed_agent(
    env_url: str,
    token: str,
    schema_name: str,
) -> dict:
    escaped_schema_name = schema_name.replace("'", "''")
    agents = query_all(
        env_url,
        token,
        "bots",
        "botid,name,schemaname",
        filter_expr=f"schemaname eq '{escaped_schema_name}'",
    )
    if len(agents) != 1:
        raise RuntimeError(
            "Expected exactly one installed agent for "
            f"'{schema_name}', found {len(agents)}."
        )
    agent = agents[0]
    if not agent.get("botid") or not agent.get("name"):
        raise RuntimeError(
            f"The installed agent '{schema_name}' is missing its ID or name."
        )
    return agent


def connection_settings_url(environment_id: str, agent_id: str) -> str:
    """Build the direct Copilot Studio connection-settings URL."""
    return (
        "https://copilotstudio.microsoft.com/environments/"
        f"{quote(environment_id, safe='')}/copilots/"
        f"{quote(agent_id, safe='')}/settings/connectionSettings"
    )


def bind_connection(
    env_url: str,
    experience: str,
    vertical: str,
    connection_name: str | None,
    *,
    config_path: Path = CONFIG_PATH,
    state_path: Path = DEFAULT_SETUP_STATE_PATH,
    pp_admin_client_factory=PPAdminClient,
) -> dict:
    env_url = env_url.rstrip("/")
    config = load_installation_config(config_path)
    installation = _installation(config, experience, vertical)
    requirement = installation.get("requiredConnection")
    if requirement is None:
        result = {
            "required": False,
            "status": "not-required",
            "connectionName": None,
        }
        _persist_setup_status(installation, result, state_path)
        return result
    if not connection_name:
        raise ValueError("A connection name is required for this ESS agent.")

    preflight = inspect_connections(
        env_url,
        experience,
        vertical,
        config_path=config_path,
        pp_admin_client_factory=pp_admin_client_factory,
    )
    selected = next(
        (
            option for option in preflight["connections"]
            if option["name"] == connection_name
        ),
        None,
    )
    if selected is None:
        raise ValueError(
            "The selected connection is not a connected instance of "
            f"{requirement['connectorApiName']} in this environment."
        )

    token = authenticate(env_url)
    escaped_logical_name = requirement["referenceLogicalName"].replace("'", "''")
    references = query_all(
        env_url,
        token,
        "connectionreferences",
        "connectionreferenceid,connectionreferencelogicalname,connectorid,"
        "connectionid,statuscode",
        filter_expr=(
            f"connectionreferencelogicalname eq '{escaped_logical_name}'"
        ),
    )
    if len(references) != 1:
        raise RuntimeError(
            "Expected exactly one required connection reference after "
            f"installation, found {len(references)}."
        )

    reference = references[0]
    if _connector_api_name(reference.get("connectorid")) != (
        requirement["connectorApiName"].casefold()
    ):
        raise RuntimeError(
            "The installed connection reference uses an unexpected connector."
        )
    _assert_reference_in_solution(
        env_url,
        token,
        reference["connectionreferenceid"],
        installation["solution"]["parentUniqueName"],
    )

    if reference.get("connectionid") != connection_name:
        update_record(
            env_url,
            token,
            "connectionreferences",
            reference["connectionreferenceid"],
            {"connectionid": connection_name},
        )

    verified = query_all(
        env_url,
        token,
        "connectionreferences",
        "connectionreferenceid,connectionid",
        filter_expr=(
            f"connectionreferenceid eq {reference['connectionreferenceid']}"
        ),
    )
    if len(verified) != 1 or verified[0].get("connectionid") != connection_name:
        raise RuntimeError(
            "Dataverse accepted the binding request but the connection "
            "reference did not retain the selected connection."
        )

    attestation_required = requirement.get("runtimeSource") == "invoker"
    agent = None
    settings_url = None
    if attestation_required:
        agent = _installed_agent(
            env_url,
            token,
            installation["solution"]["parentUniqueName"],
        )
        settings_url = connection_settings_url(
            preflight["environmentId"],
            agent["botid"],
        )

    result = {
        "required": True,
        "status": "bound",
        "connectionName": connection_name,
        "connectionDisplayName": selected["displayName"],
        "connectionAccountName": selected["accountName"],
        "referenceId": reference["connectionreferenceid"],
        "referenceLogicalName": requirement["referenceLogicalName"],
        "attestationRequired": attestation_required,
        "agentId": agent["botid"] if agent else None,
        "agentName": agent["name"] if agent else None,
        "connectionSettingsUrl": settings_url,
    }
    _persist_setup_status(installation, result, state_path)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate and bind required ESS installation connections"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("inspect", "bind"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--url", required=True)
        command_parser.add_argument("--experience", required=True, choices=("da", "cea"))
        command_parser.add_argument(
            "--vertical",
            required=True,
            choices=("hr", "it", "hub"),
        )
        if command == "bind":
            command_parser.add_argument("--connection-name")
            command_parser.add_argument(
                "--state",
                default=str(DEFAULT_SETUP_STATE_PATH),
            )
    args = parser.parse_args()

    try:
        if args.command == "inspect":
            result = inspect_connections(args.url, args.experience, args.vertical)
            print(f"{PREFLIGHT_MARKER}{json.dumps(result)}")
        else:
            result = bind_connection(
                args.url,
                args.experience,
                args.vertical,
                args.connection_name,
                state_path=Path(args.state),
            )
            print(f"{BINDING_MARKER}{json.dumps(result)}")
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
