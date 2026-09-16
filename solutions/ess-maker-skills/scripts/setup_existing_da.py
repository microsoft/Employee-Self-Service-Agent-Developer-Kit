# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Attach an existing editable DA Dev agent without using Dataverse."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from agentbuilder import (
    DEFAULT_API_VERSION,
    REALM_NAMES,
    AgentBuilderClient,
    AgentBuilderError,
    AgentBuilderHTTPError,
    authenticate,
    authenticate_selected_tenant,
    canonical_json,
    derive_environment_host,
    validate_environment_host,
)
from agentbuilder_object_model import (
    ObjectModelConverterError,
    object_models_to_yaml,
    validate_object_model_runtime,
)


ATTACH_METADATA = ".agentbuilder/attach.json"
RAW_CHANGESET = ".agentbuilder/components.json"
CANONICAL_SETUP_STATE = Path(".local/setup/config.json")
CANONICAL_SETUP_SCHEMA_VERSION = 1
PROJECTION_ENGINE = "microsoft-agents-objectmodel"
WORKSPACE_PROJECTION_VERSION = 2
STUDIO_RING_BY_HOST = {
    "copilotstudio.microsoft.com": "prod",
    "copilotstudio.preprod.microsoft.com": "preprod",
    "copilotstudio.test.microsoft.com": "test",
}
GUID_TOKEN = (
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}"
)


class ExistingDASetupError(RuntimeError):
    """Raised when existing-Dev setup cannot preserve its invariants."""


def _require_object_model_dependencies() -> None:
    """Fail before remote setup when the local projection runtime is absent."""
    try:
        validate_object_model_runtime()
    except ObjectModelConverterError as exc:
        raise ExistingDASetupError(
            f"Microsoft Object Model dependencies are unavailable: {exc}"
        ) from exc


def inspect_agent_route(
    client: AgentBuilderClient,
    *,
    environment_id: str,
    agent_id: str,
) -> dict[str, Any]:
    """Return the service-owned route realm for one exact agent."""
    normalized_environment_id = _normalize_environment_id(environment_id)
    normalized_agent_id = _normalize_guid(agent_id, "Agent ID")
    realms = client.get_realms(normalized_agent_id)
    route_realm = realms.get("routeRealm")
    realm_name = next(
        (
            name.casefold()
            for value, name in REALM_NAMES.items()
            if route_realm == value
            or (
                isinstance(route_realm, str)
                and route_realm.casefold() == name.casefold()
            )
        ),
        None,
    )
    if realm_name is None:
        raise ExistingDASetupError(
            "Agent realm discovery did not return a recognized route realm."
        )
    return {
        "environmentId": normalized_environment_id,
        "tenantId": client.tenant_id,
        "host": client.host,
        "ring": client.ring,
        "apiVersion": client.api_version,
        "agentId": normalized_agent_id,
        "realm": realm_name,
    }


def _normalize_guid(value: str, label: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise ExistingDASetupError(f"{label} must be a GUID.") from exc


def _normalize_environment_id(value: str) -> str:
    candidate = value.strip()
    if candidate.casefold().startswith("default-"):
        candidate = candidate[len("Default-") :]
    return _normalize_guid(candidate, "Environment ID")


def parse_da_target_url(target_url: str) -> dict[str, str]:
    """Extract recognized ring and resource tokens from supplied text."""
    target = unquote(target_url.strip())
    normalized_target = target.casefold()
    environment_match = re.search(
        rf"environments/(?:default-)?(?P<id>{GUID_TOKEN})"
        r"(?![0-9a-f-])",
        normalized_target,
    )

    result = {
        "source": "provided-target",
    }
    if environment_match is not None:
        result["environmentId"] = _normalize_environment_id(
            environment_match.group("id")
        )
    for marker, ring in STUDIO_RING_BY_HOST.items():
        if marker in normalized_target:
            result["source"] = "copilot-studio-url"
            result["ring"] = ring
            break
    if (
        result["source"] == "provided-target"
        and "make.powerapps.com" in normalized_target
    ):
        result["source"] = "power-apps-url"

    agent_match = re.search(
        rf"(?:bots|copilots)/(?P<id>{GUID_TOKEN})(?![0-9a-f-])",
        normalized_target,
    )
    if agent_match is not None:
        result["agentId"] = _normalize_guid(
            agent_match.group("id"),
            "Agent ID",
        )
    return result


def resolve_da_target(
    *,
    target_url: str | None,
    environment_id: str | None,
    agent_id: str | None = None,
    ring: str | None = None,
    require_agent: bool = False,
) -> dict[str, str]:
    """Resolve explicit and target-derived identifiers without ambiguity."""
    target = parse_da_target_url(target_url) if target_url else {}
    explicit_environment = (
        _normalize_environment_id(environment_id)
        if environment_id
        else None
    )
    derived_environment = target.get("environmentId")
    if (
        explicit_environment
        and derived_environment
        and explicit_environment.casefold() != derived_environment.casefold()
    ):
        raise ExistingDASetupError(
            "Supplied target and --environment-id identify different "
            "environments."
        )
    resolved_environment = explicit_environment or derived_environment
    if not resolved_environment:
        raise ExistingDASetupError(
            "The supplied target does not identify an environment; "
            "provide --environment-id."
        )

    explicit_agent = (
        _normalize_guid(agent_id, "Agent ID")
        if agent_id
        else None
    )
    derived_agent = target.get("agentId")
    if (
        explicit_agent
        and derived_agent
        and explicit_agent.casefold() != derived_agent.casefold()
    ):
        raise ExistingDASetupError(
            "Supplied target and --agent-id identify different agents."
        )
    resolved = {
        **target,
        "environmentId": resolved_environment,
    }
    derived_ring = target.get("ring")
    if ring and derived_ring and ring != derived_ring:
        raise ExistingDASetupError(
            "Supplied target and --ring identify different service rings."
        )
    resolved["ring"] = ring or derived_ring or "prod"
    if resolved_agent := (explicit_agent or derived_agent):
        resolved["agentId"] = resolved_agent
        if derived_agent:
            resolved["agentSelection"] = target["source"]
        else:
            resolved["agentSelection"] = "direct-id-fallback"
    elif require_agent:
        raise ExistingDASetupError(
            "The supplied target does not identify an agent; "
            "provide --agent-id."
        )
    return resolved


def _slugify(value: str) -> str:
    slug = value.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    if not slug:
        raise ExistingDASetupError(
            "Agent display name does not produce a usable workspace name."
        )
    return slug


def _schema_suffix(schema_name: str) -> str:
    suffix = schema_name.rsplit(".", 1)[-1]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", suffix):
        raise ExistingDASetupError(
            f"Component schema name has an unsafe suffix: {schema_name!r}"
        )
    return suffix


def _write_json(path: Path, value: Any) -> None:
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
            json.dump(value, stream, indent=2, ensure_ascii=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExistingDASetupError(f"Local JSON is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise ExistingDASetupError(f"Local JSON must contain an object: {path}")
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_canonical_setup_state(
    kit_root: Path,
) -> dict[str, Any] | None:
    path = kit_root / CANONICAL_SETUP_STATE
    if not path.exists():
        return None
    state = _load_json(path)
    required_fields = {
        "schema_version",
        "status",
        "setup_source",
        "environment",
        "agent",
        "workspace",
        "completed_at",
    }
    if set(state) != required_fields:
        raise ExistingDASetupError(
            "This workspace has setup state from an unsupported release. "
            "Open a new workspace for DA setup."
        )
    if (
        state.get("schema_version") != CANONICAL_SETUP_SCHEMA_VERSION
        or state.get("status") != "complete"
        or state.get("setup_source") != "existing-dev"
    ):
        raise ExistingDASetupError(
            "This workspace has setup state from an unsupported release. "
            "Open a new workspace for DA setup."
        )
    environment = state.get("environment")
    agent = state.get("agent")
    workspace = state.get("workspace")
    if (
        not isinstance(environment, dict)
        or not isinstance(agent, dict)
        or not isinstance(workspace, dict)
        or workspace.get("status") != "qualified-complete"
    ):
        raise ExistingDASetupError(
            "Canonical DA setup state is incomplete or malformed."
        )
    return state


def _canonical_state_matches_connection(
    state: dict[str, Any],
    connection: dict[str, Any],
) -> bool:
    environment = state["environment"]
    agent = state["agent"]
    return (
        environment.get("id") == connection["environment"]["id"]
        and environment.get("tenant_id")
        == connection["environment"]["tenantId"]
        and environment.get("power_platform_api_endpoint")
        == connection["environment"]["powerPlatformApiEndpoint"]
        and environment.get("ring") == connection["environment"]["ring"]
        and environment.get("api_version")
        == connection["environment"]["apiVersion"]
        and agent.get("id") == connection["agent"]["id"]
        and agent.get("schema_name") == connection["agent"]["schemaName"]
        and agent.get("realm") == connection["agent"]["realm"]
        and agent.get("alm_family_id")
        == connection["agent"]["almFamilyId"]
    )


def _record_canonical_setup_complete(
    kit_root: Path,
    connection: dict[str, Any],
    workspace: dict[str, Any],
) -> dict[str, Any]:
    """Record the completed agent and the ALM source used to establish it."""
    existing = _load_canonical_setup_state(kit_root)
    if existing is not None and not _canonical_state_matches_connection(
        existing,
        connection,
    ):
        raise ExistingDASetupError(
            "Canonical setup state identifies a different environment or "
            "agent. Open a new workspace before changing the setup target."
        )
    state = {
        "schema_version": CANONICAL_SETUP_SCHEMA_VERSION,
        "status": "complete",
        "setup_source": "existing-dev",
        "environment": {
            "id": connection["environment"]["id"],
            "tenant_id": connection["environment"]["tenantId"],
            "power_platform_api_endpoint": connection["environment"][
                "powerPlatformApiEndpoint"
            ],
            "ring": connection["environment"]["ring"],
            "api_version": connection["environment"]["apiVersion"],
        },
        "agent": {
            "id": connection["agent"]["id"],
            "name": connection["agent"]["name"],
            "schema_name": connection["agent"]["schemaName"],
            "realm": connection["agent"]["realm"],
            "alm_family_id": connection["agent"]["almFamilyId"],
            "workspace_slug": connection["agent"]["workspaceSlug"],
        },
        "workspace": {
            "status": workspace["status"],
            "folder": workspace["folder"],
            "agent_path": workspace["agentPath"],
            "topic_count": workspace["topicCount"],
            "variable_count": workspace["variableCount"],
            "projected_component_kinds": workspace[
                "projectedComponentKinds"
            ],
            "unprojected_component_kinds": workspace[
                "unprojectedComponentKinds"
            ],
            "unprojected_dialog_count": workspace[
                "unprojectedDialogCount"
            ],
        },
        "completed_at": (
            existing["completed_at"] if existing is not None else _utc_now()
        ),
    }
    _write_json(kit_root / CANONICAL_SETUP_STATE, state)
    return state


def inspect_dev_agents(client: AgentBuilderClient) -> dict[str, Any]:
    """Classify listed agents using authoritative direct realm metadata."""
    listed_agents = client.list_agents()
    dev_agents: list[dict[str, Any]] = []
    excluded_non_dev = 0
    unverified = 0
    for listed_agent in listed_agents:
        agent_id = str(
            listed_agent.get("botId")
            or listed_agent.get("cdsBotId")
            or listed_agent.get("componentIdUnique")
            or ""
        )
        try:
            normalized_agent_id = _normalize_guid(agent_id, "Agent ID")
        except ExistingDASetupError:
            unverified += 1
            continue
        try:
            metadata = client.get_agent(normalized_agent_id)
        except AgentBuilderHTTPError as exc:
            if exc.status_code not in (403, 404):
                raise
            unverified += 1
            continue
        realm = metadata.get("realm")
        is_dev = realm == 0 or (
            isinstance(realm, str) and realm.casefold() == "dev"
        )
        if is_dev:
            dev_agents.append({**listed_agent, **metadata})
        else:
            excluded_non_dev += 1
    return {
        "listedAgents": listed_agents,
        "devAgents": dev_agents,
        "excludedNonDevCount": excluded_non_dev,
        "unverifiedAgentCount": unverified,
    }


def _confirm_dev(
    agent_id: str,
    agent: dict[str, Any],
    configuration: dict[str, Any],
) -> tuple[str, str]:
    realm = configuration.get("realm")
    if realm not in (0, "dev", "Dev"):
        raise ExistingDASetupError(
            f"Explicit Dev configuration returned realm {realm!r}."
        )
    configured_id = _normalize_guid(
        str(configuration.get("cdsBotId") or ""),
        "Configured Dev agent ID",
    )
    if configured_id.casefold() != agent_id.casefold():
        raise ExistingDASetupError(
            "Explicit Dev configuration returned a different agent identity."
        )
    card_realm = agent.get("realm")
    if card_realm not in (None, 0, "dev", "Dev"):
        raise ExistingDASetupError(
            f"Direct agent lookup identified a non-Dev realm: {card_realm!r}."
        )
    schema_name = str(
        configuration.get("schemaName")
        or agent.get("schemaName")
        or ""
    )
    family_id = str(configuration.get("grsRepositoryId") or "")
    if not schema_name:
        raise ExistingDASetupError(
            "Dev configuration did not return a schema name."
        )
    if not family_id:
        raise ExistingDASetupError(
            "Dev configuration did not return an ALM-family identity."
        )
    return schema_name, family_id


def validate_existing_dev_connection(
    client: AgentBuilderClient,
    *,
    environment_id: str,
    agent_id: str,
    selection_source: str | None = None,
) -> dict[str, Any]:
    """Validate a directly addressable agent as editable Dev identity."""
    normalized_environment_id = _normalize_environment_id(environment_id)
    normalized_agent_id = _normalize_guid(agent_id, "Agent ID")
    agent = client.get_agent(normalized_agent_id)
    configuration = client.get_dev_configuration(normalized_agent_id)
    schema_name, family_id = _confirm_dev(
        normalized_agent_id,
        agent,
        configuration,
    )
    agent_name = str(
        agent.get("fullBotName")
        or agent.get("displayName")
        or agent.get("shortBotName")
        or schema_name
    )
    managed_properties = agent.get("managedProperties")
    is_managed = (
        bool(managed_properties.get("isManaged"))
        if isinstance(managed_properties, dict)
        else False
    )
    return {
        "schemaVersion": 1,
        "stateKind": "da-existing-dev-connection",
        "status": "connected",
        "releaseLine": "da",
        "setupSource": "existing-dev",
        "transport": "agentbuilder",
        "environment": {
            "id": normalized_environment_id,
            "tenantId": client.tenant_id,
            "powerPlatformApiEndpoint": client.host,
            "ring": client.ring,
            "apiVersion": client.api_version,
        },
        "agent": {
            "id": normalized_agent_id,
            "name": agent_name,
            "schemaName": schema_name,
            "realm": "dev",
            "almFamilyId": family_id,
            "isManaged": is_managed,
            "workspaceSlug": _slugify(agent_name),
        },
        "selectedBy": selection_source or "direct-id",
        "verifiedAt": _utc_now(),
    }


def _validate_setup_target(
    kit_root: Path,
    connection: dict[str, Any],
) -> dict[str, Any] | None:
    """Reject setup over a different platform, environment, or agent."""
    canonical_state = _load_canonical_setup_state(kit_root)
    if (
        canonical_state is not None
        and not _canonical_state_matches_connection(
            canonical_state,
            connection,
        )
    ):
        raise ExistingDASetupError(
            "This workspace already has setup state for another environment "
            "or agent. Use a new workspace for DA setup."
        )
    workspace_config = kit_root / ".local" / "config.json"
    if workspace_config.exists():
        existing_workspace = _load_json(workspace_config)
        if existing_workspace.get("transport") != "agentbuilder":
            raise ExistingDASetupError(
                "This workspace already has a non-DA local configuration. "
                "Use a new workspace for DA setup."
            )
    return canonical_state


def _changeset_sha256(changeset: dict[str, Any]) -> str:
    """Fingerprint fetched content without transport or ordering noise."""
    content = _normalize_changeset_wire(
        {
            key: value
            for key, value in changeset.items()
            if key != "changeToken"
        }
    )
    for key, value in tuple(content.items()):
        if key.endswith("Changes") and isinstance(value, list):
            content[key] = sorted(value, key=canonical_json)
    return hashlib.sha256(
        canonical_json(content).encode("utf-8")
    ).hexdigest()


def _normalize_changeset_wire(value: Any, *, field: str | None = None) -> Any:
    if field == "activity":
        literal = _expanded_literal_activity(value)
        if literal is not None:
            return literal
    if isinstance(value, dict):
        return {
            key: _normalize_changeset_wire(child, field=key)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_normalize_changeset_wire(child) for child in value]
    return value


def _expanded_literal_activity(value: Any) -> str | None:
    if not isinstance(value, dict) or set(value) != {"$kind", "text"}:
        return None
    if value.get("$kind") != "Message":
        return None
    text = value.get("text")
    if not isinstance(text, list) or len(text) != 1:
        return None
    line = text[0]
    if (
        not isinstance(line, dict)
        or set(line) != {"$kind", "segments"}
        or line.get("$kind") != "TemplateLine"
    ):
        return None
    segments = line.get("segments")
    if not isinstance(segments, list) or len(segments) != 1:
        return None
    segment = segments[0]
    if (
        not isinstance(segment, dict)
        or set(segment) != {"$kind", "value"}
        or segment.get("$kind") != "TextSegment"
        or not isinstance(segment.get("value"), str)
    ):
        return None
    return segment["value"]


def _component_changes(changeset: dict[str, Any]) -> list[dict[str, Any]]:
    changes = changeset.get("botComponentChanges")
    if not isinstance(changes, list):
        raise ExistingDASetupError(
            "Component fetch did not return botComponentChanges."
        )
    return [change for change in changes if isinstance(change, dict)]


def _validate_changeset_identity(
    changeset: dict[str, Any],
    agent_id: str,
) -> None:
    bot = changeset.get("bot")
    if not isinstance(bot, dict):
        raise ExistingDASetupError("Component fetch did not return bot identity.")
    fetched_id = _normalize_guid(
        str(bot.get("cdsBotId") or bot.get("componentIdUnique") or ""),
        "Fetched component agent ID",
    )
    if fetched_id.casefold() != agent_id.casefold():
        raise ExistingDASetupError(
            "Component fetch returned content for a different agent."
        )


def _materialize_workspace(
    changeset: dict[str, Any],
    destination: Path,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    Counter[str],
    list[dict[str, str]],
]:
    topic_entries: list[dict[str, Any]] = []
    projected_entries: list[dict[str, Any]] = []
    component_counts: Counter[str] = Counter()
    dialog_components: list[dict[str, Any]] = []
    variable_components: list[dict[str, Any]] = []
    gpt_components: list[dict[str, Any]] = []
    for change in _component_changes(changeset):
        component = change.get("component")
        if not isinstance(component, dict):
            continue
        component_kind = str(component.get("$kind") or "Unknown")
        component_counts[component_kind] += 1
        if component_kind == "DialogComponent":
            schema_name = str(component.get("schemaName") or "")
            dialog = component.get("dialog")
            if not schema_name or not isinstance(dialog, dict):
                raise ExistingDASetupError(
                    "Dialog component is missing its schema or dialog body."
                )
            dialog_components.append(component)
        elif component_kind == "GlobalVariableComponent":
            schema_name = str(component.get("schemaName") or "")
            variable = component.get("variable")
            if not schema_name or not isinstance(variable, dict):
                raise ExistingDASetupError(
                    "Global variable component is missing its schema or "
                    "variable body."
                )
            variable_components.append(component)
        elif component_kind == "GptComponent":
            metadata = component.get("metadata")
            if not isinstance(metadata, dict):
                raise ExistingDASetupError(
                    "GPT component is missing its agent metadata."
                )
            gpt_components.append(component)

    if len(gpt_components) != 1:
        raise ExistingDASetupError(
            "Component fetch must return exactly one GPT component for the "
            "agent definition."
        )

    try:
        converted_components = object_models_to_yaml(
            [
                {
                    "key": f"dialog:{index}",
                    "objectModel": component["dialog"],
                }
                for index, component in enumerate(dialog_components)
            ]
            + [
                {
                    "key": "agent",
                    "objectModel": {
                        **gpt_components[0]["metadata"],
                        "displayName": (
                            gpt_components[0].get("displayName")
                            or changeset["bot"].get("displayName")
                        ),
                    },
                }
            ]
            + [
                {
                    "key": f"variable:{index}",
                    "objectModel": component["variable"],
                }
                for index, component in enumerate(variable_components)
            ]
        )
    except ObjectModelConverterError as exc:
        raise ExistingDASetupError(
            f"Could not run the Microsoft Object Model converter: {exc}"
        ) from exc

    converted_dialogs = converted_components[: len(dialog_components)]
    converted_agent = converted_components[len(dialog_components)]
    converted_variables = converted_components[len(dialog_components) + 1 :]

    unprojected_dialogs: list[dict[str, str]] = []
    for component, converted in zip(
        dialog_components,
        converted_dialogs,
        strict=True,
    ):
        schema_name = str(component["schemaName"])
        dialog = component["dialog"]
        if converted.get("success") is not True:
            error = converted.get("error")
            message = (
                str(error.get("message") or "")
                if isinstance(error, dict)
                else ""
            )
            unprojected_dialogs.append(
                {
                    "schemaName": schema_name,
                    "displayName": str(
                        component.get("displayName") or schema_name
                    ),
                    "dialogKind": str(dialog.get("$kind") or "Unknown"),
                    "reason": "object-model-conversion-failed",
                    "detail": message,
                }
            )
            continue
        yaml_content = converted.get("yaml")
        if not isinstance(yaml_content, str) or not yaml_content.strip():
            raise ExistingDASetupError(
                "The Microsoft Object Model converter returned empty YAML "
                f"for {schema_name}."
            )
        suffix = _schema_suffix(schema_name)
        topic_path = destination / "topics" / f"{suffix}.mcs.yml"
        topic_path.parent.mkdir(parents=True, exist_ok=True)
        topic_path.write_text(
            yaml_content,
            encoding="utf-8",
            newline="",
        )
        topic_entries.append(
            {
                "path": topic_path.relative_to(destination).as_posix(),
                "componentKind": "DialogComponent",
                "componentId": component.get("id"),
                "schemaName": schema_name,
                "displayName": component.get("displayName"),
                "version": component.get("version"),
            }
        )
    projected_entries.extend(topic_entries)
    if unprojected_dialogs:
        failed = ", ".join(
            entry["schemaName"] for entry in unprojected_dialogs
        )
        raise ExistingDASetupError(
            "The Microsoft Object Model converter could not materialize all "
            f"authorable dialog components: {failed}."
        )
    if not topic_entries:
        raise ExistingDASetupError(
            "The Microsoft Object Model converter could not materialize any "
            "authorable dialog components."
        )

    agent_yaml = converted_agent.get("yaml")
    if (
        converted_agent.get("success") is not True
        or not isinstance(agent_yaml, str)
        or not agent_yaml.strip()
    ):
        raise ExistingDASetupError(
            "The Microsoft Object Model converter could not materialize the "
            "agent definition."
        )
    agent_path = destination / "agent.mcs.yml"
    agent_path.write_text(agent_yaml, encoding="utf-8", newline="")
    projected_entries.append(
        {
            "path": "agent.mcs.yml",
            "componentKind": "GptComponent",
            "componentId": gpt_components[0].get("id"),
            "schemaName": gpt_components[0].get("schemaName"),
            "displayName": gpt_components[0].get("displayName"),
            "version": gpt_components[0].get("version"),
        }
    )

    for component, converted in zip(
        variable_components,
        converted_variables,
        strict=True,
    ):
        yaml_content = converted.get("yaml")
        if (
            converted.get("success") is not True
            or not isinstance(yaml_content, str)
            or not yaml_content.strip()
        ):
            raise ExistingDASetupError(
                "The Microsoft Object Model converter could not materialize "
                f"global variable {component['schemaName']}."
            )
        variable_path = (
            destination
            / "variables"
            / f"{_schema_suffix(str(component['schemaName']))}.mcs.yml"
        )
        variable_path.parent.mkdir(parents=True, exist_ok=True)
        variable_path.write_text(yaml_content, encoding="utf-8", newline="")
        projected_entries.append(
            {
                "path": variable_path.relative_to(destination).as_posix(),
                "componentKind": "GlobalVariableComponent",
                "componentId": component.get("id"),
                "schemaName": component.get("schemaName"),
                "displayName": component.get("displayName"),
                "version": component.get("version"),
            }
        )

    return (
        topic_entries,
        projected_entries,
        component_counts,
        sorted(
            unprojected_dialogs,
            key=lambda item: (
                item["displayName"].casefold(),
                item["schemaName"].casefold(),
            ),
        ),
    )


def _write_snapshot(
    destination: Path,
    *,
    agent_name: str,
    schema_name: str,
    topics: list[dict[str, Any]],
    variable_count: int,
    counts: Counter[str],
    unprojected_dialogs: list[dict[str, str]],
) -> None:
    lines = [
        f"# {agent_name}",
        "",
        "## Setup identity",
        "",
        "- Release line: DA",
        "- Realm: Dev",
        f"- Schema: `{schema_name}`",
        "- Transport: AgentBuilder MinimalBot",
        "",
        "## Authorable agent configuration",
        "",
        "- `agent.mcs.yml`",
        f"- `{variable_count}` global variable file(s) under `variables/`",
        "",
        "## Authorable topics",
        "",
    ]
    lines.extend(
        f"- `{entry['path']}`"
        for entry in sorted(topics, key=lambda item: item["path"])
    )
    lines.extend(
        [
            "",
            "## Retained component payload",
            "",
            (
                "The complete fetched changeset is retained at "
                f"`{RAW_CHANGESET}` for component types that do not yet have "
                "a confirmed local authoring projection."
            ),
            "",
            "| Component kind | Count |",
            "| --- | ---: |",
        ]
    )
    lines.extend(
        f"| {kind} | {count} |"
        for kind, count in sorted(counts.items())
    )
    if unprojected_dialogs:
        lines.extend(
            [
                "",
                "## Unavailable dialog components",
                "",
                (
                    "These dialog records remain in the retained changeset "
                    "but are not available as local editable topics."
                ),
                "",
            ]
        )
        lines.extend(
            (
                f"- {entry['displayName']} "
                f"(`{entry['dialogKind']}`)"
            )
            for entry in unprojected_dialogs
        )
    lines.append("")
    (destination / "snapshot.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def _create_baseline(destination: Path) -> None:
    baseline = destination / ".baseline"
    baseline.mkdir()
    for child in destination.iterdir():
        if child.name in {".baseline", ".agentbuilder"}:
            continue
        target = baseline / child.name
        if child.is_dir():
            shutil.copytree(child, target)
        else:
            shutil.copy2(child, target)


def _load_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        return {}
    return _load_json(config_path)


def _write_config(
    config_path: Path,
    *,
    agent_entry: dict[str, Any],
    environment_id: str,
    host: str,
    api_version: str,
    component_counts: Counter[str],
) -> None:
    existing = _load_config(config_path)
    agents = existing.get("agents", [])
    if not isinstance(agents, list):
        raise ExistingDASetupError(
            "Existing local config contains a malformed agents list."
        )
    agents = [
        item
        for item in agents
        if isinstance(item, dict)
        and item.get("slug") != agent_entry["slug"]
        and str(item.get("botId") or "").casefold()
        != str(agent_entry["botId"]).casefold()
    ]
    agents.append(agent_entry)
    agents.sort(key=lambda item: str(item.get("name") or ""))
    config = {
        **existing,
        "configVersion": 1,
        "setup": "complete",
        "releaseLine": "da",
        "transport": "agentbuilder",
        "environmentId": environment_id,
        "powerPlatformApiEndpoint": host,
        "agentBuilderApiVersion": api_version,
        "agent": agent_entry,
        "activeAgent": agent_entry["slug"],
        "agents": agents,
        "templateConfigsDiscovered": False,
        "templateConfigCount": 0,
        "workflowCount": int(
            component_counts.get("CloudFlowDefinitionComponent", 0)
        ),
        "evaluationCount": int(
            component_counts.get("TestCaseComponent", 0)
        ),
    }
    config_path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=f"{config_path.name}.",
        suffix=".tmp",
        dir=config_path.parent,
        text=True,
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(config, stream, indent=2, ensure_ascii=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, config_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def attach_existing_dev(
    client: AgentBuilderClient,
    *,
    environment_id: str,
    agent_id: str,
    kit_root: Path,
    refresh: bool = False,
    selection_source: str | None = None,
) -> dict[str, Any]:
    """Resolve an existing Dev agent and materialize its local DA workspace."""
    connection = validate_existing_dev_connection(
        client,
        environment_id=environment_id,
        agent_id=agent_id,
        selection_source=selection_source,
    )
    existing_setup = _validate_setup_target(kit_root, connection)
    if existing_setup is not None:
        connection["agent"]["workspaceSlug"] = existing_setup["agent"][
            "workspace_slug"
        ]
    normalized_environment_id = connection["environment"]["id"]
    normalized_agent_id = connection["agent"]["id"]
    schema_name = connection["agent"]["schemaName"]
    family_id = connection["agent"]["almFamilyId"]
    agent_name = connection["agent"]["name"]
    changeset = client.fetch_components(normalized_agent_id)
    _validate_changeset_identity(changeset, normalized_agent_id)
    slug = connection["agent"]["workspaceSlug"]
    destination = kit_root / "workspace" / "agents" / slug
    changeset_sha = _changeset_sha256(changeset)
    metadata_path = destination / ATTACH_METADATA
    component_counts = Counter(
        str(component.get("$kind") or "Unknown")
        for change in _component_changes(changeset)
        if isinstance((component := change.get("component")), dict)
    )
    unprojected_dialogs: list[dict[str, str]] = []
    topics: list[dict[str, Any]]
    projected_entries: list[dict[str, Any]] = []
    materialize = not destination.exists()
    if destination.exists():
        if not metadata_path.is_file():
            raise ExistingDASetupError(
                f"Workspace already exists and is not managed by DA setup: "
                f"{destination}"
            )
        metadata = _load_json(metadata_path)
        stored_changeset_path = destination / RAW_CHANGESET
        stored_changeset_sha = (
            _changeset_sha256(_load_json(stored_changeset_path))
            if stored_changeset_path.is_file()
            else None
        )
        unchanged = (
            str(metadata.get("agentId") or "").casefold()
            == normalized_agent_id.casefold()
            and (
                metadata.get("changesetSha256") == changeset_sha
                or stored_changeset_sha == changeset_sha
            )
        )
        if (
            unchanged
            and metadata.get("projectionVersion")
            != WORKSPACE_PROJECTION_VERSION
            and not refresh
        ):
            raise ExistingDASetupError(
                "The local DA workspace uses an older projection. Run the "
                "explicit refresh flow to checkpoint local files and "
                "materialize the complete agent workspace."
            )
        unchanged = (
            unchanged
            and metadata.get("projectionVersion")
            == WORKSPACE_PROJECTION_VERSION
        )
        if unchanged and not refresh:
            stored_unprojected = metadata.get("unprojectedDialogs", [])
            if not isinstance(stored_unprojected, list):
                raise ExistingDASetupError(
                    "Workspace attach metadata contains malformed "
                    "unprojected dialogs."
                )
            unprojected_dialogs = stored_unprojected
            if (
                metadata.get("changesetSha256") != changeset_sha
                or metadata.get("selectedBy") != connection["selectedBy"]
            ):
                metadata = {
                    **metadata,
                    "changesetSha256": changeset_sha,
                    "selectedBy": connection["selectedBy"],
                }
                _write_json(metadata_path, metadata)
            result = {
                **metadata,
                "status": "resumed",
                "selectedBy": connection["selectedBy"],
            }
            topics = [
                {"path": path}
                for path in metadata.get("topicPaths", [])
            ]
        elif not refresh:
            raise ExistingDASetupError(
                f"Workspace has changed since its last DA setup: {destination}. "
                "Run the explicit refresh flow to checkpoint and replace it."
            )
        else:
            materialize = True

    if materialize:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(
            tempfile.mkdtemp(prefix=f".{slug}.", dir=destination.parent)
        )
        try:
            _write_json(temporary / RAW_CHANGESET, changeset)
            (
                topics,
                projected_entries,
                component_counts,
                unprojected_dialogs,
            ) = _materialize_workspace(changeset, temporary)
            _write_json(
                temporary / ".component-map.json",
                {
                    entry["path"]: {
                        key: value
                        for key, value in entry.items()
                        if key != "path"
                    }
                    for entry in projected_entries
                },
            )
            variable_paths = sorted(
                entry["path"]
                for entry in projected_entries
                if entry["componentKind"] == "GlobalVariableComponent"
            )
            metadata = {
                "status": "refreshed" if destination.exists() else "created",
                "releaseLine": "da",
                "transport": "agentbuilder",
                "projectionEngine": PROJECTION_ENGINE,
                "projectionVersion": WORKSPACE_PROJECTION_VERSION,
                "environmentId": normalized_environment_id,
                "host": client.host,
                "apiVersion": client.api_version,
                "agentId": normalized_agent_id,
                "agentName": agent_name,
                "schemaName": schema_name,
                "realm": "dev",
                "almFamilyId": family_id,
                "setupSource": "existing-dev",
                "selectedBy": connection["selectedBy"],
                "changesetSha256": changeset_sha,
                "topicCount": len(topics),
                "topicPaths": sorted(entry["path"] for entry in topics),
                "agentPath": "agent.mcs.yml",
                "variableCount": len(variable_paths),
                "variablePaths": variable_paths,
                "componentCounts": dict(sorted(component_counts.items())),
                "unprojectedDialogs": unprojected_dialogs,
            }
            _write_json(temporary / ATTACH_METADATA, metadata)
            _write_snapshot(
                temporary,
                agent_name=agent_name,
                schema_name=schema_name,
                topics=topics,
                variable_count=len(variable_paths),
                counts=component_counts,
                unprojected_dialogs=unprojected_dialogs,
            )
            _create_baseline(temporary)
            if destination.exists():
                from checkpoint import create_checkpoint, restore_from

                checkpoint_number = create_checkpoint(
                    str(destination),
                    "before DA setup refresh",
                )
                baseline = destination / ".baseline"
                if baseline.exists():
                    shutil.rmtree(baseline)
                restore_from(str(destination), str(temporary))
                shutil.rmtree(temporary)
                result = {
                    **metadata,
                    "checkpoint": checkpoint_number,
                }
            else:
                temporary.rename(destination)
                result = metadata
        except Exception as exc:
            _write_json(
                kit_root / ".local/setup/da-projection-failure.json",
                {
                    "environmentId": normalized_environment_id,
                    "agentId": normalized_agent_id,
                    "changesetSha256": changeset_sha,
                    "errorType": type(exc).__name__,
                    "message": str(exc),
                    "changeset": changeset,
                },
            )
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    agent_entry = {
        "name": agent_name,
        "botId": normalized_agent_id,
        "schemaName": schema_name,
        "isManaged": connection["agent"]["isManaged"],
        "slug": slug,
        "folder": destination.relative_to(kit_root).as_posix(),
        "releaseLine": "da",
        "transport": "agentbuilder",
        "environmentId": normalized_environment_id,
        "powerPlatformApiEndpoint": client.host,
        "realm": "dev",
        "almFamilyId": family_id,
        "setupSource": "existing-dev",
        "agentBuilderChangeSetPath": (
            destination.relative_to(kit_root) / RAW_CHANGESET
        ).as_posix(),
    }
    try:
        _write_config(
            kit_root / ".local" / "config.json",
            agent_entry=agent_entry,
            environment_id=normalized_environment_id,
            host=client.host,
            api_version=client.api_version,
            component_counts=component_counts,
        )
    except Exception:
        if result["status"] == "created":
            shutil.rmtree(destination, ignore_errors=True)
        raise
    failure_evidence = kit_root / ".local/setup/da-projection-failure.json"
    if failure_evidence.exists():
        failure_evidence.unlink()
    projected_kinds = {
        "DialogComponent",
        "GlobalVariableComponent",
        "GptComponent",
    }
    workspace = {
        "status": "qualified-complete",
        "folder": destination.relative_to(kit_root).as_posix(),
        "agentPath": "agent.mcs.yml",
        "topicCount": int(result["topicCount"]),
        "variableCount": int(result["variableCount"]),
        "projectedComponentKinds": sorted(projected_kinds),
        "unprojectedComponentKinds": {
            kind: count
            for kind, count in sorted(component_counts.items())
            if kind not in projected_kinds
        },
        "unprojectedDialogCount": 0,
        "completedAt": _utc_now(),
    }
    canonical_state = _record_canonical_setup_complete(
        kit_root,
        connection,
        workspace,
    )
    return {
        **result,
        "connectionStatus": "workspace-ready",
        "workspace": workspace,
        "setupState": CANONICAL_SETUP_STATE.as_posix(),
        "setupStatus": canonical_state["status"],
    }


def summarize_agents(agents: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Return the safe user-choice fields from AgentBuilder agent cards."""
    choices = []
    for agent in agents:
        agent_id = str(
            agent.get("botId")
            or agent.get("cdsBotId")
            or agent.get("componentIdUnique")
            or ""
        )
        try:
            normalized_id = _normalize_guid(agent_id, "Agent ID")
        except ExistingDASetupError:
            continue
        name = str(
            agent.get("fullBotName")
            or agent.get("displayName")
            or agent.get("shortBotName")
            or normalized_id
        )
        choices.append({"id": normalized_id, "name": name})
    return sorted(
        choices,
        key=lambda item: (item["name"].casefold(), item["id"]),
    )


def _add_agentbuilder_target_arguments(
    parser: argparse.ArgumentParser,
) -> None:
    parser.add_argument(
        "--target-url",
        help=(
            "Copied target text containing an environment and optional agent "
            "resource identifier. External makers normally use this instead "
            "of environment listing."
        ),
    )
    parser.add_argument("--environment-id")
    parser.add_argument(
        "--ring",
        choices=("prod", "preprod", "test"),
        help=(
            "Service ring override. Recognized Copilot Studio hostname text "
            "selects its ring; other targets default to prod."
        ),
    )
    parser.add_argument(
        "--tenant-id",
        help=(
            "Target tenant override. Omit for first-run account selection; "
            "the authenticated token supplies the tenant identity."
        ),
    )
    parser.add_argument(
        "--select-account",
        action="store_true",
        help=(
            "Force browser account selection for an identity-recovery retry."
        ),
    )
    parser.add_argument("--host")
    parser.add_argument("--api-version", default=DEFAULT_API_VERSION)
    parser.add_argument("--kit-root", type=Path, default=Path.cwd())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    list_agents = commands.add_parser(
        "list-agents",
        help="List directly discoverable AgentBuilder agents.",
    )
    _add_agentbuilder_target_arguments(list_agents)
    inspect_agent = commands.add_parser(
        "inspect-agent",
        help="Read the server-reported route realm for one exact agent.",
    )
    _add_agentbuilder_target_arguments(inspect_agent)
    inspect_agent.add_argument(
        "--agent-id",
        help="Agent ID override when target extraction omits it.",
    )
    validate_agent = commands.add_parser(
        "validate-agent",
        help="Validate one exact editable Dev agent without writing setup state.",
    )
    _add_agentbuilder_target_arguments(validate_agent)
    validate_agent.add_argument(
        "--agent-id",
        help="Agent ID override when target extraction omits it.",
    )
    attach = commands.add_parser(
        "attach",
        help="Validate and attach a known existing Dev agent.",
    )
    _add_agentbuilder_target_arguments(attach)
    attach.add_argument(
        "--agent-id",
        help="Agent ID override or fallback when target extraction omits it.",
    )
    attach.add_argument(
        "--refresh",
        action="store_true",
        help="Checkpoint and replace a changed existing workspace.",
    )
    return parser


def _client_from_args(
    args: argparse.Namespace,
    environment_id: str,
    ring: str,
) -> AgentBuilderClient:
    host = (
        validate_environment_host(args.host, ring)
        if args.host
        else derive_environment_host(environment_id, ring)
    )
    token, tenant_id = _authentication_from_args(args, ring)
    return AgentBuilderClient(
        host,
        token,
        ring=ring,
        tenant_id=tenant_id,
        api_version=args.api_version,
    )


def _authentication_from_args(
    args: argparse.Namespace,
    ring: str,
) -> tuple[str, str]:
    kit_root = args.kit_root.resolve()
    cache_path = kit_root / ".local" / ".agentbuilder_token_cache.bin"
    if args.tenant_id:
        token = authenticate(
            args.tenant_id,
            ring,
            cache_path=cache_path,
            force_account_selection=args.select_account,
        )
        tenant_id = args.tenant_id
    else:
        token, tenant_id = authenticate_selected_tenant(
            ring,
            cache_path=cache_path,
        )
    return token, tenant_id


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        target = resolve_da_target(
            target_url=args.target_url,
            environment_id=args.environment_id,
            agent_id=getattr(args, "agent_id", None),
            ring=args.ring,
            require_agent=args.command
            in {"attach", "inspect-agent", "validate-agent"},
        )
        environment_id = target["environmentId"]
        if args.command == "attach":
            _require_object_model_dependencies()
        client = _client_from_args(args, environment_id, target["ring"])
        if args.command == "list-agents":
            inspection = inspect_dev_agents(client)
            result = {
                "environmentId": environment_id,
                "agents": summarize_agents(inspection["devAgents"]),
                "excludedNonDevCount": inspection["excludedNonDevCount"],
                "unverifiedAgentCount": inspection[
                    "unverifiedAgentCount"
                ],
            }
            print(
                f"DA_AGENT_LIST_JSON:{json.dumps(result, ensure_ascii=True)}"
            )
            return 0

        if args.command == "inspect-agent":
            result = inspect_agent_route(
                client,
                environment_id=environment_id,
                agent_id=target["agentId"],
            )
            print(
                "DA_AGENT_ROUTE_JSON:"
                f"{json.dumps(result, ensure_ascii=True)}"
            )
            return 0

        if args.command == "validate-agent":
            connection = validate_existing_dev_connection(
                client,
                environment_id=environment_id,
                agent_id=target["agentId"],
                selection_source=target.get("agentSelection"),
            )
            result = {
                "environmentId": connection["environment"]["id"],
                "agentId": connection["agent"]["id"],
                "agentName": connection["agent"]["name"],
                "schemaName": connection["agent"]["schemaName"],
                "realm": connection["agent"]["realm"],
                "almFamilyId": connection["agent"]["almFamilyId"],
                "isManaged": connection["agent"]["isManaged"],
                "selectedBy": connection["selectedBy"],
            }
            print(
                "DA_AGENT_VALIDATION_JSON:"
                f"{json.dumps(result, ensure_ascii=True)}"
            )
            return 0

        result = attach_existing_dev(
            client,
            environment_id=environment_id,
            agent_id=target["agentId"],
            kit_root=args.kit_root.resolve(),
            refresh=args.refresh,
            selection_source=target.get("agentSelection"),
        )
    except (
        AgentBuilderError,
        ExistingDASetupError,
        OSError,
        ValueError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"DA_EXISTING_DEV_SETUP_JSON:{json.dumps(result, ensure_ascii=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
