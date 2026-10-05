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
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from agentbuilder import (
    AgentBuilderClient,
    AgentBuilderError,
    AgentBuilderHTTPError,
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
CONTRACT_PATH = Path(
    "src/skills/connect/servicenow-da-hrsd/contract.json"
)
LIFECYCLE_SCHEMA_VERSION = 6
ADMIN_SETUP_SCHEMA_VERSION = 4
AUTH_MODE = "entraIDUserLogin"
PORTAL_TOPIC_SCHEMA_SUFFIX = ".topic.ServiceNowHRSDSetupConfigurations"
PORTAL_NODE_DISPLAY_NAME = "Set ServiceNow Portal BaseURI"
PORTAL_VARIABLE_NAME = "Global.ServiceNowHRSDPortalBaseURI"
SERVICENOW_CONNECTOR_APP_ID = "c26b24aa-7874-4e06-ad55-7d06b1f79b63"
PORTAL_ORIGINS = {
    "prod": {
        "powerAutomate": "https://make.powerautomate.com",
        "powerApps": "https://make.powerapps.com",
        "copilotStudio": "https://copilotstudio.microsoft.com",
    },
    "preprod": {
        "powerAutomate": "https://make.preprod.powerautomate.com",
        "powerApps": "https://make.preprod.powerapps.com",
        "copilotStudio": "https://copilotstudio.preprod.microsoft.com",
    },
    "test": {
        "powerAutomate": "https://make.test.powerautomate.com",
        "powerApps": "https://make.test.powerapps.com",
        "copilotStudio": "https://copilotstudio.test.microsoft.com",
    },
}
ADMIN_PHASES = {
    "preflight",
    "plugin-prerequisites",
    "entra-registration",
    "servicenow-oidc",
    "credential",
}
_SAFE_USER_FIELD = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


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


def _create_json_atomic_no_clobber(
    path: Path,
    value: dict[str, Any],
) -> None:
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
        try:
            os.link(temporary_path, path)
        except FileExistsError as exc:
            raise ServiceNowConnectError(
                "ServiceNow lifecycle state appeared during initialization; "
                "the existing state was preserved."
            ) from exc
        except OSError as exc:
            raise ServiceNowConnectError(
                "Could not publish the initial ServiceNow lifecycle state "
                "without replacing an existing file."
            ) from exc
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def normalize_client_id(value: str) -> str:
    try:
        return str(uuid.UUID(value.strip()))
    except (AttributeError, ValueError) as exc:
        raise ServiceNowConnectError(
            "Application client ID must be a GUID."
        ) from exc


def normalize_instance_name(value: str) -> str:
    candidate = value.strip()
    if not candidate:
        raise ServiceNowConnectError("ServiceNow instance name is required.")
    if "://" in candidate:
        parsed = urlparse(candidate)
        if (
            parsed.scheme.casefold() != "https"
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
            or parsed.path not in ("", "/")
            or parsed.params
            or parsed.query
            or parsed.fragment
        ):
            raise ServiceNowConnectError(
                "ServiceNow instance URL must be a plain HTTPS origin."
            )
        hostname = parsed.hostname or ""
    else:
        hostname = candidate.rstrip("/")
    suffix = ".service-now.com"
    if hostname.casefold().endswith(suffix):
        hostname = hostname[: -len(suffix)]
    if "." in hostname or not re.fullmatch(r"[A-Za-z0-9-]+", hostname):
        raise ServiceNowConnectError(
            "ServiceNow instance must be an instance name or a "
            "https://<instance>.service-now.com URL."
        )
    return hostname.casefold()


def maker_portal_links(
    context: dict[str, Any],
    *,
    instance_name: str | None = None,
) -> dict[str, dict[str, str]]:
    ring = str(context["environment"].get("ring") or "")
    origins = PORTAL_ORIGINS.get(ring)
    if origins is None:
        raise ServiceNowConnectError(
            f"Unsupported Power Platform ring for maker links: {ring!r}."
        )
    environment_id = str(uuid.UUID(context["environment"]["id"]))
    agent_id = str(uuid.UUID(context["agent"]["id"]))
    links = {
        "entra": {
            "label": "Open Microsoft Entra admin center",
            "url": "https://entra.microsoft.com/",
        },
        "powerAutomateConnections": {
            "label": "Open connections for this environment",
            "url": (
                f"{origins['powerAutomate']}/environments/"
                f"{environment_id}/connections"
            ),
        },
        "powerApps": {
            "label": "Open Power Apps",
            "url": f"{origins['powerApps']}/",
        },
        "copilotStudioAgent": {
            "label": "Open Employee Self-Service (HR) in Copilot Studio",
            "url": (
                f"{origins['copilotStudio']}/environments/{environment_id}/"
                f"copilots/{agent_id}/details?agentBackend=cosmos"
            ),
        },
    }
    if instance_name:
        normalized_instance = normalize_instance_name(instance_name)
        links["serviceNowInstance"] = {
            "label": "Open this ServiceNow instance",
            "url": f"https://{normalized_instance}.service-now.com/",
        }
        links["hrCorePlugin"] = {
            "label": "Open HR Service Delivery Core",
            "url": (
                f"https://{normalized_instance}.service-now.com/now/"
                "app-manager/home/plugin/id/com.sn_hr_core/details"
            ),
        }
    return links


def required_servicenow_prerequisites(
    scope: str,
    auth_mode: str = AUTH_MODE,
) -> list[dict[str, Any]]:
    normalized_scope = scope.strip().casefold()
    if normalized_scope not in {"hrsd", "itsm"}:
        raise ServiceNowConnectError(
            "ServiceNow scope must be hrsd or itsm."
        )
    if auth_mode != AUTH_MODE:
        raise ServiceNowConnectError(
            "Only Microsoft Entra ID User Login is supported."
        )
    requirements: list[dict[str, Any]] = []
    if normalized_scope == "hrsd":
        requirements.append(
            {
                "id": "hr-core",
                "aliases": ["com.sn_hr_core", "sn_hr_core"],
                "requiredFor": ["hrsd"],
            }
        )
    return requirements


def _empty_admin_setup() -> dict[str, Any]:
    return {
        "schemaVersion": ADMIN_SETUP_SCHEMA_VERSION,
        "scope": PROFILE_KEY,
        "authMode": AUTH_MODE,
        "preflight": {
            "discovery": {},
        },
        "phaseHandoffs": {
            phase: {"status": "pending"}
            for phase in sorted(ADMIN_PHASES)
        },
    }


def _legacy_oidc_handoff_proves_capability(
    handoff: object,
) -> bool:
    if not isinstance(handoff, dict):
        return False
    evidence = handoff.get("evidence")
    return bool(
        handoff.get("status") in {"completed", "reused"}
        and isinstance(evidence, dict)
        and evidence.get("kind") == "structured-admin-attestation"
        and isinstance(evidence.get("recordedAt"), str)
        and evidence.get("recordedAt")
        and evidence.get("claim")
        and evidence.get("userField")
    )


def _legacy_oidc_handoff_proves_completion(
    handoff: object,
) -> bool:
    return bool(
        _legacy_oidc_handoff_proves_capability(handoff)
        or (
            isinstance(handoff, dict)
            and handoff.get("status") in {"completed", "reused"}
            and isinstance(handoff.get("evidence"), dict)
            and handoff["evidence"].get("kind")
            == "structured-admin-attestation"
            and isinstance(handoff["evidence"].get("recordedAt"), str)
            and handoff["evidence"].get("recordedAt")
            and handoff["evidence"].get("runbookCompleted") is True
            and handoff["evidence"].get("oidcCapabilityConfirmed") is True
        )
    )


def _admin_setup(state: dict[str, Any]) -> dict[str, Any]:
    setup = state.setdefault("adminSetup", _empty_admin_setup())
    if not isinstance(setup, dict):
        raise ServiceNowConnectError(
            "ServiceNow admin setup state must be an object."
        )
    version = setup.get("schemaVersion", 1)
    if not isinstance(version, int) or isinstance(version, bool):
        raise ServiceNowConnectError(
            "ServiceNow admin setup schemaVersion must be an integer."
        )
    if version > ADMIN_SETUP_SCHEMA_VERSION:
        raise ServiceNowConnectError(
            "ServiceNow admin setup state was written by a newer kit version."
        )
    setup["schemaVersion"] = ADMIN_SETUP_SCHEMA_VERSION
    setup.setdefault("scope", PROFILE_KEY)
    setup.setdefault("authMode", AUTH_MODE)
    preflight = setup.setdefault("preflight", {})
    if not isinstance(preflight, dict):
        raise ServiceNowConnectError(
            "ServiceNow preflight state must be an object."
        )
    preflight.pop("scenario", None)
    preflight.pop("reuseDecision", None)
    discovery = preflight.setdefault("discovery", {})
    if not isinstance(discovery, dict):
        raise ServiceNowConnectError(
            "ServiceNow preflight discovery state must be an object."
        )
    discovery.pop("fingerprint", None)
    handoffs = setup.setdefault("phaseHandoffs", {})
    if not isinstance(handoffs, dict):
        raise ServiceNowConnectError(
            "ServiceNow admin phase handoffs must be an object."
        )
    for phase in sorted(ADMIN_PHASES):
        handoffs.setdefault(phase, {"status": "pending"})
    oidc_handoff = handoffs.get("servicenow-oidc")
    if version < 4 and isinstance(oidc_handoff, dict):
        oidc_evidence = oidc_handoff.get("evidence")
        qualified_completion = _legacy_oidc_handoff_proves_completion(
            oidc_handoff
        )
        if isinstance(oidc_evidence, dict) and qualified_completion:
            oidc_evidence["oidcCapabilityConfirmed"] = True
            oidc_evidence["runbookCompleted"] = True
            oidc_evidence["mappingDetailsCollected"] = False
            oidc_evidence.pop("claim", None)
            oidc_evidence.pop("userField", None)
        elif isinstance(oidc_evidence, dict) and (
            "claim" in oidc_evidence or "userField" in oidc_evidence
        ):
            state.setdefault("migration", {})[
                "retiredOidcMappingEvidence"
            ] = {
                "sourceSha256": _canonical_json_hash(oidc_evidence),
                "qualifiedCompletion": False,
                "retiredAt": _utc_now(),
            }
            handoffs["servicenow-oidc"] = {"status": "pending"}
    preflight_handoff = handoffs.get("preflight")
    if isinstance(preflight_handoff, dict):
        evidence = preflight_handoff.get("evidence")
        if isinstance(evidence, dict):
            evidence.pop("decision", None)
            evidence.pop("discoveryFingerprint", None)
            if evidence.get("kind") == "maker-reuse-decision":
                evidence["kind"] = "read-only-resource-discovery"
    return setup


def _preflight_discovery_complete(setup: dict[str, Any]) -> bool:
    preflight = setup.get("preflight")
    if not isinstance(preflight, dict):
        return False
    discovery = preflight.get("discovery")
    if not isinstance(discovery, dict):
        return False
    return all(
        (
            isinstance(preflight.get("instanceName"), str),
            bool(preflight.get("instanceName")),
            isinstance(discovery.get("observedAt"), str),
            bool(discovery.get("observedAt")),
            isinstance(discovery.get("connectionCandidates"), list),
            isinstance(discovery.get("requiredPlugins"), list),
        )
    )


def _normalize_preflight_handoff(
    state: dict[str, Any],
    setup: dict[str, Any],
) -> bool:
    complete = _preflight_discovery_complete(setup)
    preflight = setup["preflight"]
    handoffs = setup["phaseHandoffs"]
    if complete:
        discovery = preflight["discovery"]
        handoffs["preflight"] = {
            "status": "completed",
            "evidence": {
                "kind": "read-only-resource-discovery",
                "instanceName": preflight.get("instanceName"),
                "observedAt": discovery.get("observedAt"),
            },
        }
        return True

    handoffs["preflight"] = {"status": "pending"}
    phase = state.setdefault("phases", {}).setdefault("preflight", {})
    if not isinstance(phase, dict):
        raise ServiceNowConnectError(
            "ServiceNow preflight phase must be an object."
        )
    phase["status"] = "in-progress"
    phase["checkpointResults"] = {}
    phase["checkpointAcknowledgements"] = {}
    for key in (
        "actionApplied",
        "lastActionAt",
        "lastVerifiedAt",
        "rollbackPushGlob",
    ):
        phase.pop(key, None)
    return False


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


def _portal_topic_component(
    components: dict[str, Any],
) -> dict[str, Any]:
    matches = []
    for change in components.get("botComponentChanges") or []:
        component = change.get("component")
        if (
            isinstance(component, dict)
            and str(component.get("schemaName") or "").endswith(
                PORTAL_TOPIC_SCHEMA_SUFFIX
            )
        ):
            matches.append(component)
    if len(matches) != 1:
        raise ServiceNowConnectError(
            "Expected exactly one ServiceNow HRSD Setup Configurations topic; "
            f"found {len(matches)}."
        )
    topic = matches[0]
    if (
        topic.get("$kind") != "DialogComponent"
        or not topic.get("id")
        or not isinstance(topic.get("version"), int)
    ):
        raise ServiceNowConnectError(
            "The ServiceNow portal configuration topic lacks safe dialog "
            "identity or version evidence."
        )
    return topic


def _portal_value_nodes(value: Any) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if (
            value.get("$kind") == "SetVariable"
            and value.get("displayName") == PORTAL_NODE_DISPLAY_NAME
            and value.get("variable") == PORTAL_VARIABLE_NAME
        ):
            matches.append(value)
        for child in value.values():
            matches.extend(_portal_value_nodes(child))
    elif isinstance(value, list):
        for child in value:
            matches.extend(_portal_value_nodes(child))
    return matches


def _portal_value_node(topic: dict[str, Any]) -> dict[str, Any]:
    matches = _portal_value_nodes(topic.get("dialog"))
    if len(matches) != 1:
        raise ServiceNowConnectError(
            "Expected exactly one Set ServiceNow Portal BaseURI node; "
            f"found {len(matches)}."
        )
    node = matches[0]
    node_value = node.get("value")
    if (
        not isinstance(node_value, dict)
        or set(node_value) != {"$kind", "literalValue"}
        or not isinstance(node_value.get("$kind"), str)
    ):
        raise ServiceNowConnectError(
            "The ServiceNow Portal BaseURI node has an unsupported value shape."
        )
    return node


def normalize_portal_url(
    value: str,
    *,
    expected_instance_name: str,
) -> str:
    stripped = value.strip()
    parsed = urlparse(stripped)
    try:
        parsed_port = parsed.port
    except ValueError as exc:
        raise ServiceNowConnectError(
            "ServiceNow portal URL has an invalid network port."
        ) from exc
    if (
        any(character.isspace() for character in stripped)
        or parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.params
        or parsed_port not in {None, 443}
    ):
        raise ServiceNowConnectError(
            "ServiceNow portal URL must be a plain HTTPS URL without "
            "credentials, query, fragment, or a nonstandard port."
        )
    expected_host = f"{expected_instance_name}.service-now.com"
    if parsed.hostname.casefold() != expected_host.casefold():
        raise ServiceNowConnectError(
            "ServiceNow portal URL must use the confirmed ServiceNow instance."
        )
    path = parsed.path.rstrip("/")
    return f"https://{expected_host}{path}"


def build_portal_url_update_payload(
    components: dict[str, Any],
    portal_url: str,
    *,
    expected_instance_name: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    change_token = components.get("changeToken")
    if not isinstance(change_token, str) or not change_token:
        raise ServiceNowConnectError(
            "MinimalBot component state has no concurrency change token."
        )
    before = copy.deepcopy(_portal_topic_component(components))
    updated = copy.deepcopy(before)
    node = _portal_value_node(updated)
    normalized_url = normalize_portal_url(
        portal_url,
        expected_instance_name=expected_instance_name,
    )
    node["value"]["literalValue"] = normalized_url
    payload = {
        "changeToken": change_token,
        "botComponentChanges": [
            {
                "$kind": "BotComponentUpdate",
                "component": updated,
            }
        ],
    }
    return payload, before, updated


def _portal_literal_value(topic: dict[str, Any]) -> str:
    literal = _portal_value_node(topic)["value"].get("literalValue")
    if not isinstance(literal, str):
        raise ServiceNowConnectError(
            "The ServiceNow Portal BaseURI value is not a string literal."
        )
    return literal


def portal_configuration_summary(
    components: dict[str, Any],
    *,
    expected_instance_name: str | None = None,
) -> dict[str, Any]:
    topic = _portal_topic_component(components)
    literal = _portal_literal_value(topic).strip()
    summary = {
        "topicId": topic.get("id"),
        "topicSchemaName": topic.get("schemaName"),
        "topicDisplayName": topic.get("displayName"),
        "topicState": topic.get("state"),
        "topicStatus": topic.get("status"),
        "variable": PORTAL_VARIABLE_NAME,
        "configured": False,
        "valid": False,
        "origin": None,
        "path": None,
        "reason": "missing",
    }
    if not literal:
        return summary
    parsed = urlparse(literal)
    summary["origin"] = (
        f"{parsed.scheme}://{parsed.hostname}"
        if parsed.scheme and parsed.hostname
        else None
    )
    summary["path"] = parsed.path or "/"
    summary["configured"] = True
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.params
    ):
        summary["reason"] = "invalid-url"
        return summary
    if expected_instance_name and (
        parsed.hostname.casefold()
        != f"{expected_instance_name}.service-now.com".casefold()
    ):
        summary["reason"] = "wrong-instance"
        return summary
    summary["valid"] = True
    summary["reason"] = "valid"
    return summary


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
        "draftSemanticHash": _draft_semantic_hash(components),
        "reference": summary["reference"],
        "phases": {},
        "evidence": {},
        "adminSetup": _empty_admin_setup(),
        "transactions": {"topics": {}},
        "migration": {},
        "updatedAt": _utc_now(),
    }


def initialize_lifecycle_state(
    context: dict[str, Any],
    *,
    contract_revision: int,
) -> dict[str, Any]:
    if (
        not isinstance(contract_revision, int)
        or isinstance(contract_revision, bool)
        or contract_revision < 1
    ):
        raise ServiceNowConnectError(
            "Contract revision must be a positive integer."
        )
    path = _lifecycle_state_path(context)
    if path.exists():
        raise ServiceNowConnectError(
            "ServiceNow lifecycle state already exists; initialize-state "
            "never repairs or replaces existing state."
        )
    contract = _load_json(context["root"] / CONTRACT_PATH)
    if (
        contract.get("provider") != PROVIDER_KEY
        or contract.get("profile") != PROFILE_KEY
        or contract.get("contractRevision") != contract_revision
    ):
        raise ServiceNowConnectError(
            "ServiceNow lifecycle contract identity or revision does not "
            "match the initialization request."
        )
    phases = contract.get("phases")
    if not isinstance(phases, list) or not phases:
        raise ServiceNowConnectError(
            "ServiceNow lifecycle contract has no phases."
        )
    phase_ids: list[str] = []
    for phase in phases:
        phase_id = phase.get("id") if isinstance(phase, dict) else None
        if (
            not isinstance(phase_id, str)
            or not phase_id
            or phase_id in phase_ids
        ):
            raise ServiceNowConnectError(
                "ServiceNow lifecycle contract has invalid phase IDs."
            )
        phase_ids.append(phase_id)

    components = _load_json(context["snapshotPath"])
    state = _state_base(context, components)
    state.update(
        {
            "attested": True,
            "attestedAt": _utc_now(),
            "acceptedContractRevision": contract_revision,
            "roleAttestations": {},
            "phases": {
                phase_id: {
                    "status": "pending",
                    "checkpointResults": {},
                    "checkpointAcknowledgements": {},
                }
                for phase_id in phase_ids
            },
        }
    )
    _create_json_atomic_no_clobber(path, state)
    return {
        "status": "initialized",
        "statePath": str(path),
        "schemaVersion": state["schemaVersion"],
        "provider": state["provider"],
        "profile": state["profile"],
        "agentSlug": state["agentSlug"],
        "agentId": state["agentId"],
        "environmentId": state["environmentId"],
        "acceptedContractRevision": state["acceptedContractRevision"],
        "phaseIds": phase_ids,
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
        "provider": PROVIDER_KEY,
        "profile": PROFILE_KEY,
        "agentSlug": _agent_slug(context),
        "agentId": context["agent"]["id"],
        "environmentId": context["environment"]["id"],
    }
    for key, value in expected.items():
        recorded = state.get(key)
        if (
            not isinstance(recorded, str)
            or not recorded
            or recorded.casefold() != str(value).casefold()
        ):
            raise ServiceNowConnectError(
                f"ServiceNow lifecycle {key} does not match the active agent."
            )


def _validate_legacy_state_identity(
    context: dict[str, Any],
    state: dict[str, Any],
) -> None:
    for key, value in {
        "agentId": context["agent"]["id"],
        "environmentId": context["environment"]["id"],
    }.items():
        recorded = state.get(key)
        if (
            not isinstance(recorded, str)
            or not recorded
            or recorded.casefold() != str(value).casefold()
        ):
            raise ServiceNowConnectError(
                f"Legacy ServiceNow state {key} does not match the active agent."
            )


def _migrate_lifecycle_schema(
    context: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    version = state.get("schemaVersion")
    if not isinstance(version, int) or isinstance(version, bool):
        raise ServiceNowConnectError(
            "ServiceNow lifecycle schemaVersion must be an integer."
        )
    if version > LIFECYCLE_SCHEMA_VERSION:
        raise ServiceNowConnectError(
            "ServiceNow lifecycle state was written by a newer kit version."
        )
    if version < 2:
        raise ServiceNowConnectError(
            "Unsupported canonical ServiceNow lifecycle schema."
        )
    if version == LIFECYCLE_SCHEMA_VERSION:
        _admin_setup(state)
        return state

    source_sha256 = _canonical_json_hash(state)
    phases = state.setdefault("phases", {})
    if not isinstance(phases, dict):
        raise ServiceNowConnectError(
            "ServiceNow lifecycle phases must be an object."
        )
    migration = state.setdefault("migration", {})
    if not isinstance(migration, dict):
        raise ServiceNowConnectError(
            "ServiceNow lifecycle migration state must be an object."
        )

    if version == 2:
        added_phase_ids = [
            "preflight",
            "plugin-prerequisites",
            "entra-registration",
            "servicenow-oidc",
        ]
        for phase_id in added_phase_ids:
            phases.setdefault(
                phase_id,
                {
                    "status": "pending",
                    "checkpointResults": {},
                    "checkpointAcknowledgements": {},
                },
            )

        invalidated_phase_ids: list[str] = []
        credential = phases.setdefault(
            "credential",
            {"status": "pending", "checkpointResults": {}},
        )
        if not isinstance(credential, dict):
            raise ServiceNowConnectError(
                "ServiceNow credential phase must be an object."
            )
        credential["status"] = "in-progress"
        credential["checkpointResults"] = {}
        credential["checkpointAcknowledgements"] = {}
        for key in ("actionApplied", "lastActionAt", "lastVerifiedAt"):
            credential.pop(key, None)
        invalidated_phase_ids.append("credential")

        for phase_id in (
            "topics",
            "agent-connection",
            "parameter-sharing",
            "publish",
            "test",
        ):
            phase = phases.get(phase_id)
            if not isinstance(phase, dict):
                continue
            phase["status"] = "pending"
            phase["checkpointResults"] = {}
            phase["checkpointAcknowledgements"] = {}
            phase.pop("lastVerifiedAt", None)
            invalidated_phase_ids.append(phase_id)

        state["schemaVersion"] = 3
        state.setdefault("acceptedContractRevision", 1)
        migration["schemaV3"] = {
            "from": version,
            "to": 3,
            "sourceSha256": source_sha256,
            "migratedAt": _utc_now(),
            "addedPhaseIds": added_phase_ids,
            "invalidatedPhaseIds": invalidated_phase_ids,
            "reuseApprovalInferred": False,
        }

    raw_admin_setup = state.get("adminSetup")
    raw_oidc_handoff = (
        raw_admin_setup.get("phaseHandoffs", {}).get("servicenow-oidc")
        if isinstance(raw_admin_setup, dict)
        and isinstance(raw_admin_setup.get("phaseHandoffs"), dict)
        else None
    )
    inferred_oidc_capability = _legacy_oidc_handoff_proves_capability(
        raw_oidc_handoff
    )
    setup = _admin_setup(state)
    retained_preflight = _normalize_preflight_handoff(state, setup)
    if version <= 3:
        migration["schemaV4"] = {
            "from": 3,
            "to": 4,
            "sourceSha256": source_sha256,
            "migratedAt": _utc_now(),
            "removedGlobalReuseDecision": True,
            "retainedCompletedPreflight": retained_preflight,
        }
    if version <= 4:
        migration["schemaV5"] = {
            "from": 4,
            "to": 5,
            "sourceSha256": source_sha256,
            "migratedAt": _utc_now(),
            "removedScenarioGate": True,
            "retainedCompletedPreflight": retained_preflight,
            "inferredOidcCapabilityFromCompletedHandoff": (
                inferred_oidc_capability
            ),
        }
    retired_parameter_sharing = None
    if version < 6:
        retired_phases = state.setdefault("retiredPhases", {})
        if not isinstance(retired_phases, dict):
            raise ServiceNowConnectError(
                "ServiceNow retiredPhases state must be an object."
            )
        retired_parameter_sharing = phases.pop("parameter-sharing", None)
        if retired_parameter_sharing is not None:
            retired_phases.setdefault(
                "parameter-sharing",
                retired_parameter_sharing,
            )
    state["schemaVersion"] = LIFECYCLE_SCHEMA_VERSION
    migration["schemaV6"] = {
        "from": 5 if version <= 5 else version,
        "to": LIFECYCLE_SCHEMA_VERSION,
        "sourceSha256": source_sha256,
        "migratedAt": _utc_now(),
        "collapsedOidcMappingEvidence": inferred_oidc_capability,
        "removedOidcMappingCollection": True,
        "retiredParameterSharingPhase": retired_parameter_sharing is not None,
        "testBeforePublish": True,
    }
    return state


def _migrate_legacy_state(
    context: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    legacy_path = _legacy_state_path(context["agent"]["id"])
    if not legacy_path.exists():
        return state
    legacy = _load_json(legacy_path)
    _validate_legacy_state_identity(context, legacy)
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
        version = state.get("schemaVersion")
        if not isinstance(version, int) or isinstance(version, bool):
            raise ServiceNowConnectError(
                "ServiceNow lifecycle schemaVersion must be an integer."
            )
        if version > LIFECYCLE_SCHEMA_VERSION:
            raise ServiceNowConnectError(
                "ServiceNow lifecycle state was written by a newer kit version."
            )
        _validate_state_identity(context, state)
        state = _migrate_lifecycle_schema(context, state)
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
            "adminSetup": _empty_admin_setup(),
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
            "draftSemanticHash",
            "reference",
        ):
            state[key] = current[key]
        credential = state.get("evidence", {}).get("credential")
        if (
            isinstance(credential, dict)
            and credential.get("connectionId")
            and _agent_connection_attestation_current(state, components)
        ):
            state["connectionBindingHash"] = _connection_binding_hash(
                context,
                state,
                components,
            )
        else:
            state.pop("connectionBindingHash", None)
        publish_record = state.get("evidence", {}).get("publish")
        test_record = state.get("evidence", {}).get("test")
        published_hash = (
            publish_record.get("publishedComponentHash")
            or publish_record.get("componentHash")
            if isinstance(publish_record, dict)
            else None
        )
        test_binding = (
            test_record.get("binding")
            if isinstance(test_record, dict)
            else None
        )
        if (
            isinstance(publish_record, dict)
            and publish_record.get("status")
            in {"completed", "confirmation-required"}
            and published_hash == state["componentHash"]
            and isinstance(test_record, dict)
            and test_record.get("status") == "completed"
            and test_record.get("result") == "pass"
            and isinstance(test_binding, dict)
            and test_binding.get("draftSemanticHash")
            == state["draftSemanticHash"]
            and test_binding.get("connectionBindingHash")
            == state.get("connectionBindingHash")
        ):
            publish_record.setdefault(
                "testedDraftSemanticHash",
                state["draftSemanticHash"],
            )
            publish_record.setdefault(
                "publishedSemanticHash",
                state["draftSemanticHash"],
            )
            publish_record.setdefault(
                "connectionBindingHash",
                state["connectionBindingHash"],
            )
    state.setdefault("phases", {})
    state.setdefault("evidence", {})
    _admin_setup(state)
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
    current_draft_hash = state.get("draftSemanticHash")
    publish_done = (
        publish_record.get("status") == "completed"
        and published_hash == current_hash
        and publish_record.get("testedDraftSemanticHash")
        == current_draft_hash
        and publish_record.get("publishedSemanticHash")
        == current_draft_hash
    )

    test_record = evidence.get("test")
    if not isinstance(test_record, dict):
        test_record = {}
    test_result = test_record.get("result")
    test_binding = test_record.get("binding")
    test_current = bool(
        isinstance(test_binding, dict)
        and test_binding.get("draftSemanticHash") == current_draft_hash
        and test_binding.get("connectionBindingHash")
        == state.get("connectionBindingHash")
    )

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
        "test": {
            "status": (
                "confirmation-required"
                if test_current and test_result in {"pass", "fail"}
                else "pending"
            ),
            "message": (
                "A passing Test pane result was previously recorded; a "
                "current functional result requires maker confirmation."
                if test_current and test_result == "pass"
                else (
                    "A failing Test pane result was previously recorded; a "
                    "current functional result requires maker confirmation."
                )
                if test_current and test_result == "fail"
                else (
                    "Functional Test pane validation has not been recorded "
                    "for the current saved draft and selected connection."
                )
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
    }


def record_preflight_instance(
    context: dict[str, Any],
    *,
    instance_url: str,
) -> dict[str, Any]:
    instance_name = normalize_instance_name(instance_url)
    state = _load_lifecycle_state(context)
    preflight = _admin_setup(state)["preflight"]
    preflight.update(
        {
            "instanceName": instance_name,
            "instanceOrigin": (
                f"https://{instance_name}.service-now.com"
            ),
            "recordedAt": _utc_now(),
        }
    )
    _admin_setup(state)["phaseHandoffs"]["preflight"] = {
        "status": "pending"
    }
    _write_lifecycle_state(context, state)
    return copy.deepcopy(preflight)


def _discovered_instance_name(
    connections: list[dict[str, Any]],
) -> str | None:
    names: set[str] = set()
    for connection in connections:
        values = connection.get("parameterValues")
        values = values if isinstance(values, dict) else {}
        raw_name = values.get("token:InstanceName") or values.get("instance")
        if not isinstance(raw_name, str) or not raw_name.strip():
            continue
        try:
            names.add(normalize_instance_name(raw_name))
        except ServiceNowConnectError:
            continue
    return next(iter(names)) if len(names) == 1 else None


def _credential_selection_key(connection_id: str) -> str:
    normalized = uuid.UUID(connection_id).hex
    return f"connection-{hashlib.sha256(normalized.encode()).hexdigest()[:12]}"


def _connection_matches_expected_credential(
    connection: dict[str, Any],
    *,
    expected_instance: str | None,
    expected_client_id: str | None,
) -> bool:
    if connection.get("authMode") != AUTH_MODE:
        return False
    values = connection.get("parameterValues")
    values = values if isinstance(values, dict) else {}
    instance_name = values.get("token:InstanceName") or values.get("instance")
    resource_uri = values.get("token:ResourceUri")
    if not expected_instance or not expected_client_id:
        return False
    try:
        return (
            normalize_instance_name(str(instance_name)) == expected_instance
            and normalize_client_id(str(resource_uri)) == expected_client_id
        )
    except ServiceNowConnectError:
        return False


def _credential_resolution(
    setup: dict[str, Any],
    connections: list[dict[str, Any]],
) -> dict[str, Any]:
    preflight = setup.get("preflight")
    preflight = preflight if isinstance(preflight, dict) else {}
    expected_instance = preflight.get("instanceName")
    app_record = setup.get("phaseHandoffs", {}).get("entra-registration")
    app_evidence = (
        app_record.get("evidence")
        if isinstance(app_record, dict)
        else {}
    )
    app_evidence = app_evidence if isinstance(app_evidence, dict) else {}
    expected_client_id = app_evidence.get("clientId")
    exact = [
        connection
        for connection in connections
        if _connection_matches_expected_credential(
            connection,
            expected_instance=expected_instance,
            expected_client_id=expected_client_id,
        )
    ]
    healthy = [
        connection
        for connection in exact
        if connection.get("status") == "Connected"
    ]
    unhealthy = [
        connection
        for connection in exact
        if connection.get("status") != "Connected"
    ]
    healthy = sorted(
        healthy,
        key=lambda connection: (
            str(connection.get("displayName") or ""),
            str(connection.get("connectionId") or ""),
        ),
    )
    return {
        "expected": {
            "authMode": AUTH_MODE,
            "instanceName": expected_instance,
            "resourceUri": expected_client_id,
        },
        "healthyExactCount": len(healthy),
        "unhealthyExactCount": len(unhealthy),
        "healthyExactCandidates": [
            {
                "selectionKey": _credential_selection_key(
                    str(connection["connectionId"])
                ),
                "label": (
                    f"{connection.get('displayName') or 'ServiceNow connection'} "
                    f"(Connected, option {index})"
                ),
            }
            for index, connection in enumerate(healthy, start=1)
            if connection.get("connectionId")
        ],
    }


def inspect_admin_setup(context: dict[str, Any]) -> dict[str, Any]:
    state = _load_lifecycle_state(context)
    setup = _admin_setup(state)
    connections = [
        connection_summary(record)
        for record in _connectivity_client(context).list_connections()
    ]
    user_login_connections = sorted(
        [
        connection
        for connection in connections
        if connection.get("authMode") == AUTH_MODE
        ],
        key=lambda connection: (
            str(connection.get("connectionId") or ""),
            str(connection.get("displayName") or ""),
        ),
    )
    preflight = setup["preflight"]
    instance_name = preflight.get("instanceName")
    if not isinstance(instance_name, str) or not instance_name:
        instance_name = _discovered_instance_name(user_login_connections)
        if instance_name:
            preflight.update(
                {
                    "instanceName": instance_name,
                    "instanceOrigin": (
                        f"https://{instance_name}.service-now.com"
                    ),
                    "instanceSource": "connector-discovery",
                }
            )
    handoffs = setup["phaseHandoffs"]
    app_record = handoffs.get("entra-registration")
    client_id = None
    if isinstance(app_record, dict):
        client_id = (app_record.get("evidence") or {}).get("clientId")
    discovery = {
        "source": "connectivity-readonly",
        "observedAt": _utc_now(),
        "scope": setup["scope"],
        "authMode": setup["authMode"],
        "instanceName": instance_name,
        "instanceInputRequired": not bool(instance_name),
        "requiredPlugins": required_servicenow_prerequisites(
            setup["scope"],
            setup["authMode"],
        ),
        "connectionCandidates": user_login_connections,
        "credentialResolution": _credential_resolution(
            setup,
            connections,
        ),
        "entraClientId": client_id,
        "links": maker_portal_links(
            context,
            instance_name=instance_name,
        ),
        "limitations": [
            "ServiceNow plugin and OIDC security objects require admin "
            "confirmation when no supported read-only API is available.",
            "Entra application details are verified by the phase's Microsoft "
            "Graph checkpoints after a client ID is supplied.",
        ],
    }
    setup["preflight"]["discovery"] = discovery
    _normalize_preflight_handoff(state, setup)
    _write_lifecycle_state(context, state)
    return discovery


def resolve_credential_completion(
    context: dict[str, Any],
    *,
    selection_key: str | None = None,
) -> dict[str, Any]:
    state = _load_lifecycle_state(context)
    setup = _admin_setup(state)
    connections = [
        connection_summary(record)
        for record in _connectivity_client(context).list_connections()
    ]
    resolution = _credential_resolution(setup, connections)
    healthy = [
        connection
        for connection in connections
        if _connection_matches_expected_credential(
            connection,
            expected_instance=resolution["expected"]["instanceName"],
            expected_client_id=resolution["expected"]["resourceUri"],
        )
        and connection.get("status") == "Connected"
        and connection.get("connectionId")
    ]
    healthy = sorted(
        healthy,
        key=lambda connection: (
            str(connection.get("displayName") or ""),
            str(connection.get("connectionId") or ""),
        ),
    )
    if selection_key is not None:
        selected = next(
            (
                connection
                for connection in healthy
                if _credential_selection_key(
                    str(connection["connectionId"])
                )
                == selection_key
            ),
            None,
        )
        if selected is None:
            raise ServiceNowConnectError(
                "The selected ServiceNow connection is no longer an exact "
                "healthy candidate. Refresh and select again."
            )
        evidence = record_credential_selection(
            context,
            str(selected["connectionId"]),
        )
        return {
            "status": "selected",
            "selection": {
                "label": selected.get("displayName"),
            },
            "evidence": evidence,
        }
    if len(healthy) == 1:
        evidence = record_credential_selection(
            context,
            str(healthy[0]["connectionId"]),
        )
        return {
            "status": "selected",
            "selection": {
                "label": healthy[0].get("displayName"),
            },
            "evidence": evidence,
        }
    if len(healthy) > 1:
        return {
            "status": "choice-required",
            "candidates": resolution["healthyExactCandidates"],
            "message": (
                "Multiple exact healthy ServiceNow connections are available. "
                "Select one candidate by label."
            ),
        }
    return {
        "status": "not-ready",
        "expected": resolution["expected"],
        "unhealthyExactCount": resolution["unhealthyExactCount"],
        "remediation": (
            "No exact healthy Connected Microsoft Entra ID User Login "
            "ServiceNow connection is currently visible. Finish creation or "
            "repair in the same environment, then choose Completed so the "
            "read-only inventory can verify it again."
        ),
    }


def record_admin_phase(
    context: dict[str, Any],
    *,
    phase: str,
    status: str,
    client_id: str | None = None,
) -> dict[str, Any]:
    if phase not in ADMIN_PHASES:
        raise ServiceNowConnectError("Unsupported ServiceNow admin phase.")
    if status not in {"completed", "reused"}:
        raise ServiceNowConnectError(
            "Admin operation status must be completed or reused."
        )
    state = _load_lifecycle_state(context)
    setup = _admin_setup(state)

    evidence: dict[str, Any] = {
        "kind": "structured-admin-attestation",
        "ownerBoundary": "admin-owned-guided-workflow",
        "recordedAt": _utc_now(),
    }
    if phase == "entra-registration":
        if not client_id:
            raise ServiceNowConnectError(
                "The non-secret Application client ID is required."
            )
        evidence["clientId"] = normalize_client_id(client_id)
    elif client_id is not None:
        raise ServiceNowConnectError(
            "Application client ID is accepted only for entra-registration."
        )

    if phase == "servicenow-oidc":
        evidence.update(
            {
                "oidcCapabilityConfirmed": True,
                "runbookCompleted": True,
                "mappingDetailsCollected": False,
            }
        )

    record = {
        "status": status,
        "evidence": evidence,
        "verifiedBy": (
            "read-only-checkpoint-pending"
            if phase == "entra-registration"
            else "structured-attestation"
        ),
    }
    setup["phaseHandoffs"][phase] = record
    _write_lifecycle_state(context, state)
    return copy.deepcopy(record)


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
        "links": maker_portal_links(
            context,
            instance_name=(
                _admin_setup(
                    _load_lifecycle_state(context, components)
                )["preflight"].get("instanceName")
            ),
        ),
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


def inspect_portal_configuration(
    context: dict[str, Any],
    *,
    offline: bool = False,
    expected_portal_url: str | None = None,
) -> dict[str, Any]:
    components = (
        _load_json(context["snapshotPath"])
        if offline
        else _agentbuilder_client(context).fetch_components(
            context["agent"]["id"]
        )
    )
    state = _load_lifecycle_state(context, components)
    expected_instance = _admin_setup(state)["preflight"].get("instanceName")
    summary = portal_configuration_summary(
        components,
        expected_instance_name=(
            expected_instance
            if isinstance(expected_instance, str)
            else None
        ),
    )
    verification_url = expected_portal_url
    explicit_root_confirmed = True
    if (
        summary["valid"]
        and summary["path"] == "/"
        and verification_url is None
    ):
        verification_url = _latest_requested_portal_url(state)
        explicit_root_confirmed = verification_url is not None
    expected_match: bool | None = None
    if verification_url is not None:
        if not isinstance(expected_instance, str) or not expected_instance:
            raise ServiceNowConnectError(
                "The lifecycle has no confirmed ServiceNow instance."
            )
        expected = normalize_portal_url(
            verification_url,
            expected_instance_name=expected_instance,
        )
        current = (
            normalize_portal_url(
                _portal_literal_value(_portal_topic_component(components)),
                expected_instance_name=expected_instance,
            )
            if summary["valid"]
            else None
        )
        expected_match = current == expected
    configured = (
        summary["valid"]
        and expected_match is not False
        and explicit_root_confirmed
    )
    return {
        "status": "configured" if configured else "input-required",
        "mode": "offline" if offline else "live",
        "agentId": context["agent"]["id"],
        "environmentId": context["environment"]["id"],
        "portal": summary,
        "expectedPortalUrlMatch": expected_match,
        "input": (
            None
            if configured
            else {
                "field": "portalUrl",
                "description": (
                    "Explicit administrator confirmation of this exact root "
                    "ServiceNow URL for the employee portal."
                    if not explicit_root_confirmed
                    else (
                    "The exact administrator-confirmed full ServiceNow "
                    "employee portal URL supplied for this phase."
                    if expected_match is False
                    else (
                        "Administrator-confirmed full ServiceNow employee "
                        "portal URL. Use a root URL only when the administrator "
                        "explicitly confirms that exact value."
                    )
                    )
                ),
            }
        ),
    }


def _latest_requested_portal_url(state: dict[str, Any]) -> str | None:
    transactions = state.get("transactions")
    transactions = transactions if isinstance(transactions, dict) else {}
    portal_transactions = transactions.get("portal")
    portal_transactions = (
        portal_transactions if isinstance(portal_transactions, dict) else {}
    )
    candidates = [
        transaction
        for transaction in portal_transactions.values()
        if isinstance(transaction, dict)
        and transaction.get("status")
        in {"committed", "failed-unchanged", "reconciliation-required"}
        and isinstance(transaction.get("requestedPortalUrl"), str)
        and transaction["requestedPortalUrl"]
    ]
    if not candidates:
        return None
    latest = max(
        candidates,
        key=lambda transaction: str(transaction.get("preparedAt") or ""),
    )
    return str(latest["requestedPortalUrl"])


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
    state = _state_for_components(context, components)
    setup = _admin_setup(state)
    app_record = setup["phaseHandoffs"].get("entra-registration")
    app_evidence = (
        app_record.get("evidence")
        if isinstance(app_record, dict)
        else {}
    )
    if not isinstance(app_evidence, dict):
        app_evidence = {}
    instance_name = (
        instance_name
        or setup["preflight"].get("instanceName")
        or reference.get("instanceName")
    )
    resource_uri = (
        resource_uri
        or app_evidence.get("clientId")
        or reference.get("resourceUri")
    )
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
    instance_name = normalize_instance_name(str(instance_name))
    if str(resource_uri).casefold().startswith("api://"):
        raise ServiceNowConnectError(
            "Resource URI must be the Application client ID, not api:// URI."
        )
    resource_uri = normalize_client_id(str(resource_uri))
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
    state = _load_lifecycle_state(context)
    setup = _admin_setup(state)
    expected_instance = setup["preflight"].get("instanceName")
    app_record = setup["phaseHandoffs"].get("entra-registration")
    app_evidence = (
        app_record.get("evidence")
        if isinstance(app_record, dict)
        else {}
    )
    if not isinstance(app_evidence, dict):
        app_evidence = {}
    expected_client_id = app_evidence.get("clientId")
    values = physical.get("parameterValues")
    if not isinstance(values, dict):
        values = {}
    actual_instance = values.get("token:InstanceName") or values.get("instance")
    actual_resource = values.get("token:ResourceUri")
    if expected_instance:
        if not actual_instance:
            raise ServiceNowConnectError(
                "The physical ServiceNow connection did not expose its "
                "Instance Name for exact verification."
            )
        if normalize_instance_name(str(actual_instance)) != expected_instance:
            raise ServiceNowConnectError(
                "The physical ServiceNow connection targets a different "
                "Instance Name."
            )
    if expected_client_id:
        if not actual_resource:
            raise ServiceNowConnectError(
                "The physical ServiceNow connection did not expose its "
                "Resource URI for exact verification."
            )
        if normalize_client_id(str(actual_resource)) != expected_client_id:
            raise ServiceNowConnectError(
                "The physical ServiceNow connection Resource URI does not "
                "match the verified Application client ID."
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
    state = _load_lifecycle_state(context, components)
    setup = _admin_setup(state)
    values = physical.get("parameterValues")
    values = values if isinstance(values, dict) else {}
    instance_name = values.get("token:InstanceName") or values.get("instance")
    resource_uri = values.get("token:ResourceUri")
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
        "instanceName": (
            normalize_instance_name(str(instance_name))
            if instance_name
            else setup["preflight"].get("instanceName")
        ),
        "resourceUri": (
            normalize_client_id(str(resource_uri))
            if resource_uri
            else (
                (
                    setup["phaseHandoffs"]
                    .get("entra-registration", {})
                    .get("evidence", {})
                    .get("clientId")
                )
            )
        ),
        "parameterMetadata": copy.deepcopy(
            physical.get("parameterValues") or {}
        ),
    }
    state.setdefault("evidence", {})["credential"] = evidence
    setup["phaseHandoffs"]["credential"] = {
        "status": "completed",
        "evidence": {
            "kind": "maker-connection-return",
            "connectionId": normalized_connection_id,
            "displayName": physical.get("displayName"),
            "recordedAt": _utc_now(),
        },
    }
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
        "status": "completed",
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
            "draftSemanticHash": _draft_semantic_hash(components),
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


def _draft_semantic_hash(components: dict[str, Any]) -> str:
    topics: list[dict[str, Any]] = []
    changes = components.get("botComponentChanges")
    if not isinstance(changes, list):
        raise ServiceNowConnectError(
            "MinimalBot component state has an invalid topic collection."
        )
    for change in changes:
        if not isinstance(change, dict):
            raise ServiceNowConnectError(
                "MinimalBot topic collection contains an invalid change."
            )
        component = change.get("component")
        if not isinstance(component, dict):
            continue
        if "ServiceNowHRSD" not in str(component.get("schemaName") or ""):
            continue
        normalized = copy.deepcopy(component)
        normalized.pop("version", None)
        normalized.pop("auditInfo", None)
        topics.append(normalized)
    topics.sort(
        key=lambda component: (
            str(component.get("id") or ""),
            str(component.get("schemaName") or ""),
        )
    )
    reference = copy.deepcopy(find_servicenow_reference(components))
    reference.pop("version", None)
    reference.pop("auditInfo", None)
    reference["sharedConnectionParameters"] = _shared_parameters(reference)
    projection = {
        "serviceNowTopics": topics,
        "serviceNowReference": reference,
    }
    return _canonical_json_hash(projection)


def _agent_connection_attestation_current(
    state: dict[str, Any],
    components: dict[str, Any],
) -> bool:
    credential = state.get("evidence", {}).get("credential")
    attestation = state.get("evidence", {}).get("agentConnection")
    attestation_binding = (
        attestation.get("binding")
        if isinstance(attestation, dict)
        else None
    )
    if not isinstance(credential, dict) or not credential.get("connectionId"):
        return False
    normalized_connection_id = str(credential["connectionId"]).replace("-", "")
    return not (
        not isinstance(attestation, dict)
        or attestation.get("kind") != "maker-attestation"
        or attestation.get("status") != "completed"
        or attestation.get("makerAttested") is not True
        or attestation.get("physicalStatus") != "Connected"
        or str(attestation.get("connectionId") or "").replace("-", "")
        != normalized_connection_id
        or not isinstance(attestation_binding, dict)
        or attestation_binding.get("draftSemanticHash")
        != _draft_semantic_hash(components)
    )


def _connection_binding_hash(
    context: dict[str, Any],
    state: dict[str, Any],
    components: dict[str, Any],
    *,
    require_agent_attestation: bool = True,
) -> str:
    credential = state.get("evidence", {}).get("credential")
    if not isinstance(credential, dict) or not credential.get("connectionId"):
        raise ServiceNowConnectError(
            "Select and verify a ServiceNow credential before recording Test "
            "evidence."
        )
    attestation = state.get("evidence", {}).get("agentConnection")
    attestation_current = _agent_connection_attestation_current(
        state,
        components,
    )
    if require_agent_attestation and not attestation_current:
        raise ServiceNowConnectError(
            "Record a current Agent Connect observation for this saved draft "
            "and selected credential before recording Test evidence."
        )
    summary = summarize_components(components)
    reference = summary["reference"]
    return _canonical_json_hash(
        {
            "provider": PROVIDER_KEY,
            "profile": PROFILE_KEY,
            "agentSlug": _agent_slug(context),
            "agentId": context["agent"]["id"],
            "environmentId": context["environment"]["id"],
            "connectionId": credential["connectionId"],
            "agentConnectionRecordedAt": (
                attestation.get("recordedAt")
                if isinstance(attestation, dict)
                else None
            ),
            "reference": {
                "id": reference.get("id"),
                "logicalName": reference.get("logicalName"),
                "authMode": reference.get("authMode"),
                "instanceName": reference.get("instanceName"),
                "resourceUri": reference.get("resourceUri"),
            },
            "serviceNowInvokeConnectorActionCount": summary[
                "serviceNowInvokeConnectorActionCount"
            ],
            "serviceNowInvokeFlowActionCount": summary[
                "serviceNowInvokeFlowActionCount"
            ],
        }
    )


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


def _rollback_portal_transaction(
    context: dict[str, Any],
    agentbuilder: AgentBuilderClient,
    state: dict[str, Any],
    operation_id: str,
) -> dict[str, Any]:
    transactions = state.setdefault("transactions", {}).setdefault(
        "portal", {}
    )
    transaction = transactions.get(operation_id)
    if not isinstance(transaction, dict):
        raise ServiceNowConnectError(
            f"Unknown portal transaction: {operation_id}"
        )
    try:
        current = agentbuilder.fetch_components(context["agent"]["id"])
    except Exception as exc:
        transaction.update(
            {
                "status": "rollback-incomplete",
                "rolledBackAt": _utc_now(),
                "rollbackError": type(exc).__name__,
                "remediation": (
                    "The skill could not read the portal topic before "
                    "rollback. Stop and verify the current authored value "
                    "manually before retrying."
                ),
            }
        )
        _write_lifecycle_state(context, state)
        return transaction
    current_topic = _portal_topic_component(current)
    expected_post_hash = transaction.get(
        "expectedPostContentHashExcludingVersion"
    )
    if (
        not expected_post_hash
        or _component_content_hash(current_topic) != expected_post_hash
    ):
        transaction.update(
            {
                "status": "rollback-incomplete",
                "rolledBackAt": _utc_now(),
                "remediation": (
                    "The portal configuration topic changed after the guarded "
                    "update. Preserve the current authored content and restore "
                    "the prior value manually after reviewing the conflict."
                ),
            }
        )
        _write_lifecycle_state(context, state)
        return transaction
    preimage = transaction.get("component")
    if not isinstance(preimage, dict):
        raise ServiceNowConnectError(
            "Portal transaction has no rollback preimage."
        )
    token = current.get("changeToken")
    if not isinstance(token, str) or not token:
        raise ServiceNowConnectError(
            "Cannot roll back the portal URL without a fresh change token."
        )
    restored = copy.deepcopy(preimage)
    restored["version"] = current_topic.get("version")
    rollback_error: Exception | None = None
    try:
        agentbuilder.update_components(
            context["agent"]["id"],
            {
                "changeToken": token,
                "botComponentChanges": [
                    {
                        "$kind": "BotComponentUpdate",
                        "component": restored,
                    }
                ],
            },
        )
    except Exception as exc:
        rollback_error = exc
    try:
        verified = agentbuilder.fetch_components(context["agent"]["id"])
    except Exception as exc:
        transaction.update(
            {
                "status": "rollback-incomplete",
                "rolledBackAt": _utc_now(),
                "rollbackVerified": False,
                "rollbackError": type(exc).__name__,
                "remediation": (
                    "The rollback write could not be verified. Stop and "
                    "inspect the current portal value manually before "
                    "retrying."
                ),
            }
        )
        _write_lifecycle_state(context, state)
        return transaction
    verified_topic = _portal_topic_component(verified)
    restored_ok = (
        _component_content_hash(verified_topic)
        == _component_content_hash(preimage)
    )
    transaction.update(
        {
            "status": "rolled-back" if restored_ok else "rollback-incomplete",
            "rolledBackAt": _utc_now(),
            "rollbackVerified": restored_ok,
        }
    )
    if not restored_ok:
        transaction["rollbackError"] = (
            type(rollback_error).__name__
            if rollback_error is not None
            else "ReadbackMismatch"
        )
        transaction["remediation"] = (
            "Rollback did not restore the original portal configuration. "
            "Stop and restore the prior value manually from the recorded "
            "preimage before retrying."
        )
    _write_lifecycle_state(context, state)
    return transaction


def set_portal_url(
    context: dict[str, Any],
    portal_url: str,
    *,
    confirmed: bool,
    rollback_after_verify: bool = False,
) -> dict[str, Any]:
    if not confirmed:
        raise ServiceNowConnectError(
            "Portal URL update requires explicit confirmation (--yes)."
        )
    state = _load_lifecycle_state(context)
    setup = _admin_setup(state)
    expected_instance = setup["preflight"].get("instanceName")
    if not isinstance(expected_instance, str) or not expected_instance:
        raise ServiceNowConnectError(
            "The lifecycle has no confirmed ServiceNow instance."
        )
    agentbuilder = _agentbuilder_client(context)
    before = agentbuilder.fetch_components(context["agent"]["id"])
    payload, preimage, expected_postimage = build_portal_url_update_payload(
        before,
        portal_url,
        expected_instance_name=expected_instance,
    )
    normalized_url = _portal_literal_value(expected_postimage)
    if _portal_literal_value(preimage) == normalized_url:
        return {
            "status": "already-configured",
            "portal": portal_configuration_summary(
                before,
                expected_instance_name=expected_instance,
            ),
            "readbackVerified": True,
        }
    operation_id = str(uuid.uuid4())
    transaction = {
        "operationId": operation_id,
        "status": "prepared",
        "preparedAt": _utc_now(),
        "topicId": preimage.get("id"),
        "topicSchemaName": preimage.get("schemaName"),
        "beforeContentHashExcludingVersion": _component_content_hash(preimage),
        "expectedPostContentHashExcludingVersion": _component_content_hash(
            expected_postimage
        ),
        "beforePortalUrl": _portal_literal_value(preimage),
        "requestedPortalUrl": normalized_url,
        "component": preimage,
    }
    state.setdefault("transactions", {}).setdefault("portal", {})[
        operation_id
    ] = transaction
    _write_lifecycle_state(context, state)
    update_error: Exception | None = None
    try:
        agentbuilder.update_components(context["agent"]["id"], payload)
    except Exception as exc:
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
                "reconciliationError": type(exc).__name__,
                "remediation": (
                    "The portal URL update may have occurred, but readback "
                    "failed. Do not retry or roll back until a fresh component "
                    "read establishes the current authored content."
                ),
            }
        )
        _write_lifecycle_state(context, state)
        raise ServiceNowConnectError(
            transaction["remediation"],
            details={
                "operationId": operation_id,
                "transaction": copy.deepcopy(transaction),
            },
        ) from exc
    postimage = _portal_topic_component(after)
    post_hash = _component_content_hash(postimage)
    transaction.update(
        {
            "postContentHashExcludingVersion": post_hash,
            "readbackAt": _utc_now(),
        }
    )
    if post_hash == transaction["expectedPostContentHashExcludingVersion"]:
        transaction.update(
            {
                "status": "committed",
                "committedAt": _utc_now(),
                "readbackVerified": (
                    _portal_literal_value(postimage) == normalized_url
                ),
            }
        )
        _write_lifecycle_state(context, state)
        if rollback_after_verify:
            rolled_back = _rollback_portal_transaction(
                context,
                agentbuilder,
                state,
                operation_id,
            )
            if rolled_back.get("status") != "rolled-back":
                raise ServiceNowConnectError(
                    str(rolled_back.get("remediation")),
                    details={
                        "operationId": operation_id,
                        "transaction": copy.deepcopy(rolled_back),
                    },
                )
            return {
                "status": "verified-and-rolled-back",
                "operationId": operation_id,
                "topicId": preimage.get("id"),
                "portalUrl": normalized_url,
                "rollbackVerified": True,
            }
        return {
            "status": "committed",
            "operationId": operation_id,
            "topicId": preimage.get("id"),
            "portalUrl": normalized_url,
            "readbackVerified": True,
        }
    if post_hash == transaction["beforeContentHashExcludingVersion"]:
        transaction.update(
            {
                "status": "failed-unchanged",
                "mutationMayHaveOccurred": False,
                "readbackVerified": True,
                "rollbackVerified": True,
                "remediation": (
                    "The component API did not apply the Portal BaseURI "
                    "change. Use the manual Copilot Studio topic step."
                ),
            }
        )
    else:
        transaction.update(
            {
                "status": "conflict",
                "remediation": (
                    "The portal configuration topic changed unexpectedly. "
                    "Do not overwrite it; review the current topic manually."
                ),
            }
        )
    _write_lifecycle_state(context, state)
    raise ServiceNowConnectError(
        transaction["remediation"],
        details={
            "operationId": operation_id,
            "transaction": copy.deepcopy(transaction),
        },
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
        "kind": "maker-attestation",
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


def _publish_validation_pending(response: dict[str, Any]) -> bool | None:
    upper = response.get("ValidationPending")
    lower = response.get("validationPending")
    if (
        upper is not None
        and lower is not None
        and upper is not lower
        and upper != lower
    ):
        raise ServiceNowConnectError(
            "Publish response returned conflicting ValidationPending values."
        )
    value = lower if lower is not None else upper
    if value is not None and not isinstance(value, bool):
        raise ServiceNowConnectError(
            "Publish response returned an invalid ValidationPending value."
        )
    return value


def _publish_remote_snapshot(
    context: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    agentbuilder = _agentbuilder_client(context)
    agent = agentbuilder.get_agent(context["agent"]["id"])
    components = agentbuilder.fetch_components(context["agent"]["id"])
    last_published_at = agent.get("lastPublishedAt")
    return {
        "agentId": context["agent"]["id"],
        "environmentId": context["environment"]["id"],
        "componentHash": _component_hash(components),
        "draftSemanticHash": _draft_semantic_hash(components),
        "connectionBindingHash": _connection_binding_hash(
            context,
            state,
            components,
        ),
        "serverLastPublishedAt": (
            last_published_at
            if isinstance(last_published_at, str) and last_published_at
            else None
        ),
    }


def inspect_publish_state(
    context: dict[str, Any],
) -> dict[str, Any]:
    state = _load_lifecycle_state(context)
    receipt = state.get("evidence", {}).get("publish")
    receipt = receipt if isinstance(receipt, dict) else {}
    snapshot = _publish_remote_snapshot(context, state)
    return {
        "status": "read-only",
        **snapshot,
        "receipt": {
            "status": receipt.get("status"),
            "requestedAt": receipt.get("requestedAt"),
            "completedAt": receipt.get("completedAt"),
            "componentHash": receipt.get("componentHash"),
            "requestedComponentHash": receipt.get(
                "requestedComponentHash"
            ),
            "publishedComponentHash": receipt.get(
                "publishedComponentHash"
            ),
        },
        "reconciliationEligible": bool(
            snapshot["serverLastPublishedAt"]
            and receipt.get("requestedAt")
            and receipt.get("status")
            in {"confirmation-required", "needs_remediation"}
            and receipt.get("publishedComponentHash") is None
        ),
    }


def _parse_utc_timestamp(value: str, label: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ServiceNowConnectError(
            f"{label} must be an ISO 8601 timestamp."
        ) from exc
    if parsed.tzinfo is None:
        raise ServiceNowConnectError(f"{label} must include a timezone.")
    return parsed.astimezone(dt.UTC)


def reconcile_publish_receipt(
    context: dict[str, Any],
    *,
    expected_component_hash: str,
    expected_last_published_at: str,
    confirmed: bool,
) -> dict[str, Any]:
    if not confirmed:
        raise ServiceNowConnectError(
            "Publish receipt reconciliation requires explicit confirmation."
        )
    if not re.fullmatch(r"[0-9a-f]{64}", expected_component_hash):
        raise ServiceNowConnectError(
            "Expected component hash must be a lowercase SHA-256 value."
        )
    state = _load_lifecycle_state(context)
    evidence = state.setdefault("evidence", {})
    receipt = evidence.get("publish")
    if not isinstance(receipt, dict):
        raise ServiceNowConnectError(
            "No legacy publish receipt is available to reconcile."
        )
    if receipt.get("publishedComponentHash") is not None:
        raise ServiceNowConnectError(
            "The publish receipt already has a post-publish component hash."
        )
    requested_at = receipt.get("requestedAt")
    if not isinstance(requested_at, str) or not requested_at:
        raise ServiceNowConnectError(
            "The legacy publish receipt has no request timestamp."
        )
    expected_published = _parse_utc_timestamp(
        expected_last_published_at,
        "Expected server lastPublishedAt",
    )
    requested = _parse_utc_timestamp(
        requested_at,
        "Legacy publish requestedAt",
    )
    if abs((expected_published - requested).total_seconds()) > 300:
        raise ServiceNowConnectError(
            "The server publish timestamp does not match the legacy request."
        )

    snapshot = _publish_remote_snapshot(context, state)
    if snapshot["componentHash"] != expected_component_hash:
        raise ServiceNowConnectError(
            "The current component revision changed after maker confirmation."
        )
    if snapshot["serverLastPublishedAt"] != expected_last_published_at:
        raise ServiceNowConnectError(
            "The server publish timestamp changed after maker confirmation."
        )
    test_record = evidence.get("test")
    if (
        not isinstance(test_record, dict)
        or test_record.get("status") != "completed"
        or test_record.get("result") != "pass"
        or not isinstance(test_record.get("binding"), dict)
        or test_record["binding"].get("draftSemanticHash")
        != snapshot["draftSemanticHash"]
        or test_record["binding"].get("connectionBindingHash")
        != snapshot["connectionBindingHash"]
    ):
        raise ServiceNowConnectError(
            "The current draft and selected connection do not have a matching "
            "privacy-safe Test result for publish receipt reconciliation."
        )

    legacy_receipt = {
        key: copy.deepcopy(receipt.get(key))
        for key in (
            "requestedAt",
            "completedAt",
            "status",
            "componentHash",
            "requestedComponentHash",
            "response",
        )
        if key in receipt
    }
    reconciled_at = _utc_now()
    reconciled = {
        **receipt,
        "kind": "maker-attestation",
        "status": "confirmation-required",
        "completedAt": (
            receipt.get("completedAt") or expected_last_published_at
        ),
        "requestedComponentHash": (
            receipt.get("requestedComponentHash")
            or receipt.get("componentHash")
        ),
        "publishedComponentHash": expected_component_hash,
        "componentHash": expected_component_hash,
        "testedDraftSemanticHash": snapshot["draftSemanticHash"],
        "publishedSemanticHash": snapshot["draftSemanticHash"],
        "connectionBindingHash": snapshot["connectionBindingHash"],
        "serverLastPublishedAt": expected_last_published_at,
        "verifiedBy": "maker-attested-current-revision",
        "recordedAt": reconciled_at,
        "attestedAt": reconciled_at,
        "reconciledAt": reconciled_at,
        "legacyReceipt": legacy_receipt,
    }
    evidence["publish"] = reconciled
    state["componentHash"] = expected_component_hash
    state["draftSemanticHash"] = snapshot["draftSemanticHash"]
    state["connectionBindingHash"] = snapshot["connectionBindingHash"]
    _write_lifecycle_state(context, state)
    return reconciled


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
    requested_component_hash = _component_hash(components)
    tested_draft_semantic_hash = _draft_semantic_hash(components)
    state = _load_lifecycle_state(context, components)
    current_connection_binding_hash = _connection_binding_hash(
        context,
        state,
        components,
    )
    test_record = state.get("evidence", {}).get("test")
    credential = state.get("evidence", {}).get("credential")
    if (
        not isinstance(test_record, dict)
        or test_record.get("status") != "completed"
        or test_record.get("result") != "pass"
        or not isinstance(test_record.get("binding"), dict)
        or test_record["binding"].get("draftSemanticHash")
        != tested_draft_semantic_hash
        or test_record["binding"].get("connectionBindingHash")
        != current_connection_binding_hash
        or not isinstance(credential, dict)
        or test_record["binding"].get("connectionId")
        != credential.get("connectionId")
    ):
        raise ServiceNowConnectError(
            "The current draft content and selected connection have not "
            "passed the privacy-safe HRSD Test pane check. Test this exact "
            "draft before publishing."
        )
    requested_at = _utc_now()
    try:
        response = agentbuilder.publish_agent(context["agent"]["id"])
    except Exception as exc:
        publish_error = {
            "requestedAt": requested_at,
            "status": "needs_remediation",
            "mutationMayHaveOccurred": True,
            "componentHash": requested_component_hash,
            "errorCode": type(exc).__name__,
            "recordedAt": _utc_now(),
        }
        detail = str(exc)
        if isinstance(exc, AgentBuilderHTTPError):
            publish_error.update(
                {
                    "httpStatus": exc.status_code,
                    "serviceErrorCode": exc.error_code,
                    "requestId": exc.request_id,
                }
            )
        state.setdefault("evidence", {})["publish"] = publish_error
        _write_lifecycle_state(context, state)
        raise ServiceNowConnectError(
            f"Publish outcome is ambiguous: {detail}. Review Copilot Studio "
            "publish details before retrying; automatic unpublish is not "
            "available."
        ) from exc
    validation_pending = _publish_validation_pending(response)
    try:
        published_components = agentbuilder.fetch_components(
            context["agent"]["id"]
        )
    except Exception as exc:
        publish_error = {
            "requestedAt": requested_at,
            "acceptedAt": _utc_now(),
            "status": "needs_remediation",
            "mutationMayHaveOccurred": True,
            "requestedComponentHash": requested_component_hash,
            "componentHash": requested_component_hash,
            "errorCode": type(exc).__name__,
            "response": {
                "validationPending": validation_pending,
                "responseKeys": sorted(response.keys()),
            },
            "remediation": (
                "Publish was accepted, but the post-publish component "
                "revision could not be read. Do not republish blindly; "
                "reconcile the current remote publish state first."
            ),
            "recordedAt": _utc_now(),
        }
        if isinstance(exc, AgentBuilderHTTPError):
            publish_error.update(
                {
                    "httpStatus": exc.status_code,
                    "serviceErrorCode": exc.error_code,
                    "requestId": exc.request_id,
                }
            )
        state.setdefault("evidence", {})["publish"] = publish_error
        _write_lifecycle_state(context, state)
        raise ServiceNowConnectError(publish_error["remediation"]) from exc
    published_component_hash = _component_hash(published_components)
    published_semantic_hash = _draft_semantic_hash(published_components)
    if published_semantic_hash != tested_draft_semantic_hash:
        publish_error = {
            "kind": "maker-attestation",
            "requestedAt": requested_at,
            "acceptedAt": _utc_now(),
            "status": "needs_remediation",
            "mutationMayHaveOccurred": True,
            "requestedComponentHash": requested_component_hash,
            "publishedComponentHash": published_component_hash,
            "testedDraftSemanticHash": tested_draft_semantic_hash,
            "publishedSemanticHash": published_semantic_hash,
            "connectionBindingHash": current_connection_binding_hash,
            "response": {
                "validationPending": validation_pending,
                "responseKeys": sorted(response.keys()),
            },
            "remediation": (
                "Publish changed authored semantic content relative to the "
                "tested draft. Do not republish blindly; inspect the current "
                "draft and run Test again."
            ),
            "recordedAt": _utc_now(),
        }
        state.setdefault("evidence", {})["publish"] = publish_error
        state["componentHash"] = published_component_hash
        _write_lifecycle_state(context, state)
        raise ServiceNowConnectError(publish_error["remediation"])
    completed_at = _utc_now()
    publish_record = {
        "kind": "maker-attestation",
        "requestedAt": requested_at,
        "completedAt": completed_at,
        "recordedAt": completed_at,
        "agentId": context["agent"]["id"],
        "environmentId": context["environment"]["id"],
        "requestedComponentHash": requested_component_hash,
        "publishedComponentHash": published_component_hash,
        "componentHash": published_component_hash,
        "testedDraftSemanticHash": tested_draft_semantic_hash,
        "publishedSemanticHash": published_semantic_hash,
        "connectionBindingHash": current_connection_binding_hash,
        "response": {
            "validationPending": validation_pending,
            "responseKeys": sorted(response.keys()),
        },
        "status": (
            "completed"
            if validation_pending is False
            else "confirmation-required"
        ),
        "mutationMayHaveOccurred": True,
    }
    state.setdefault("evidence", {})["publish"] = publish_record
    state["componentHash"] = published_component_hash
    state["draftSemanticHash"] = published_semantic_hash
    state["connectionBindingHash"] = current_connection_binding_hash
    _write_lifecycle_state(context, state)
    return state


def record_test_attestation(
    context: dict[str, Any],
    *,
    prompt_category: str,
    result: str,
    failure_category: str | None,
) -> dict[str, Any]:
    allowed_prompts = {"list-my-open-hr-cases"}
    allowed_failures = {
        "authentication",
        "permission",
        "empty-result",
        "connector",
        "unexpected",
    }
    if prompt_category not in allowed_prompts:
        raise ServiceNowConnectError(
            "Unsupported privacy-safe Test pane prompt category."
        )
    if result not in {"pass", "fail"}:
        raise ServiceNowConnectError(
            "Test pane result must be pass or fail."
        )
    if result == "pass" and failure_category is not None:
        raise ServiceNowConnectError(
            "A passing Test pane result cannot have a failure category."
        )
    if result == "fail" and failure_category not in allowed_failures:
        raise ServiceNowConnectError(
            "A failing Test pane result requires a bounded failure category."
        )
    components = _agentbuilder_client(context).fetch_components(
        context["agent"]["id"]
    )
    state = _load_lifecycle_state(context, components)
    evidence = state.setdefault("evidence", {})
    credential = evidence.get("credential")
    if not isinstance(credential, dict) or not credential.get("connectionId"):
        raise ServiceNowConnectError(
            "Select and verify a ServiceNow credential before recording a test."
        )
    draft_semantic_hash = _draft_semantic_hash(components)
    connection_binding_hash = _connection_binding_hash(
        context,
        state,
        components,
    )
    attestation = {
        "kind": "maker-attestation",
        "status": "completed" if result == "pass" else "failed",
        "promptCategory": prompt_category,
        "result": result,
        "failureCategory": failure_category,
        "recordedAt": _utc_now(),
        "binding": {
            "connectionId": credential["connectionId"],
            "provider": PROVIDER_KEY,
            "profile": PROFILE_KEY,
            "environmentId": context["environment"]["id"],
            "agentId": context["agent"]["id"],
            "agentSlug": _agent_slug(context),
            "draftSemanticHash": draft_semantic_hash,
            "connectionBindingHash": connection_binding_hash,
        },
    }
    evidence["test"] = attestation
    state["draftSemanticHash"] = draft_semantic_hash
    state["connectionBindingHash"] = connection_binding_hash
    _write_lifecycle_state(context, state)
    return attestation


def migrate_state(context: dict[str, Any]) -> dict[str, Any]:
    state = _load_lifecycle_state(context)
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
    inspect_portal_parser = subparsers.add_parser(
        "inspect-portal-url",
        help="Inspect the exact HRSD Portal BaseURI topic value.",
    )
    inspect_portal_parser.add_argument("--offline", action="store_true")
    inspect_portal_parser.add_argument("--expected-portal-url")
    subparsers.add_parser(
        "inspect-admin-setup",
        help="Discover reusable ServiceNow admin setup with read-only APIs.",
    )
    preflight_parser = subparsers.add_parser(
        "record-preflight",
        help="Record the public ServiceNow instance URL when discovery cannot derive it.",
    )
    preflight_parser.add_argument("--instance-url", required=True)
    phase_parser = subparsers.add_parser(
        "record-admin-phase",
        help="Record one complete non-secret delegated admin phase.",
    )
    phase_parser.add_argument(
        "--phase",
        required=True,
        choices=tuple(sorted(ADMIN_PHASES)),
    )
    phase_parser.add_argument(
        "--status",
        required=True,
        choices=("completed", "reused"),
    )
    phase_parser.add_argument("--client-id")

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
    resolve_credential_parser = subparsers.add_parser(
        "resolve-credential",
        help=(
            "Freshly verify exact healthy ServiceNow credentials and "
            "automatically select one when unambiguous."
        ),
    )
    resolve_credential_parser.add_argument("--selection-key")

    agent_connection_parser = subparsers.add_parser(
        "record-agent-connection",
        help="Record the maker's manual Connect action after health validation.",
    )
    agent_connection_parser.add_argument("--connection-id", required=True)
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
    portal_parser = subparsers.add_parser(
        "set-portal-url",
        help=(
            "Set the exact HRSD Setup Configurations Portal BaseURI topic "
            "value with guarded readback and rollback."
        ),
    )
    portal_parser.add_argument("--portal-url", required=True)
    portal_parser.add_argument("--yes", action="store_true")
    portal_parser.add_argument(
        "--rollback-after-verify",
        action="store_true",
        help="Restore the original value after a successful guarded readback.",
    )

    publish_parser = subparsers.add_parser(
        "publish",
        help="Publish the active Dev agent.",
    )
    publish_parser.add_argument("--yes", action="store_true")
    subparsers.add_parser(
        "inspect-publish",
        help="Read the current remote publish marker and component revision.",
    )
    reconcile_publish_parser = subparsers.add_parser(
        "reconcile-publish-receipt",
        help="Record maker-confirmed current publish evidence without publishing.",
    )
    reconcile_publish_parser.add_argument(
        "--expected-component-hash",
        required=True,
    )
    reconcile_publish_parser.add_argument(
        "--expected-last-published-at",
        required=True,
    )
    reconcile_publish_parser.add_argument("--yes", action="store_true")

    test_parser = subparsers.add_parser(
        "record-test",
        help="Record the maker's ServiceNow HRSD Test pane attestation.",
    )
    test_parser.add_argument(
        "--prompt-category",
        choices=("list-my-open-hr-cases",),
        required=True,
    )
    test_parser.add_argument(
        "--result",
        choices=("pass", "fail"),
        required=True,
    )
    test_parser.add_argument(
        "--failure-category",
        choices=(
            "authentication",
            "permission",
            "empty-result",
            "connector",
            "unexpected",
        ),
    )
    subparsers.add_parser(
        "migrate-state",
        help="Migrate legacy Agent-ID ServiceNow state into lifecycle state.",
    )
    initialize_parser = subparsers.add_parser(
        "initialize-state",
        help="Create the first provider-owned lifecycle state after plan approval.",
    )
    initialize_parser.add_argument(
        "--contract-revision",
        type=int,
        required=True,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        context = load_context()
        if args.command == "inspect":
            result = inspect(context, offline=args.offline)
        elif args.command == "inspect-portal-url":
            result = inspect_portal_configuration(
                context,
                offline=args.offline,
                expected_portal_url=args.expected_portal_url,
            )
        elif args.command == "inspect-admin-setup":
            result = inspect_admin_setup(context)
        elif args.command == "record-preflight":
            result = record_preflight_instance(
                context,
                instance_url=args.instance_url,
            )
        elif args.command == "record-admin-phase":
            result = record_admin_phase(
                context,
                phase=args.phase,
                status=args.status,
                client_id=args.client_id,
            )
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
        elif args.command == "resolve-credential":
            result = resolve_credential_completion(
                context,
                selection_key=args.selection_key,
            )
        elif args.command == "record-agent-connection":
            result = record_agent_connection_attestation(
                context,
                args.connection_id,
            )
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
        elif args.command == "set-portal-url":
            result = set_portal_url(
                context,
                args.portal_url,
                confirmed=args.yes,
                rollback_after_verify=args.rollback_after_verify,
            )
        elif args.command == "publish":
            result = publish(context, confirmed=args.yes)
        elif args.command == "inspect-publish":
            result = inspect_publish_state(context)
        elif args.command == "reconcile-publish-receipt":
            result = reconcile_publish_receipt(
                context,
                expected_component_hash=args.expected_component_hash,
                expected_last_published_at=args.expected_last_published_at,
                confirmed=args.yes,
            )
        elif args.command == "record-test":
            result = record_test_attestation(
                context,
                prompt_category=args.prompt_category,
                result=args.result,
                failure_category=args.failure_category,
            )
        elif args.command == "migrate-state":
            result = migrate_state(context)
        elif args.command == "initialize-state":
            result = initialize_lifecycle_state(
                context,
                contract_revision=args.contract_revision,
            )
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
