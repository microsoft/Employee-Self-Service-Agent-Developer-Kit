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
PROVIDER_KEY = "servicenow-da-hrsd"
PROFILE_KEY = "hrsd"
LIFECYCLE_SCHEMA_VERSION = 2


class ServiceNowConnectError(RuntimeError):
    """Raised when the DA-GA ServiceNow prototype cannot proceed safely."""

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.details = details


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


def _legacy_state_path(agent_id: str) -> Path:
    return Path(".local/connect/servicenow/agents") / agent_id / "state.json"


def _agent_slug(context: dict[str, Any]) -> str:
    agent = context.get("agent")
    active = context.get("active")
    if isinstance(agent, dict):
        slug = agent.get("workspace_slug")
        if isinstance(slug, str) and slug:
            return slug
    if isinstance(active, dict):
        slug = active.get("slug")
        if isinstance(slug, str) and slug:
            return slug
    if isinstance(agent, dict):
        agent_id = agent.get("id")
        if isinstance(agent_id, str) and agent_id:
            return agent_id
    raise ServiceNowConnectError("The active agent has no workspace slug.")


def _lifecycle_state_path(context: dict[str, Any]) -> Path:
    return (
        Path(".local/connect")
        / PROVIDER_KEY
        / "agents"
        / _agent_slug(context)
        / "lifecycle.json"
    )


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
    if canonical.get("authoring_ready") is not True:
        raise ServiceNowConnectError(
            "DA foundation setup is not ready for authoring."
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
    topic_summaries = sorted(
        (
            {
                "id": change["component"].get("id"),
                "version": change["component"].get("version"),
                "displayName": change["component"].get("displayName"),
                "schemaName": change["component"].get("schemaName"),
                "state": change["component"].get("state"),
                "status": change["component"].get("status"),
            }
            for change in service_now_topics
            if isinstance(change.get("component"), dict)
        ),
        key=lambda item: str(item.get("displayName") or ""),
    )
    return {
        "botComponentCount": len(components.get("botComponentChanges") or []),
        "serviceNowTopicCount": len(service_now_topics),
        "activeServiceNowTopicCount": sum(
            1
            for change in service_now_topics
            if isinstance(change.get("component"), dict)
            and change["component"].get("state") == "Active"
            and change["component"].get("status") == "Active"
        ),
        "serviceNowTopics": topic_summaries,
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


def find_servicenow_topic(
    components: dict[str, Any],
    topic_id: str,
) -> dict[str, Any]:
    normalized_topic_id = str(uuid.UUID(topic_id))
    for change in components.get("botComponentChanges") or []:
        component = change.get("component")
        if (
            isinstance(component, dict)
            and str(component.get("id") or "").casefold()
            == normalized_topic_id.casefold()
            and "ServiceNowHRSD" in str(component.get("schemaName") or "")
        ):
            return component
    raise ServiceNowConnectError(
        "The requested ServiceNow topic was not found in the active agent."
    )


def build_topic_state_update_payload(
    components: dict[str, Any],
    topic_id: str,
    target_state: str,
) -> dict[str, Any]:
    if target_state not in {"Active", "Inactive"}:
        raise ServiceNowConnectError(
            "Topic state must be Active or Inactive."
        )
    change_token = components.get("changeToken")
    if not isinstance(change_token, str) or not change_token:
        raise ServiceNowConnectError(
            "MinimalBot component state has no concurrency change token."
        )
    component = copy.deepcopy(find_servicenow_topic(components, topic_id))
    if component.get("$kind") != "DialogComponent":
        raise ServiceNowConnectError(
            "The requested ServiceNow component is not a dialog topic."
        )
    if not component.get("id") or not isinstance(component.get("version"), int):
        raise ServiceNowConnectError(
            "The requested ServiceNow topic lacks identity or version evidence."
        )
    component["state"] = target_state
    component["status"] = target_state
    return {
        "changeToken": change_token,
        "botComponentChanges": [
            {
                "$kind": "BotComponentUpdate",
                "component": component,
            }
        ],
    }


def build_enable_all_topics_payload(
    components: dict[str, Any],
) -> dict[str, Any]:
    change_token = components.get("changeToken")
    if not isinstance(change_token, str) or not change_token:
        raise ServiceNowConnectError(
            "MinimalBot component state has no concurrency change token."
        )
    changes = []
    for change in components.get("botComponentChanges") or []:
        component = change.get("component")
        if (
            not isinstance(component, dict)
            or "ServiceNowHRSD" not in str(component.get("schemaName") or "")
            or (
                component.get("state") == "Active"
                and component.get("status") == "Active"
            )
        ):
            continue
        topic_id = component.get("id")
        if not topic_id:
            raise ServiceNowConnectError(
                "A ServiceNow topic lacks identity evidence."
            )
        topic_payload = build_topic_state_update_payload(
            components,
            str(topic_id),
            "Active",
        )
        changes.extend(topic_payload["botComponentChanges"])
    return {
        "changeToken": change_token,
        "botComponentChanges": changes,
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
        "schemaVersion": LIFECYCLE_SCHEMA_VERSION,
        "provider": PROVIDER_KEY,
        "profile": PROFILE_KEY,
        "intent": "DA-GA ServiceNow HRSD connection",
        "agentSlug": _agent_slug(context),
        "agentId": context["agent"]["id"],
        "agentSchemaName": context["agent"]["schema_name"],
        "environmentId": context["environment"]["id"],
        "ring": context["environment"]["ring"],
        "componentHash": _component_hash(components),
        "reference": summary["reference"],
        "phases": {},
        "evidence": {},
        "transactions": {"topics": {}},
        "migration": {},
        "updatedAt": _utc_now(),
    }


def _canonical_json_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_state_identity(
    context: dict[str, Any],
    state: dict[str, Any],
) -> None:
    expected = {
        "agentId": context["agent"]["id"],
        "environmentId": context["environment"]["id"],
    }
    for key, value in expected.items():
        recorded = state.get(key)
        if recorded and str(recorded).casefold() != str(value).casefold():
            raise ServiceNowConnectError(
                f"ServiceNow lifecycle {key} does not match the active agent."
            )


def _migrate_legacy_state(
    context: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    legacy_path = _legacy_state_path(context["agent"]["id"])
    if not legacy_path.exists():
        return state
    legacy = _load_json(legacy_path)
    _validate_state_identity(context, legacy)
    digest = _canonical_json_hash(legacy)
    migration = state.setdefault("migration", {})
    if migration.get("legacySha256") == digest:
        return state

    evidence = state.setdefault("evidence", {})
    mapping = {
        "topicEnablement": "topics",
        "connection": "credentialPreparation",
        "publish": "publish",
    }
    phase_for_evidence = {
        "topics": "topics",
        "credentialPreparation": "credential",
        "publish": "publish",
    }
    imported: list[str] = []
    conflicts = list(migration.get("conflicts") or [])
    for legacy_key, evidence_key in mapping.items():
        value = legacy.get(legacy_key)
        if not isinstance(value, dict):
            continue
        record_id = _canonical_json_hash({legacy_key: value})
        existing = evidence.get(evidence_key)
        if isinstance(existing, dict) and existing != value:
            conflicts.append(
                {
                    "field": evidence_key,
                    "legacyRecordId": record_id,
                    "recordedAt": _utc_now(),
                }
            )
            phase = state.setdefault("phases", {}).setdefault(
                phase_for_evidence[evidence_key],
                {"checkpointResults": {}},
            )
            phase["status"] = "in-progress"
            continue
        evidence.setdefault(evidence_key, copy.deepcopy(value))
        imported.append(record_id)

    for legacy_key, evidence_key in (
        ("agentConnection", "agentConnection"),
        ("parameterSharing", "parameterSharing"),
        ("test", "test"),
    ):
        value = legacy.get(legacy_key)
        if not isinstance(value, dict):
            continue
        record_id = _canonical_json_hash({legacy_key: value})
        target = evidence.setdefault(evidence_key, {})
        if not isinstance(target, dict):
            target = {}
            evidence[evidence_key] = target
        existing_legacy = target.get("legacy")
        if isinstance(existing_legacy, dict) and existing_legacy != value:
            conflicts.append(
                {
                    "field": evidence_key,
                    "legacyRecordId": record_id,
                    "recordedAt": _utc_now(),
                }
            )
        else:
            target.setdefault("legacy", copy.deepcopy(value))
            target["reconfirmRequired"] = True
            imported.append(record_id)

    migration.update(
        {
            "legacySourcePath": str(legacy_path),
            "legacySchemaVersion": legacy.get("schemaVersion"),
            "legacySha256": digest,
            "completedAt": _utc_now(),
            "importedRecordIds": sorted(
                set(migration.get("importedRecordIds") or []) | set(imported)
            ),
            "conflicts": conflicts,
            "legacySteps": copy.deepcopy(legacy.get("steps") or {}),
            "lastLegacyInspection": copy.deepcopy(
                legacy.get("lastInspection")
            ),
        }
    )
    return state


def _load_lifecycle_state(
    context: dict[str, Any],
    components: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = _lifecycle_state_path(context)
    if path.exists():
        state = _load_json(path)
        _validate_state_identity(context, state)
    elif components is not None:
        state = _state_base(context, components)
    else:
        state = {
            "schemaVersion": LIFECYCLE_SCHEMA_VERSION,
            "provider": PROVIDER_KEY,
            "profile": PROFILE_KEY,
            "intent": "DA-GA ServiceNow HRSD connection",
            "agentSlug": _agent_slug(context),
            "agentId": context["agent"]["id"],
            "agentSchemaName": context["agent"].get("schema_name"),
            "environmentId": context["environment"]["id"],
            "ring": context["environment"].get("ring"),
            "phases": {},
            "evidence": {},
            "transactions": {"topics": {}},
            "migration": {},
        }
    state = _migrate_legacy_state(context, state)
    if components is not None:
        current = _state_base(context, components)
        for key in (
            "schemaVersion",
            "provider",
            "profile",
            "intent",
            "agentSlug",
            "agentId",
            "agentSchemaName",
            "environmentId",
            "ring",
            "componentHash",
            "reference",
        ):
            state[key] = current[key]
    state.setdefault("phases", {})
    state.setdefault("evidence", {})
    state.setdefault("transactions", {}).setdefault("topics", {})
    state.setdefault("migration", {})
    return state


def _write_lifecycle_state(
    context: dict[str, Any],
    state: dict[str, Any],
) -> None:
    path = _lifecycle_state_path(context)
    if path.exists():
        existing = _load_json(path)
        before = copy.deepcopy(existing)
        after = copy.deepcopy(state)
        before.pop("updatedAt", None)
        after.pop("updatedAt", None)
        if before == after:
            state["updatedAt"] = existing.get("updatedAt")
            return
    state["updatedAt"] = _utc_now()
    _write_json_atomic(path, state)


def _state_for_components(
    context: dict[str, Any],
    components: dict[str, Any],
) -> dict[str, Any]:
    return _load_lifecycle_state(context, components)


def _inspection_progress(
    state: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, dict[str, str]]:
    components = result["components"]
    connections = result.get("connectivity", {}).get("connections", [])
    connected = {
        str(connection.get("connectionId")): connection
        for connection in connections
        if connection.get("status") == "Connected"
        and connection.get("authMode") == "entraIDUserLogin"
    }
    evidence = state.get("evidence")
    if not isinstance(evidence, dict):
        evidence = {}

    total_topics = components["serviceNowTopicCount"]
    active_topics = components["activeServiceNowTopicCount"]
    topic_enablement = evidence.get("topics")
    kept_current_topics = (
        isinstance(topic_enablement, dict)
        and topic_enablement.get("customerChoice") == "keep-current"
        and topic_enablement.get("boundComponentHash")
        == state.get("componentHash")
    )
    topics_done = (
        total_topics > 0 and active_topics == total_topics
    ) or kept_current_topics

    attestation = evidence.get("agentConnection")
    if not isinstance(attestation, dict):
        attestation = {}
    attested_connection_id = str(attestation.get("connectionId") or "")
    agent_connection_done = (
        attestation.get("makerAttested") is True
        and attested_connection_id in connected
    )

    publish_record = evidence.get("publish")
    if not isinstance(publish_record, dict):
        publish_record = {}
    published_hash = publish_record.get("componentHash")
    current_hash = state.get("componentHash")
    publish_done = (
        publish_record.get("status") == "completed"
        and (
            published_hash == current_hash
            or published_hash is None
        )
    )

    test_record = evidence.get("test")
    if not isinstance(test_record, dict):
        test_record = {}
    test_result = test_record.get("result")

    parameter_record = evidence.get("parameterSharing")
    if not isinstance(parameter_record, dict):
        parameter_record = {}
    parameter_status = parameter_record.get("status")
    return {
        "topics": {
            "status": "done" if topics_done else "pending",
            "message": (
                f"{active_topics}/{total_topics} ServiceNow HRSD topics are "
                f"active."
            ),
        },
        "credential": {
            "status": "done" if connected else "pending",
            "message": (
                f"{len(connected)} Connected Entra user-login ServiceNow "
                "credential(s) found."
            ),
        },
        "agentConnection": {
            "status": (
                "confirmation-required"
                if connected
                else "pending"
            ),
            "message": (
                "A prior maker attestation is recorded and the selected "
                "credential is still Connected, but the current agent UI "
                "binding requires maker confirmation."
                if agent_connection_done
                else (
                    "Maker confirmation of the agent's ServiceNow row is "
                    "required."
                )
            ),
        },
        "parameterSharing": {
            "status": (
                "confirmation-required"
                if parameter_status in {"enabled", "not-exposed"}
                else "pending"
            ),
            "message": (
                f"Parameter sharing was recorded as {parameter_status}; "
                "the current UI state requires maker confirmation."
                if parameter_status
                else "Parameter-sharing availability has not been recorded."
            ),
        },
        "publish": {
            "status": "done" if publish_done else "pending",
            "message": (
                "The current component revision is recorded as published."
                if publish_done
                else "The current component revision is not recorded as published."
            ),
        },
        "test": {
            "status": (
                "confirmation-required"
                if test_result in {"pass", "fail"}
                else "pending"
            ),
            "message": (
                "A passing Test pane result was previously recorded; a "
                "current functional result requires maker confirmation."
                if test_result == "pass"
                else (
                    "A failing Test pane result was previously recorded; a "
                    "current functional result requires maker confirmation."
                )
                if test_result == "fail"
                else "Functional Test pane validation has not been recorded."
            ),
        },
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
        result["connectivity"] = {
            "connector": {
                "displayName": connector_properties.get("displayName"),
                "tier": connector_properties.get("tier"),
                "isCustomApi": connector_properties.get("isCustomApi"),
            },
            "connections": connections,
            "userConnectionBinding": {
                "mode": "maker-ui",
                "automationAvailable": False,
                "requiredDelegatedScope": "PowerVirtualAgents.Tokens.Read",
            },
        }
        state = _state_for_components(context, components)
        result["progress"] = _inspection_progress(state, result)
        state.setdefault("evidence", {})["lastInspection"] = result
        _write_lifecycle_state(context, state)
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
        missing_fields = []
        if not instance_name:
            missing_fields.append("instanceName")
        if not resource_uri:
            missing_fields.append("resourceUri")
        return {
            "status": "input-required",
            "creationMode": "manual",
            "agentId": context["agent"]["id"],
            "environmentId": context["environment"]["id"],
            "missingFields": missing_fields,
            "knownValues": {
                "instanceName": instance_name,
                "resourceUri": resource_uri,
            },
            "message": (
                "The installed connection reference does not contain every "
                "value required to create the ServiceNow connection."
            ),
        }
    state = _state_for_components(context, components)
    preparation = {
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
    state.setdefault("evidence", {})["credentialPreparation"] = preparation
    _write_lifecycle_state(context, state)
    return {
        "status": "maker-action-required",
        "creationMode": "manual",
        "agentId": context["agent"]["id"],
        "environmentId": context["environment"]["id"],
        "connection": preparation,
        "instructions": [
            "Open https://copilotstudio.microsoft.com and select the target environment.",
            "Open the Employee Self-Service HR agent.",
            "Select Settings, then Connection settings.",
            "Find the ServiceNow connection and select its status link.",
            "Open the connection configuration and select Create new connection.",
            "Choose Microsoft Entra ID User Login.",
            "Enter the Instance Name and Resource URI shown in this output.",
            "Select Sign in, complete authentication, then select Submit.",
            "Wait until the credential status is Connected.",
            "Return to Connection settings and select Connect for ServiceNow.",
            "Choose the new connection and save the agent connection.",
            "Return to VS Code after the ServiceNow row shows Connected.",
        ],
        "afterCompletion": {
            "command": "python scripts/connect_servicenow_da.py inspect",
            "expected": (
                "A ServiceNow credential with status Connected, followed by "
                "maker confirmation that it was connected to the agent."
            ),
        },
    }


def _healthy_connection(
    context: dict[str, Any],
    connection_id: str,
) -> dict[str, Any]:
    connectivity = _connectivity_client(context)
    physical = connection_summary(connectivity.get_connection(connection_id))
    if physical.get("status") != "Connected":
        raise ServiceNowConnectError(
            "The physical ServiceNow connection is not Connected."
        )
    if physical.get("authMode") != "entraIDUserLogin":
        raise ServiceNowConnectError(
            "The physical ServiceNow connection must use Microsoft Entra ID "
            "User Login."
        )
    return physical


def record_credential_selection(
    context: dict[str, Any],
    connection_id: str,
) -> dict[str, Any]:
    physical = _healthy_connection(context, connection_id)
    components = _agentbuilder_client(context).fetch_components(
        context["agent"]["id"]
    )
    normalized_connection_id = uuid.UUID(connection_id).hex
    evidence = {
        "connectionId": normalized_connection_id,
        "displayName": physical.get("displayName"),
        "connectorId": CONNECTOR_ID,
        "physicalStatus": physical.get("status"),
        "authMode": physical.get("authMode"),
        "environmentId": context["environment"]["id"],
        "selectedAt": _utc_now(),
        "lastVerifiedAt": _utc_now(),
        "parameterMetadata": copy.deepcopy(
            physical.get("parameterValues") or {}
        ),
    }
    state = _load_lifecycle_state(context, components)
    state.setdefault("evidence", {})["credential"] = evidence
    _write_lifecycle_state(context, state)
    return evidence


def record_agent_connection_attestation(
    context: dict[str, Any],
    connection_id: str,
) -> dict[str, Any]:
    physical = _healthy_connection(context, connection_id)
    components = _agentbuilder_client(context).fetch_components(
        context["agent"]["id"]
    )

    normalized_connection_id = uuid.UUID(connection_id).hex
    state = _load_lifecycle_state(context, components)
    result = {
        "kind": "maker-attestation",
        "mode": "maker-ui",
        "connectionId": normalized_connection_id,
        "displayName": physical.get("displayName"),
        "physicalStatus": physical.get("status"),
        "authMode": physical.get("authMode"),
        "makerAttested": True,
        "recordedAt": _utc_now(),
        "physicalVerifiedAt": _utc_now(),
        "binding": {
            "connectionId": normalized_connection_id,
            "environmentId": context["environment"]["id"],
            "agentId": context["agent"]["id"],
            "agentSlug": _agent_slug(context),
            "provider": PROVIDER_KEY,
            "profile": PROFILE_KEY,
            "componentHash": _component_hash(components),
        },
    }
    evidence = state.setdefault("evidence", {})
    selected = evidence.get("credential")
    if (
        isinstance(selected, dict)
        and selected.get("connectionId")
        and str(selected["connectionId"]).casefold()
        != normalized_connection_id.casefold()
    ):
        raise ServiceNowConnectError(
            "The attested Agent Connect credential differs from the selected "
            "lifecycle credential. Record the intended credential first."
        )
    evidence["agentConnection"] = result
    evidence.setdefault(
        "credential",
        {
            "connectionId": normalized_connection_id,
            "displayName": physical.get("displayName"),
            "connectorId": CONNECTOR_ID,
            "physicalStatus": physical.get("status"),
            "authMode": physical.get("authMode"),
            "environmentId": context["environment"]["id"],
            "selectedAt": _utc_now(),
            "lastVerifiedAt": _utc_now(),
        },
    )
    _write_lifecycle_state(context, state)
    return result


def record_parameter_sharing(
    context: dict[str, Any],
    status: str,
) -> dict[str, Any]:
    if status not in {"enabled", "not-exposed"}:
        raise ServiceNowConnectError(
            "Parameter-sharing status must be enabled or not-exposed."
        )
    components = _agentbuilder_client(context).fetch_components(
        context["agent"]["id"]
    )
    state = _load_lifecycle_state(context, components)
    credential = state.get("evidence", {}).get("credential", {})
    if not isinstance(credential, dict) or not credential.get("connectionId"):
        raise ServiceNowConnectError(
            "Select and verify a ServiceNow credential before recording "
            "parameter sharing."
        )
    result = {
        "kind": "maker-attestation",
        "status": status,
        "makerAttested": True,
        "recordedAt": _utc_now(),
        "binding": {
            "connectionId": credential.get("connectionId"),
            "environmentId": context["environment"]["id"],
            "agentId": context["agent"]["id"],
            "agentSlug": _agent_slug(context),
            "componentHash": _component_hash(components),
        },
    }
    state.setdefault("evidence", {})["parameterSharing"] = result
    _write_lifecycle_state(context, state)
    return result


def set_topic_state(
    context: dict[str, Any],
    topic_id: str,
    target_state: str,
    *,
    confirmed: bool,
) -> dict[str, Any]:
    if not confirmed:
        raise ServiceNowConnectError(
            "Topic state mutation requires explicit confirmation (--yes)."
        )
    agentbuilder = _agentbuilder_client(context)
    before = agentbuilder.fetch_components(context["agent"]["id"])
    before_topic = find_servicenow_topic(before, topic_id)
    before_state = before_topic.get("state")
    before_status = before_topic.get("status")
    changed = (
        before_state != target_state
        or before_status != target_state
    )
    if changed:
        payload = build_topic_state_update_payload(
            before,
            topic_id,
            target_state,
        )
        agentbuilder.update_components(context["agent"]["id"], payload)
    after = agentbuilder.fetch_components(context["agent"]["id"])
    after_topic = find_servicenow_topic(after, topic_id)
    if (
        after_topic.get("state") != target_state
        or after_topic.get("status") != target_state
    ):
        raise ServiceNowConnectError(
            "MinimalBot update completed without the expected topic state."
        )
    return {
        "topicId": str(uuid.UUID(topic_id)),
        "displayName": after_topic.get("displayName"),
        "schemaName": after_topic.get("schemaName"),
        "previousState": before_state,
        "previousStatus": before_status,
        "state": after_topic.get("state"),
        "status": after_topic.get("status"),
        "previousVersion": before_topic.get("version"),
        "version": after_topic.get("version"),
        "changed": changed,
        "published": False,
    }


def _servicenow_topic_components(
    components: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    topics: dict[str, dict[str, Any]] = {}
    for change in components.get("botComponentChanges") or []:
        component = change.get("component")
        if (
            isinstance(component, dict)
            and "ServiceNowHRSD" in str(component.get("schemaName") or "")
            and component.get("id")
        ):
            topics[str(component["id"]).casefold()] = component
    return topics


def _component_content_hash(component: dict[str, Any]) -> str:
    normalized = copy.deepcopy(component)
    normalized.pop("version", None)
    normalized.pop("auditInfo", None)
    return _canonical_json_hash(normalized)


def _topic_transaction_diagnostics(
    transaction: dict[str, Any],
) -> dict[str, Any]:
    rollback_statuses = transaction.get("topics")
    if not isinstance(rollback_statuses, dict):
        rollback_statuses = {}
    targets = transaction.get("targets")
    if not isinstance(targets, dict):
        targets = {}
    target_summaries = []
    for topic_id, target in sorted(targets.items())[:20]:
        if not isinstance(target, dict):
            continue
        component = target.get("component")
        display_name = (
            component.get("displayName")
            if isinstance(component, dict)
            else None
        )
        target_summaries.append(
            {
                "topicId": topic_id,
                "displayName": display_name,
                "beforeVersion": target.get("beforeVersion"),
                "postVersion": target.get("postVersion"),
                "ownershipStatus": target.get("ownershipStatus"),
                "changedByOperation": target.get("changedByOperation"),
                "rollbackStatus": rollback_statuses.get(topic_id),
            }
        )
    details = {
        "operationId": transaction.get("operationId"),
        "transactionStatus": transaction.get("status"),
        "mutationMayHaveOccurred": transaction.get(
            "mutationMayHaveOccurred"
        ),
        "updateError": transaction.get("updateError"),
        "reconciliationError": transaction.get("reconciliationError"),
        "rollbackError": transaction.get("rollbackError"),
        "before": transaction.get("before"),
        "after": transaction.get("after"),
        "targets": target_summaries,
    }
    remediation = transaction.get("remediation")
    if isinstance(remediation, str) and remediation:
        details["remediation"] = remediation
    if len(targets) > len(target_summaries):
        details["omittedTargetCount"] = len(targets) - len(target_summaries)
    return details


def _rollback_topic_transaction(
    context: dict[str, Any],
    agentbuilder: AgentBuilderClient,
    state: dict[str, Any],
    operation_id: str,
) -> dict[str, Any]:
    transactions = state.setdefault("transactions", {}).setdefault(
        "topics", {}
    )
    transaction = transactions.get(operation_id)
    if not isinstance(transaction, dict):
        raise ServiceNowConnectError(
            f"Unknown topic transaction: {operation_id}"
        )
    current = agentbuilder.fetch_components(context["agent"]["id"])
    current_topics = _servicenow_topic_components(current)
    changes = []
    statuses: dict[str, str] = {}
    for topic_id, target in transaction.get("targets", {}).items():
        if not isinstance(target, dict):
            continue
        current_topic = current_topics.get(topic_id.casefold())
        if current_topic is None:
            statuses[topic_id] = "missing"
            continue
        current_hash = _component_content_hash(current_topic)
        pre_hash = target.get("beforeContentHashExcludingVersion")
        if pre_hash and current_hash == pre_hash:
            statuses[topic_id] = "restored"
            continue
        if target.get("ownershipStatus") != "owned":
            statuses[topic_id] = "conflict"
            continue
        expected_post_hash = target.get(
            "expectedPostContentHashExcludingVersion"
        )
        if (
            not expected_post_hash
            or current_hash != expected_post_hash
        ):
            statuses[topic_id] = "conflict"
            continue
        preimage = target.get("component")
        if not isinstance(preimage, dict):
            statuses[topic_id] = "missing"
            continue
        restored = copy.deepcopy(preimage)
        restored["version"] = current_topic.get("version")
        changes.append(
            {
                "$kind": "BotComponentUpdate",
                "component": restored,
            }
        )
        statuses[topic_id] = "pending"
    if any(value in {"conflict", "missing"} for value in statuses.values()):
        transaction.update(
            {
                "status": "rollback-incomplete",
                "rolledBackAt": _utc_now(),
                "topics": statuses,
                "remediation": (
                    "Review conflicting or missing topics before restoring "
                    "their pre-mutation content."
                ),
            }
        )
        _write_lifecycle_state(context, state)
        return transaction
    rollback_error: Exception | None = None
    if changes:
        token = current.get("changeToken")
        if not isinstance(token, str) or not token:
            raise ServiceNowConnectError(
                "Cannot roll back topics without a fresh change token."
            )
        try:
            agentbuilder.update_components(
                context["agent"]["id"],
                {
                    "changeToken": token,
                    "botComponentChanges": changes,
                },
            )
        except Exception as exc:
            rollback_error = exc
    verified = agentbuilder.fetch_components(context["agent"]["id"])
    verified_topics = _servicenow_topic_components(verified)
    for topic_id, target in transaction.get("targets", {}).items():
        restored = verified_topics.get(topic_id.casefold())
        preimage = target.get("component") if isinstance(target, dict) else None
        if (
            restored is None
            or not isinstance(preimage, dict)
        ):
            statuses[topic_id] = "pending"
        elif (
            _component_content_hash(restored)
            == _component_content_hash(preimage)
        ):
            statuses[topic_id] = "restored"
        elif (
            target.get("expectedPostContentHashExcludingVersion")
            and _component_content_hash(restored)
            == target["expectedPostContentHashExcludingVersion"]
        ):
            statuses[topic_id] = "pending"
        else:
            statuses[topic_id] = "conflict"
    transaction.update(
        {
            "status": (
                "rolled-back"
                if all(value == "restored" for value in statuses.values())
                else "rollback-incomplete"
            ),
            "rolledBackAt": _utc_now(),
            "topics": statuses,
        }
    )
    if transaction["status"] != "rolled-back":
        transaction["remediation"] = (
            "Refetch the pending topics and retry rollback only when their "
            "current content still matches the provider-owned postimage."
        )
        if rollback_error is not None:
            transaction["rollbackError"] = type(rollback_error).__name__
    _write_lifecycle_state(context, state)
    return transaction


def rollback_topic_transaction(
    context: dict[str, Any],
    operation_id: str,
    *,
    confirmed: bool,
) -> dict[str, Any]:
    if not confirmed:
        raise ServiceNowConnectError(
            "Topic rollback requires explicit confirmation (--yes)."
        )
    state = _load_lifecycle_state(context)
    return _rollback_topic_transaction(
        context,
        _agentbuilder_client(context),
        state,
        operation_id,
    )


def enable_all_servicenow_topics(
    context: dict[str, Any],
    *,
    confirmed: bool,
) -> dict[str, Any]:
    if not confirmed:
        raise ServiceNowConnectError(
            "Enabling all ServiceNow topics requires explicit confirmation "
            "(--yes)."
        )
    agentbuilder = _agentbuilder_client(context)
    before = agentbuilder.fetch_components(context["agent"]["id"])
    before_summary = summarize_components(before)
    inactive = [
        topic
        for topic in before_summary["serviceNowTopics"]
        if topic.get("state") != "Active"
        or topic.get("status") != "Active"
    ]
    if inactive:
        payload = build_enable_all_topics_payload(before)
    state = _load_lifecycle_state(context, before)
    operation_id = str(uuid.uuid4())
    transaction = {
        "operationId": operation_id,
        "status": "prepared",
        "preparedAt": _utc_now(),
        "changeTokenHash": _canonical_json_hash(before.get("changeToken")),
        "beforeComponentHash": _component_hash(before),
        "before": {
            "total": before_summary["serviceNowTopicCount"],
            "active": before_summary["activeServiceNowTopicCount"],
            "inactive": len(inactive),
        },
        "targets": {
            str(topic["id"]): {
                "beforeVersion": topic.get("version"),
                "beforeContentHashExcludingVersion": _component_content_hash(
                    find_servicenow_topic(before, str(topic["id"]))
                ),
                "component": copy.deepcopy(
                    find_servicenow_topic(before, str(topic["id"]))
                ),
                "expectedPostContentHashExcludingVersion": (
                    _component_content_hash(
                        {
                            **copy.deepcopy(
                                find_servicenow_topic(
                                    before,
                                    str(topic["id"]),
                                )
                            ),
                            "state": "Active",
                            "status": "Active",
                        }
                    )
                ),
            }
            for topic in inactive
        },
    }
    state.setdefault("transactions", {}).setdefault("topics", {})[
        operation_id
    ] = transaction
    _write_lifecycle_state(context, state)
    update_error: Exception | None = None
    if inactive:
        try:
            agentbuilder.update_components(context["agent"]["id"], payload)
        except Exception as exc:  # refetch decides whether rollback is needed
            update_error = exc
        transaction.update(
            {
                "status": "reconciliation-required",
                "mutationMayHaveOccurred": True,
                "mutationAttemptedAt": _utc_now(),
                "updateError": (
                    type(update_error).__name__
                    if update_error is not None
                    else None
                ),
            }
        )
        _write_lifecycle_state(context, state)
    try:
        after = agentbuilder.fetch_components(context["agent"]["id"])
    except Exception as exc:
        transaction.update(
            {
                "status": "reconciliation-required",
                "mutationMayHaveOccurred": bool(inactive),
                "reconciliationError": type(exc).__name__,
                "reconciliationFailedAt": _utc_now(),
                "remediation": (
                    "Refetch the agent components before any rollback. "
                    "Ownership of the remote postimage is not established."
                ),
            }
        )
        _write_lifecycle_state(context, state)
        raise ServiceNowConnectError(
            "ServiceNow topic mutation may have occurred, but the required "
            "post-update refetch failed. Do not roll back until ownership "
            "can be established from a fresh component fetch.",
            details=_topic_transaction_diagnostics(transaction),
        ) from exc
    after_summary = summarize_components(after)
    transaction["after"] = {
        "total": after_summary["serviceNowTopicCount"],
        "active": after_summary["activeServiceNowTopicCount"],
        "inactive": (
            after_summary["serviceNowTopicCount"]
            - after_summary["activeServiceNowTopicCount"]
        ),
    }
    after_topics = _servicenow_topic_components(after)
    for topic_id, target in transaction["targets"].items():
        postimage = after_topics.get(topic_id.casefold())
        if postimage is None:
            target["ownershipStatus"] = "missing"
            target["changedByOperation"] = None
            continue
        target["postVersion"] = postimage.get("version")
        target["postContentHashExcludingVersion"] = _component_content_hash(
            postimage
        )
        if (
            target["postContentHashExcludingVersion"]
            == target["expectedPostContentHashExcludingVersion"]
        ):
            target["ownershipStatus"] = "owned"
            target["changedByOperation"] = True
        elif (
            target["postContentHashExcludingVersion"]
            == target["beforeContentHashExcludingVersion"]
        ):
            target["ownershipStatus"] = "unchanged"
            target["changedByOperation"] = False
        else:
            target["ownershipStatus"] = "conflict"
            target["changedByOperation"] = None
    not_active = [
        topic
        for topic in after_summary["serviceNowTopics"]
        if topic.get("state") != "Active"
        or topic.get("status") != "Active"
    ]
    target_issues = [
        topic_id
        for topic_id, target in transaction["targets"].items()
        if target.get("ownershipStatus") in {"missing", "conflict"}
    ]
    if update_error is not None or not_active or target_issues:
        changed = any(
            target.get("ownershipStatus") in {"owned", "missing", "conflict"}
            for target in transaction["targets"].values()
        )
        if not changed:
            transaction.update(
                {
                    "status": "failed-no-mutation",
                    "afterComponentHash": _component_hash(after),
                    "failedAt": _utc_now(),
                }
            )
            _write_lifecycle_state(context, state)
            raise ServiceNowConnectError(
                "ServiceNow topic update failed before any topic mutation.",
                details=_topic_transaction_diagnostics(transaction),
            ) from update_error
        transaction["status"] = "rollback-required"
        transaction["afterComponentHash"] = _component_hash(after)
        _write_lifecycle_state(context, state)
        rollback = _rollback_topic_transaction(
            context,
            agentbuilder,
            state,
            operation_id,
        )
        if rollback.get("status") != "rolled-back":
            raise ServiceNowConnectError(
                "ServiceNow topic update failed and automatic rollback is "
                "incomplete; review the transaction remediation.",
                details=_topic_transaction_diagnostics(rollback),
            ) from update_error
        names = ", ".join(
            str(topic.get("displayName") or topic.get("id"))
            for topic in not_active
        )
        raise ServiceNowConnectError(
            (
                "ServiceNow topic update failed and was rolled back safely."
                if update_error is not None
                else "MinimalBot update left inactive topics and was rolled "
                f"back safely: {names}."
            ),
            details=_topic_transaction_diagnostics(rollback),
        ) from update_error
    result = {
        "status": "updated" if inactive else "already-active",
        "customerChoice": "enable-all",
        "before": {
            "total": before_summary["serviceNowTopicCount"],
            "active": before_summary["activeServiceNowTopicCount"],
            "inactive": len(inactive),
        },
        "changedTopics": [
            {
                "id": topic.get("id"),
                "displayName": topic.get("displayName"),
                "previousState": topic.get("state"),
                "previousStatus": topic.get("status"),
            }
            for topic in inactive
        ],
        "after": {
            "total": after_summary["serviceNowTopicCount"],
            "active": after_summary["activeServiceNowTopicCount"],
            "inactive": len(not_active),
        },
        "published": False,
        "operationId": operation_id,
        "transactionStatus": "committed",
    }
    transaction.update(
        {
            "status": "committed",
            "committedAt": _utc_now(),
            "afterComponentHash": _component_hash(after),
        }
    )
    state.setdefault("evidence", {})["topics"] = result
    state["componentHash"] = _component_hash(after)
    _write_lifecycle_state(context, state)
    return result


def record_keep_current_topic_choice(
    context: dict[str, Any],
) -> dict[str, Any]:
    components = _agentbuilder_client(context).fetch_components(
        context["agent"]["id"]
    )
    summary = summarize_components(components)
    counts = {
        "total": summary["serviceNowTopicCount"],
        "active": summary["activeServiceNowTopicCount"],
        "inactive": (
            summary["serviceNowTopicCount"]
            - summary["activeServiceNowTopicCount"]
        ),
    }
    result = {
        "status": "recorded",
        "customerChoice": "keep-current",
        "before": counts,
        "changedTopics": [],
        "after": counts,
        "published": False,
    }
    result["boundComponentHash"] = _component_hash(components)
    result["topicStates"] = summary["serviceNowTopics"]
    result["makerAttested"] = True
    result["recordedAt"] = _utc_now()
    state = _load_lifecycle_state(context, components)
    state.setdefault("evidence", {})["topics"] = result
    state["componentHash"] = _component_hash(components)
    _write_lifecycle_state(context, state)
    return result


def publish(
    context: dict[str, Any],
    *,
    confirmed: bool,
) -> dict[str, Any]:
    if not confirmed:
        raise ServiceNowConnectError(
            "Publishing requires explicit confirmation (--yes)."
        )
    agentbuilder = _agentbuilder_client(context)
    components = agentbuilder.fetch_components(context["agent"]["id"])
    state = _load_lifecycle_state(context, components)
    requested_at = _utc_now()
    try:
        response = agentbuilder.publish_agent(context["agent"]["id"])
    except Exception as exc:
        state.setdefault("evidence", {})["publish"] = {
            "requestedAt": requested_at,
            "status": "needs_remediation",
            "mutationMayHaveOccurred": True,
            "componentHash": _component_hash(components),
            "errorCode": type(exc).__name__,
            "recordedAt": _utc_now(),
        }
        _write_lifecycle_state(context, state)
        raise ServiceNowConnectError(
            "Publish outcome is ambiguous. Review Copilot Studio publish "
            "details before retrying; automatic unpublish is not available."
        ) from exc
    publish_record = {
        "requestedAt": requested_at,
        "completedAt": _utc_now(),
        "agentId": context["agent"]["id"],
        "environmentId": context["environment"]["id"],
        "componentHash": _component_hash(components),
        "response": {
            "validationPending": response.get("validationPending"),
            "responseKeys": sorted(response.keys()),
        },
        "status": (
            "completed"
            if response.get("validationPending") is False
            else "confirmation-required"
        ),
        "mutationMayHaveOccurred": True,
    }
    state.setdefault("evidence", {})["publish"] = publish_record
    _write_lifecycle_state(context, state)
    return state


def record_test_attestation(
    context: dict[str, Any],
    *,
    prompt: str,
    result: str,
    details: str | None,
) -> dict[str, Any]:
    prompt = prompt.strip()
    if not prompt:
        raise ServiceNowConnectError("A Test pane prompt is required.")
    if result not in {"pass", "fail"}:
        raise ServiceNowConnectError(
            "Test pane result must be pass or fail."
        )
    components = _agentbuilder_client(context).fetch_components(
        context["agent"]["id"]
    )
    state = _load_lifecycle_state(context, components)
    evidence = state.setdefault("evidence", {})
    credential = evidence.get("credential")
    publish_record = evidence.get("publish")
    if not isinstance(credential, dict) or not credential.get("connectionId"):
        raise ServiceNowConnectError(
            "Select and verify a ServiceNow credential before recording a test."
        )
    if (
        not isinstance(publish_record, dict)
        or publish_record.get("status")
        not in {"completed", "confirmation-required"}
    ):
        raise ServiceNowConnectError(
            "Publish the current component revision before recording a test."
        )
    attestation = {
        "kind": "maker-attestation",
        "prompt": prompt,
        "result": result,
        "details": details.strip() if details else None,
        "recordedAt": _utc_now(),
        "binding": {
            "connectionId": credential["connectionId"],
            "publishCompletedAt": publish_record.get("completedAt"),
            "publishedComponentHash": publish_record.get("componentHash"),
            "environmentId": context["environment"]["id"],
            "agentId": context["agent"]["id"],
            "agentSlug": _agent_slug(context),
        },
    }
    evidence["test"] = attestation
    _write_lifecycle_state(context, state)
    return attestation


def migrate_state(context: dict[str, Any]) -> dict[str, Any]:
    components = _agentbuilder_client(context).fetch_components(
        context["agent"]["id"]
    )
    state = _load_lifecycle_state(context, components)
    _write_lifecycle_state(context, state)
    return {
        "status": "migrated",
        "statePath": str(_lifecycle_state_path(context)),
        "migration": state.get("migration", {}),
    }


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

    credential_parser = subparsers.add_parser(
        "record-credential",
        help="Record a selected healthy ServiceNow credential.",
    )
    credential_parser.add_argument("--connection-id", required=True)

    agent_connection_parser = subparsers.add_parser(
        "record-agent-connection",
        help="Record the maker's manual Connect action after health validation.",
    )
    agent_connection_parser.add_argument("--connection-id", required=True)
    parameter_parser = subparsers.add_parser(
        "record-parameter-sharing",
        help="Record the maker-observed parameter-sharing state.",
    )
    parameter_parser.add_argument(
        "--status",
        required=True,
        choices=("enabled", "not-exposed"),
    )

    topic_state_parser = subparsers.add_parser(
        "set-topic-state",
        help="Set one ServiceNow topic to Active or Inactive.",
    )
    topic_state_parser.add_argument("--topic-id", required=True)
    topic_state_parser.add_argument(
        "--state",
        choices=("active", "inactive"),
        required=True,
    )
    topic_state_parser.add_argument("--yes", action="store_true")

    enable_all_parser = subparsers.add_parser(
        "enable-all-topics",
        help="Enable every ServiceNow HRSD topic after customer confirmation.",
    )
    enable_all_parser.add_argument("--yes", action="store_true")

    rollback_parser = subparsers.add_parser(
        "rollback-topics",
        help="Restore a prepared ServiceNow topic transaction.",
    )
    rollback_parser.add_argument("--operation-id", required=True)
    rollback_parser.add_argument("--yes", action="store_true")

    topic_choice_parser = subparsers.add_parser(
        "record-topic-choice",
        help="Record the customer's decision to keep current topic states.",
    )
    topic_choice_parser.add_argument(
        "--choice",
        choices=("keep-current",),
        required=True,
    )

    publish_parser = subparsers.add_parser(
        "publish",
        help="Publish the active Dev agent.",
    )
    publish_parser.add_argument("--yes", action="store_true")

    test_parser = subparsers.add_parser(
        "record-test",
        help="Record the maker's ServiceNow HRSD Test pane attestation.",
    )
    test_parser.add_argument("--prompt", required=True)
    test_parser.add_argument(
        "--result",
        choices=("pass", "fail"),
        required=True,
    )
    test_parser.add_argument("--details")
    subparsers.add_parser(
        "migrate-state",
        help="Migrate legacy Agent-ID ServiceNow state into lifecycle state.",
    )
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
        elif args.command == "record-credential":
            result = record_credential_selection(
                context,
                args.connection_id,
            )
        elif args.command == "record-agent-connection":
            result = record_agent_connection_attestation(
                context,
                args.connection_id,
            )
        elif args.command == "record-parameter-sharing":
            result = record_parameter_sharing(context, args.status)
        elif args.command == "set-topic-state":
            result = set_topic_state(
                context,
                args.topic_id,
                args.state.title(),
                confirmed=args.yes,
            )
        elif args.command == "enable-all-topics":
            result = enable_all_servicenow_topics(
                context,
                confirmed=args.yes,
            )
        elif args.command == "rollback-topics":
            result = rollback_topic_transaction(
                context,
                args.operation_id,
                confirmed=args.yes,
            )
        elif args.command == "record-topic-choice":
            result = record_keep_current_topic_choice(context)
        elif args.command == "publish":
            result = publish(context, confirmed=args.yes)
        elif args.command == "record-test":
            result = record_test_attestation(
                context,
                prompt=args.prompt,
                result=args.result,
                details=args.details,
            )
        elif args.command == "migrate-state":
            result = migrate_state(context)
        else:  # pragma: no cover
            raise ServiceNowConnectError("Unsupported command.")
    except (ServiceNowConnectError, AgentBuilderError, ValueError) as exc:
        error = {"status": "error", "message": str(exc)}
        if isinstance(exc, ServiceNowConnectError) and exc.details is not None:
            error["details"] = exc.details
        print(json.dumps(error, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
