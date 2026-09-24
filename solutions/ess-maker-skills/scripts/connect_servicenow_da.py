# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Connect the DA-GA HR agent to ServiceNow HRSD without Dataverse."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from agentbuilder import (
    AgentBuilderClient,
    AgentBuilderError,
    RING_CONFIG,
    authenticate,
    validate_environment_host,
)


SETUP_STATE = Path(".local/setup/config.json")
ACTIVE_CONFIG = Path(".local/config.json")
CONNECTOR_ID = "/providers/Microsoft.PowerApps/apis/shared_service-now"
CONNECTOR_NAME = "shared_service-now"
CONNECTIVITY_API_VERSION = "1"
SETUP_SCHEMA_VERSION = 4
HR_SCHEMA_NAME = "gptagent_copilotforemployeeselfservicehr"
TOKEN_CACHE = Path(".local/.agentbuilder_token_cache.bin")
CONNECT_FOUNDATION_STEPS = (
    "SETUP-01",
    "SETUP-02.1",
    "SETUP-03",
    "SETUP-04",
    "SETUP-07",
)


class ServiceNowConnectError(RuntimeError):
    """Raised when the DA-GA ServiceNow prototype cannot proceed safely."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ServiceNowConnectError(f"Required file is missing: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ServiceNowConnectError(f"Could not read JSON file: {path}") from exc
    if not isinstance(value, dict):
        raise ServiceNowConnectError(f"Expected a JSON object in {path}.")
    return value


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=f"{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def _state_path(agent_id: str) -> Path:
    return Path(".local/connect/servicenow/agents") / agent_id / "state.json"


def load_context(root: Path = Path(".")) -> dict[str, Any]:
    setup = _load_json(root / SETUP_STATE)
    if setup.get("schema_version") != SETUP_SCHEMA_VERSION:
        raise ServiceNowConnectError(
            f"Expected /setup schema {SETUP_SCHEMA_VERSION}."
        )
    if setup.get("intent") != "DA foundation setup":
        raise ServiceNowConnectError("The setup state is not DA foundation setup.")

    environment = setup.get("environment")
    config = _load_json(root / ACTIVE_CONFIG)
    active_slug = config.get("activeAgent")
    operational_agents = config.get("agents")
    if not isinstance(environment, dict):
        raise ServiceNowConnectError("The setup handoff has no environment.")
    if not isinstance(active_slug, str) or not active_slug:
        raise ServiceNowConnectError("Operational config has no active agent.")
    if not isinstance(operational_agents, list):
        raise ServiceNowConnectError("Operational setup config has no agent list.")
    active = next(
        (
            item
            for item in operational_agents
            if isinstance(item, dict) and item.get("slug") == active_slug
        ),
        None,
    )
    if not isinstance(active, dict):
        raise ServiceNowConnectError("Could not resolve the active setup agent.")

    active_bot_id = active.get("botId")
    if not isinstance(active_bot_id, str):
        raise ServiceNowConnectError("The active agent has no bot ID.")
    try:
        normalized_bot_id = str(uuid.UUID(active_bot_id))
    except ValueError as exc:
        raise ServiceNowConnectError(
            "The active agent bot ID is invalid."
        ) from exc

    canonical_agents = setup.get("agents")
    if not isinstance(canonical_agents, dict):
        raise ServiceNowConnectError("Canonical setup state has no agent map.")
    canonical = next(
        (
            value
            for key, value in canonical_agents.items()
            if isinstance(key, str)
            and key.casefold() == normalized_bot_id.casefold()
            and isinstance(value, dict)
        ),
        None,
    )
    if not isinstance(canonical, dict):
        raise ServiceNowConnectError(
            "The active agent has no canonical /setup record."
        )
    agent = canonical.get("agent")
    if not isinstance(agent, dict):
        raise ServiceNowConnectError("The setup record has no agent identity.")
    if str(agent.get("id") or "").casefold() != normalized_bot_id.casefold():
        raise ServiceNowConnectError(
            "Canonical setup state and active agent config identify different agents."
        )
    if agent.get("workspace_slug") != active_slug:
        raise ServiceNowConnectError(
            "Canonical setup state and active workspace identify different agents."
        )
    if agent.get("realm") != "dev":
        raise ServiceNowConnectError("/connect only supports the editable Dev realm.")
    if agent.get("schema_name") != HR_SCHEMA_NAME:
        raise ServiceNowConnectError(
            "This prototype supports only Employee Self-Service (HR)."
        )
    steps = canonical.get("steps")
    if not isinstance(steps, dict):
        raise ServiceNowConnectError("The setup record has no foundation steps.")
    incomplete = [
        step_id
        for step_id in CONNECT_FOUNDATION_STEPS
        if not isinstance(steps.get(step_id), dict)
        or steps[step_id].get("state") != "done"
    ]
    if incomplete:
        raise ServiceNowConnectError(
            "DA foundation setup is incomplete for /connect: "
            + ", ".join(incomplete)
            + "."
        )
    workspace = canonical.get("workspace")
    if (
        not isinstance(workspace, dict)
        or not workspace.get("folder")
        or not workspace.get("agent_path")
    ):
        raise ServiceNowConnectError(
            "DA foundation setup has no materialized agent workspace."
        )

    relative_snapshot = active.get("agentBuilderChangeSetPath")
    if not isinstance(relative_snapshot, str) or not relative_snapshot:
        raise ServiceNowConnectError("The active agent has no component snapshot path.")
    snapshot_path = root / Path(relative_snapshot)
    return {
        "root": root,
        "setup": setup,
        "agentSetup": canonical,
        "config": config,
        "environment": environment,
        "agent": agent,
        "active": active,
        "snapshotPath": snapshot_path,
    }


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _component_schema(change: dict[str, Any]) -> str:
    component = change.get("component")
    if not isinstance(component, dict):
        return ""
    return str(component.get("schemaName") or "")


def find_servicenow_reference(components: dict[str, Any]) -> dict[str, Any]:
    matches = []
    for change in components.get("connectionReferenceChanges") or []:
        if not isinstance(change, dict):
            continue
        reference = change.get("connectionReference")
        if (
            isinstance(reference, dict)
            and str(reference.get("connectorId") or "").casefold()
            == CONNECTOR_ID.casefold()
        ):
            matches.append(reference)
    if len(matches) != 1:
        raise ServiceNowConnectError(
            "Expected exactly one ServiceNow connection reference; "
            f"found {len(matches)}."
        )
    return matches[0]


def _shared_parameters(reference: dict[str, Any]) -> dict[str, Any]:
    raw = reference.get("sharedConnectionParameters")
    if not raw:
        return {}
    if isinstance(raw, dict):
        value = raw
    elif isinstance(raw, str):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ServiceNowConnectError(
                "ServiceNow shared connection parameters are invalid JSON."
            ) from exc
    else:
        raise ServiceNowConnectError(
            "ServiceNow shared connection parameters have an invalid shape."
        )
    return value if isinstance(value, dict) else {}


def _parameter_value(parameters: dict[str, Any], name: str) -> str | None:
    values = parameters.get("values")
    if not isinstance(values, dict):
        return None
    item = values.get(name)
    if not isinstance(item, dict):
        return None
    value = item.get("value")
    return str(value) if value not in (None, "") else None


def summarize_components(components: dict[str, Any]) -> dict[str, Any]:
    reference = find_servicenow_reference(components)
    service_now_topics = [
        change
        for change in components.get("botComponentChanges") or []
        if "ServiceNowHRSD" in _component_schema(change)
    ]
    action_counts = {"InvokeFlowAction": 0, "InvokeConnectorAction": 0}
    service_now_action_counts = {"InvokeFlowAction": 0, "InvokeConnectorAction": 0}
    flow_ids: set[str] = set()
    for change in components.get("botComponentChanges") or []:
        is_service_now = "ServiceNowHRSD" in _component_schema(change)
        for node in _walk(change):
            kind = node.get("$kind")
            if kind in action_counts:
                action_counts[kind] += 1
                if is_service_now:
                    service_now_action_counts[kind] += 1
            flow_id = node.get("flowId")
            if isinstance(flow_id, str) and flow_id:
                flow_ids.add(flow_id)

    parameters = _shared_parameters(reference)
    return {
        "botComponentCount": len(components.get("botComponentChanges") or []),
        "serviceNowTopicCount": len(service_now_topics),
        "activeServiceNowTopicCount": sum(
            1
            for change in service_now_topics
            if isinstance(change.get("component"), dict)
            and change["component"].get("state") == "Active"
        ),
        "connectionReferenceCount": len(
            components.get("connectionReferenceChanges") or []
        ),
        "connectorDefinitionCount": len(
            components.get("connectorDefinitionChanges") or []
        ),
        "cloudFlowDefinitionCount": len(
            components.get("cloudFlowDefinitionChanges") or []
        ),
        "invokeFlowActionCount": action_counts["InvokeFlowAction"],
        "invokeConnectorActionCount": action_counts["InvokeConnectorAction"],
        "serviceNowInvokeFlowActionCount": service_now_action_counts[
            "InvokeFlowAction"
        ],
        "serviceNowInvokeConnectorActionCount": service_now_action_counts[
            "InvokeConnectorAction"
        ],
        "flowIds": sorted(flow_ids),
        "reference": {
            "id": reference.get("id"),
            "connectionId": reference.get("connectionId"),
            "logicalName": reference.get("connectionReferenceLogicalName"),
            "displayName": reference.get("displayName"),
            "authMode": parameters.get("name"),
            "instanceName": _parameter_value(
                parameters,
                "token:InstanceName",
            ),
            "resourceUri": _parameter_value(
                parameters,
                "token:ResourceUri",
            ),
        },
        "hasChangeToken": bool(components.get("changeToken")),
    }


def connectivity_scopes(ring: str) -> list[str]:
    config = RING_CONFIG.get(ring)
    if config is None:
        raise ServiceNowConnectError(f"Unsupported Power Platform ring: {ring}")
    audience = str(config["audience"])
    return [
        f"{audience}/Connectivity.Connections.Read",
        f"{audience}/Connectivity.Connectors.Read",
        f"{audience}/Connectivity.ConnectionPermissions.Read",
    ]


class ConnectivityClient:
    """Small client for the per-environment Power Platform Connectivity API."""

    def __init__(
        self,
        host: str,
        environment_id: str,
        token: str,
        *,
        ring: str,
        session: requests.Session | None = None,
    ) -> None:
        self.host = validate_environment_host(host, ring)
        self.environment_id = str(uuid.UUID(environment_id))
        self.session = session or requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "HEAD", "OPTIONS"}),
            respect_retry_after_header=True,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "x-ms-client-name": "EssAdk",
        }

    def _filter(self) -> str:
        return f"environment eq '{self.environment_id}'"

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        include_filter: bool = True,
        timeout: int = 60,
    ) -> dict[str, Any]:
        headers = dict(self.headers)
        if body is not None:
            headers["Content-Type"] = "application/json"
        params = {"api-version": CONNECTIVITY_API_VERSION}
        if include_filter:
            params["$filter"] = self._filter()
        response = self.session.request(
            method,
            f"{self.host}{path}",
            params=params,
            headers=headers,
            json=body,
            timeout=timeout,
        )
        if not response.ok:
            error_code = None
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if isinstance(payload, dict):
                error = payload.get("error") or payload
                if isinstance(error, dict):
                    error_code = error.get("code")
            detail = f"Connectivity API returned HTTP {response.status_code}"
            if error_code:
                detail += f" ({error_code})"
            raise ServiceNowConnectError(detail)
        try:
            value = response.json()
        except ValueError as exc:
            raise ServiceNowConnectError(
                "Connectivity API returned non-JSON content."
            ) from exc
        if not isinstance(value, dict):
            raise ServiceNowConnectError(
                "Connectivity API returned an invalid JSON shape."
            )
        return value

    def get_connector(self) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/connectivity/connectors/{CONNECTOR_NAME}",
        )

    def list_connections(self) -> list[dict[str, Any]]:
        body = self._request(
            "GET",
            f"/connectivity/connectors/{CONNECTOR_NAME}/connections",
        )
        values = body.get("value")
        if not isinstance(values, list):
            raise ServiceNowConnectError(
                "Connection listing returned an invalid shape."
            )
        return [value for value in values if isinstance(value, dict)]

    def get_connection(self, connection_id: str) -> dict[str, Any]:
        normalized = uuid.UUID(connection_id).hex
        return self._request(
            "GET",
            f"/connectivity/connectors/{CONNECTOR_NAME}/connections/"
            f"{quote(normalized, safe='')}",
        )

def connection_summary(record: dict[str, Any]) -> dict[str, Any]:
    properties = record.get("properties")
    if not isinstance(properties, dict):
        properties = {}
    statuses = properties.get("statuses")
    if not isinstance(statuses, list):
        statuses = []
    selected = next(
        (
            status
            for status in statuses
            if isinstance(status, dict) and status.get("target") == "token"
        ),
        next((status for status in statuses if isinstance(status, dict)), {}),
    )
    parameter_set = properties.get("connectionParametersSet")
    if not isinstance(parameter_set, dict):
        parameter_set = {}
    values = parameter_set.get("values")
    visible_values = {}
    if isinstance(values, dict):
        visible_values = {
            key: value.get("value")
            for key, value in values.items()
            if key in {
                "instance",
                "token:InstanceName",
                "token:ResourceUri",
            }
            if isinstance(value, dict) and "value" in value
        }
    return {
        "connectionId": record.get("name"),
        "displayName": properties.get("displayName"),
        "status": selected.get("status"),
        "statusTarget": selected.get("target"),
        "authMode": parameter_set.get("name"),
        "parameterValues": visible_values,
    }


def build_reference_update_payload(
    components: dict[str, Any],
    connection_id: str,
) -> dict[str, Any]:
    normalized_connection_id = uuid.UUID(connection_id).hex
    change_token = components.get("changeToken")
    if not isinstance(change_token, str) or not change_token:
        raise ServiceNowConnectError(
            "MinimalBot component state has no concurrency change token."
        )
    reference = copy.deepcopy(find_servicenow_reference(components))
    reference["connectionId"] = normalized_connection_id
    return {
        "changeToken": change_token,
        "connectionReferenceChanges": [
            {
                "$kind": "ConnectionReferenceUpdate",
                "connectionReference": reference,
            }
        ],
    }


def _component_hash(components: dict[str, Any]) -> str:
    encoded = json.dumps(
        components,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _agentbuilder_client(
    context: dict[str, Any],
    *,
    force_account_selection: bool = False,
) -> AgentBuilderClient:
    environment = context["environment"]
    token = authenticate(
        environment["tenant_id"],
        environment["ring"],
        cache_path=TOKEN_CACHE,
        force_account_selection=force_account_selection,
    )
    return AgentBuilderClient(
        environment["power_platform_api_endpoint"],
        token,
        ring=environment["ring"],
        tenant_id=environment["tenant_id"],
        api_version=environment["api_version"],
    )


def _connectivity_client(
    context: dict[str, Any],
    *,
    force_account_selection: bool = False,
) -> ConnectivityClient:
    environment = context["environment"]
    token = authenticate(
        environment["tenant_id"],
        environment["ring"],
        cache_path=TOKEN_CACHE,
        force_account_selection=force_account_selection,
        scopes=tuple(connectivity_scopes(environment["ring"])),
    )
    return ConnectivityClient(
        environment["power_platform_api_endpoint"],
        environment["id"],
        token,
        ring=environment["ring"],
    )


def _state_base(
    context: dict[str, Any],
    components: dict[str, Any],
) -> dict[str, Any]:
    summary = summarize_components(components)
    return {
        "schemaVersion": 1,
        "intent": "DA-GA ServiceNow HRSD connection",
        "agentId": context["agent"]["id"],
        "agentSchemaName": context["agent"]["schema_name"],
        "environmentId": context["environment"]["id"],
        "ring": context["environment"]["ring"],
        "componentHash": _component_hash(components),
        "reference": summary["reference"],
        "updatedAt": _utc_now(),
    }


def inspect(context: dict[str, Any], *, offline: bool = False) -> dict[str, Any]:
    if offline:
        components = _load_json(context["snapshotPath"])
    else:
        components = _agentbuilder_client(context).fetch_components(
            context["agent"]["id"]
        )
    summary = summarize_components(components)
    result = {
        "mode": "offline" if offline else "live",
        "agentId": context["agent"]["id"],
        "environmentId": context["environment"]["id"],
        "components": summary,
    }
    if not offline:
        connectivity = _connectivity_client(context)
        connector = connectivity.get_connector()
        connector_properties = connector.get("properties")
        if not isinstance(connector_properties, dict):
            connector_properties = connector
        connections = [
            connection_summary(record)
            for record in connectivity.list_connections()
        ]
        referenced_connection = None
        referenced_error = None
        referenced_id = summary["reference"].get("connectionId")
        if referenced_id:
            try:
                referenced_connection = connection_summary(
                    connectivity.get_connection(referenced_id)
                )
            except ServiceNowConnectError as exc:
                referenced_error = str(exc)
        result["connectivity"] = {
            "connector": {
                "displayName": connector_properties.get("displayName"),
                "tier": connector_properties.get("tier"),
                "isCustomApi": connector_properties.get("isCustomApi"),
            },
            "connections": connections,
            "referencedConnection": referenced_connection,
            "referencedConnectionError": referenced_error,
        }
        state = _state_base(context, components)
        state["lastInspection"] = result
        _write_json_atomic(_state_path(context["agent"]["id"]), state)
    return result


def prepare_manual_connection(
    context: dict[str, Any],
    *,
    instance_name: str | None,
    resource_uri: str | None,
    display_name: str | None,
) -> dict[str, Any]:
    components = _agentbuilder_client(context).fetch_components(
        context["agent"]["id"]
    )
    summary = summarize_components(components)
    reference = summary["reference"]
    instance_name = instance_name or reference.get("instanceName")
    resource_uri = resource_uri or reference.get("resourceUri")
    if not instance_name or not resource_uri:
        raise ServiceNowConnectError(
            "Instance name and Entra resource URI are required."
        )
    state = _state_base(context, components)
    state["connection"] = {
        "connectionId": None,
        "displayName": (
            display_name or "ESS HR ServiceNow HRSD Connection"
        ),
        "status": "maker-action-required",
        "authMode": "entraIDUserLogin",
        "instanceName": instance_name,
        "resourceUri": resource_uri,
        "createdBySkill": False,
    }
    state["steps"] = {
        "connection": "maker-action-required",
        "signIn": "maker-action-required",
        "referenceBinding": "pending",
        "publish": "pending",
        "test": "pending",
    }
    _write_json_atomic(_state_path(context["agent"]["id"]), state)
    return {
        "status": "maker-action-required",
        "creationMode": "manual",
        "agentId": context["agent"]["id"],
        "environmentId": context["environment"]["id"],
        "connection": state["connection"],
        "instructions": [
            "Open https://copilotstudio.microsoft.com and select the target environment.",
            "Open the Employee Self-Service HR agent.",
            "Select Settings, then Connection settings.",
            "Find the ServiceNow connection and select its status link.",
            "Open the connection configuration and select Create new connection.",
            "Choose Microsoft Entra ID User Login.",
            "Enter the Instance Name and Resource URI shown in this output.",
            "Select Sign in, complete authentication, then select Submit.",
            "Wait until the status is Connected, then return to VS Code.",
        ],
        "afterCompletion": {
            "command": "python scripts/connect_servicenow_da.py inspect",
            "expected": (
                "A ServiceNow connection with status Connected and auth mode "
                "entraIDUserLogin."
            ),
        },
    }


def bind_reference(
    context: dict[str, Any],
    connection_id: str,
    *,
    confirmed: bool,
) -> dict[str, Any]:
    if not confirmed:
        raise ServiceNowConnectError(
            "Reference binding requires explicit confirmation (--yes)."
        )
    connectivity = _connectivity_client(context)
    physical = connection_summary(connectivity.get_connection(connection_id))
    if physical.get("status") != "Connected":
        raise ServiceNowConnectError(
            "The physical ServiceNow connection is not Connected."
        )

    agentbuilder = _agentbuilder_client(context)
    before = agentbuilder.fetch_components(context["agent"]["id"])
    before_summary = summarize_components(before)
    normalized_connection_id = uuid.UUID(connection_id).hex
    if before_summary["reference"].get("connectionId") == normalized_connection_id:
        after = before
        changed = False
    else:
        payload = build_reference_update_payload(before, normalized_connection_id)
        agentbuilder.update_components(context["agent"]["id"], payload)
        after = agentbuilder.fetch_components(context["agent"]["id"])
        changed = True
    after_summary = summarize_components(after)
    if after_summary["reference"].get("connectionId") != normalized_connection_id:
        raise ServiceNowConnectError(
            "MinimalBot update completed without the expected connection binding."
        )

    state_path = _state_path(context["agent"]["id"])
    state = _load_json(state_path) if state_path.exists() else _state_base(
        context,
        before,
    )
    state["referenceBinding"] = {
        "referenceId": after_summary["reference"].get("id"),
        "previousConnectionId": before_summary["reference"].get("connectionId"),
        "connectionId": normalized_connection_id,
        "changedBySkill": changed,
        "verifiedAt": _utc_now(),
    }
    steps = state.setdefault("steps", {})
    steps["referenceBinding"] = "done"
    state["componentHash"] = _component_hash(after)
    state["updatedAt"] = _utc_now()
    _write_json_atomic(state_path, state)
    return state


def publish(
    context: dict[str, Any],
    *,
    confirmed: bool,
) -> dict[str, Any]:
    if not confirmed:
        raise ServiceNowConnectError(
            "Publishing requires explicit confirmation (--yes)."
        )
    response = _agentbuilder_client(context).publish_agent(
        context["agent"]["id"]
    )
    state_path = _state_path(context["agent"]["id"])
    state = _load_json(state_path) if state_path.exists() else {
        "schemaVersion": 1,
        "agentId": context["agent"]["id"],
        "environmentId": context["environment"]["id"],
    }
    state["publish"] = {
        "completedAt": _utc_now(),
        "responseKeys": sorted(response.keys()),
    }
    steps = state.setdefault("steps", {})
    steps["publish"] = "done"
    state["updatedAt"] = _utc_now()
    _write_json_atomic(state_path, state)
    return state


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prototype DA-GA ServiceNow HRSD connection setup.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Inspect the active HR agent and ServiceNow connection state.",
    )
    inspect_parser.add_argument(
        "--offline",
        action="store_true",
        help="Use the cached component snapshot and skip live APIs.",
    )

    create_parser = subparsers.add_parser(
        "create",
        help="Show guided steps for manually creating the ServiceNow connection.",
    )
    create_parser.add_argument("--instance-name")
    create_parser.add_argument("--resource-uri")
    create_parser.add_argument("--display-name")

    bind_parser = subparsers.add_parser(
        "bind",
        help="Bind a Connected physical connection to the DA reference.",
    )
    bind_parser.add_argument("--connection-id", required=True)
    bind_parser.add_argument("--yes", action="store_true")

    publish_parser = subparsers.add_parser(
        "publish",
        help="Publish the active Dev agent.",
    )
    publish_parser.add_argument("--yes", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        context = load_context()
        if args.command == "inspect":
            result = inspect(context, offline=args.offline)
        elif args.command == "create":
            result = prepare_manual_connection(
                context,
                instance_name=args.instance_name,
                resource_uri=args.resource_uri,
                display_name=args.display_name,
            )
        elif args.command == "bind":
            result = bind_reference(
                context,
                args.connection_id,
                confirmed=args.yes,
            )
        elif args.command == "publish":
            result = publish(context, confirmed=args.yes)
        else:  # pragma: no cover
            raise ServiceNowConnectError("Unsupported command.")
    except (ServiceNowConnectError, AgentBuilderError, ValueError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
