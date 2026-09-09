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
from urllib.parse import unquote, urlparse

from agentbuilder import (
    DEFAULT_API_VERSION,
    AgentBuilderClient,
    AgentBuilderError,
    authenticate,
    authenticate_selected_tenant,
    canonical_json,
    derive_environment_host,
    validate_environment_host,
)
from agentbuilder_topic_projection import ProjectionError, project_dialog


ATTACH_METADATA = ".agentbuilder/attach.json"
RAW_CHANGESET = ".agentbuilder/components.json"
DA_CONNECTION_STATE = Path(".local/setup/da-connection.json")
DA_COMPONENT_SNAPSHOT = Path(".local/setup/da-components.json")
STUDIO_RING_BY_HOST = {
    "copilotstudio.microsoft.com": "prod",
    "copilotstudio.preprod.microsoft.com": "preprod",
    "copilotstudio.test.microsoft.com": "test",
}


class ExistingDASetupError(RuntimeError):
    """Raised when existing-Dev setup cannot preserve its invariants."""


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
    """Extract DA resource identity from a trusted Power Platform URL."""
    parsed = urlparse(target_url.strip())
    hostname = (parsed.hostname or "").casefold()
    trusted_hosts = {*STUDIO_RING_BY_HOST, "make.powerapps.com"}
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or hostname not in trusted_hosts
    ):
        raise ExistingDASetupError(
            "DA target URL must be an HTTPS Copilot Studio or Power Apps URL."
        )
    segments = [
        unquote(segment)
        for segment in parsed.path.split("/")
        if segment
    ]
    try:
        environment_index = next(
            index
            for index, segment in enumerate(segments)
            if segment.casefold() == "environments"
        )
        environment_id = _normalize_environment_id(
            segments[environment_index + 1]
        )
    except (StopIteration, IndexError, ExistingDASetupError) as exc:
        raise ExistingDASetupError(
            "DA target URL does not contain a valid environment ID."
        ) from exc

    result = {
        "environmentId": environment_id,
        "source": (
            "copilot-studio-url"
            if hostname in STUDIO_RING_BY_HOST
            else "power-apps-url"
        ),
    }
    if hostname in STUDIO_RING_BY_HOST:
        result["ring"] = STUDIO_RING_BY_HOST[hostname]
        for resource_name in ("bots", "copilots"):
            try:
                resource_index = next(
                    index
                    for index, segment in enumerate(segments)
                    if segment.casefold() == resource_name
                )
            except StopIteration:
                continue
            try:
                result["agentId"] = _normalize_guid(
                    segments[resource_index + 1],
                    "Agent ID",
                )
            except (IndexError, ExistingDASetupError) as exc:
                raise ExistingDASetupError(
                    "Copilot Studio target URL contains an invalid agent ID."
                ) from exc
            break
    return result


def resolve_da_target(
    *,
    target_url: str | None,
    environment_id: str | None,
    agent_id: str | None = None,
    ring: str | None = None,
    require_agent: bool = False,
) -> dict[str, str]:
    """Resolve explicit and URL-derived identifiers without ambiguity."""
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
            "Target URL and --environment-id identify different environments."
        )
    resolved_environment = explicit_environment or derived_environment
    if not resolved_environment:
        raise ExistingDASetupError(
            "Provide --target-url or --environment-id."
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
            "Target URL and --agent-id identify different agents."
        )
    resolved = {
        **target,
        "environmentId": resolved_environment,
    }
    derived_ring = target.get("ring")
    if ring and derived_ring and ring != derived_ring:
        raise ExistingDASetupError(
            "Target URL and --ring identify different service rings."
        )
    resolved["ring"] = ring or derived_ring or "prod"
    if resolved_agent := (explicit_agent or derived_agent):
        resolved["agentId"] = resolved_agent
        if derived_agent:
            resolved["agentSelection"] = target["source"]
    elif require_agent:
        raise ExistingDASetupError(
            "The target URL does not identify an agent; provide --agent-id."
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


def _find_listed_agent(
    agents: list[dict[str, Any]],
    agent_id: str,
) -> dict[str, Any] | None:
    expected = agent_id.casefold()
    return next(
        (
            agent
            for agent in agents
            if str(
                agent.get("botId")
                or agent.get("cdsBotId")
                or agent.get("componentIdUnique")
                or ""
            ).casefold()
            == expected
        ),
        None,
    )


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
    listed_agent = None
    if selection_source is None:
        listed_agent = _find_listed_agent(
            client.list_agents(),
            normalized_agent_id,
        )
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
        "selectedBy": selection_source or (
            "list" if listed_agent is not None else "direct-id-fallback"
        ),
        "verifiedAt": _utc_now(),
    }


def _connection_identity(state: dict[str, Any]) -> tuple[Any, ...]:
    environment = state.get("environment", {})
    agent = state.get("agent", {})
    return (
        state.get("stateKind"),
        state.get("releaseLine"),
        state.get("setupSource"),
        state.get("transport"),
        environment.get("id"),
        environment.get("tenantId"),
        environment.get("powerPlatformApiEndpoint"),
        environment.get("ring"),
        environment.get("apiVersion"),
        agent.get("id"),
        agent.get("schemaName"),
        agent.get("realm"),
        agent.get("almFamilyId"),
    )


def load_da_connection_state(kit_root: Path) -> dict[str, Any]:
    """Load and validate temporary DA setup state for deterministic resume."""
    path = kit_root / DA_CONNECTION_STATE
    if not path.exists():
        return {
            "schemaVersion": 1,
            "stateKind": "da-existing-dev-connection",
            "status": "not-started",
        }
    state = _load_json(path)
    if state.get("schemaVersion") != 1:
        raise ExistingDASetupError(
            "Temporary DA setup state has an unsupported schema version."
        )
    if state.get("stateKind") != "da-existing-dev-connection":
        raise ExistingDASetupError(
            "Temporary DA setup state has an unexpected state kind."
        )
    status = state.get("status")
    if status not in {"connected", "acquired", "workspace-ready"}:
        raise ExistingDASetupError(
            f"Temporary DA setup state has an invalid status: {status!r}."
        )
    if any(value in (None, "") for value in _connection_identity(state)):
        raise ExistingDASetupError(
            "Temporary DA setup state is missing connection identity."
        )
    if not state.get("agent", {}).get("workspaceSlug"):
        raise ExistingDASetupError(
            "Temporary DA setup state is missing its workspace identity."
        )
    if status in {"acquired", "workspace-ready"}:
        acquisition = state.get("acquisition")
        if (
            not isinstance(acquisition, dict)
            or acquisition.get("status") != "acquired"
            or not acquisition.get("changesetSha256")
            or not acquisition.get("rawPath")
        ):
            raise ExistingDASetupError(
                "Temporary DA setup state has incomplete acquisition state."
            )
    if status == "workspace-ready":
        workspace = state.get("workspace")
        if (
            not isinstance(workspace, dict)
            or workspace.get("status") != "qualified-complete"
            or not workspace.get("folder")
        ):
            raise ExistingDASetupError(
                "Temporary DA setup state has incomplete workspace state."
            )
    return state


def persist_da_connection_state(
    kit_root: Path,
    connection: dict[str, Any],
) -> dict[str, Any]:
    """Persist connection identity without regressing later DA setup phases."""
    path = kit_root / DA_CONNECTION_STATE
    canonical_state = kit_root / ".local" / "setup" / "config.json"
    if canonical_state.exists():
        raise ExistingDASetupError(
            "This workspace already has foundation setup state for another "
            "platform. Use a new workspace for DA setup."
        )
    workspace_config = kit_root / ".local" / "config.json"
    if workspace_config.exists():
        existing_workspace = _load_json(workspace_config)
        if existing_workspace.get("transport") != "agentbuilder":
            raise ExistingDASetupError(
                "This workspace already has a non-DA local configuration. "
                "Use a new workspace for DA setup."
            )
    if not path.exists():
        _write_json(path, connection)
        return connection
    existing = _load_json(path)
    if _connection_identity(existing) != _connection_identity(connection):
        raise ExistingDASetupError(
            "A different DA connection is already recorded. Start a new "
            "setup run before changing environment or agent identity."
        )
    updated = {
        **connection,
        "agent": {
            **connection["agent"],
            "workspaceSlug": existing["agent"]["workspaceSlug"],
        },
        "status": existing.get("status", "connected"),
    }
    for field in ("acquisition", "workspace"):
        if field in existing:
            updated[field] = existing[field]
    _write_json(path, updated)
    return updated


def _record_acquisition(
    kit_root: Path,
    connection: dict[str, Any],
    changeset: dict[str, Any],
) -> dict[str, Any]:
    changes = _component_changes(changeset)
    component_counts = Counter(
        str(component.get("$kind") or "Unknown")
        for change in changes
        if isinstance((component := change.get("component")), dict)
    )
    content_sha = _changeset_sha256(changeset)
    _write_json(kit_root / DA_COMPONENT_SNAPSHOT, changeset)
    updated = {
        **{
            key: value
            for key, value in connection.items()
            if key != "workspace"
        },
        "status": "acquired",
        "acquisition": {
            "status": "acquired",
            "rawPath": DA_COMPONENT_SNAPSHOT.as_posix(),
            "changesetSha256": content_sha,
            "componentCounts": dict(sorted(component_counts.items())),
            "acquiredAt": _utc_now(),
        },
    }
    _write_json(kit_root / DA_CONNECTION_STATE, updated)
    return updated


def _changeset_sha256(changeset: dict[str, Any]) -> str:
    """Fingerprint fetched content without transport or ordering noise."""
    content = {
        key: value
        for key, value in changeset.items()
        if key != "changeToken"
    }
    for key, value in tuple(content.items()):
        if key.endswith("Changes") and isinstance(value, list):
            content[key] = sorted(value, key=canonical_json)
    return hashlib.sha256(
        canonical_json(content).encode("utf-8")
    ).hexdigest()


def _record_workspace_ready(
    kit_root: Path,
    connection: dict[str, Any],
    *,
    folder: Path,
    topic_count: int,
    component_counts: Counter[str],
) -> dict[str, Any]:
    projected_kinds = {"DialogComponent"}
    unprojected = {
        kind: count
        for kind, count in sorted(component_counts.items())
        if kind not in projected_kinds
    }
    updated = {
        **connection,
        "status": "workspace-ready",
        "workspace": {
            "status": "qualified-complete",
            "folder": folder.relative_to(kit_root).as_posix(),
            "topicCount": topic_count,
            "projectedComponentKinds": sorted(projected_kinds),
            "unprojectedComponentKinds": unprojected,
            "completedAt": _utc_now(),
        },
    }
    _write_json(kit_root / DA_CONNECTION_STATE, updated)
    return updated


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


def _materialize_topics(
    changeset: dict[str, Any],
    destination: Path,
) -> tuple[list[dict[str, Any]], Counter[str]]:
    topic_entries: list[dict[str, Any]] = []
    component_counts: Counter[str] = Counter()
    for change in _component_changes(changeset):
        component = change.get("component")
        if not isinstance(component, dict):
            continue
        component_kind = str(component.get("$kind") or "Unknown")
        component_counts[component_kind] += 1
        if component_kind != "DialogComponent":
            continue
        schema_name = str(component.get("schemaName") or "")
        dialog = component.get("dialog")
        if not schema_name or not isinstance(dialog, dict):
            raise ExistingDASetupError(
                "Dialog component is missing its schema or dialog body."
            )
        suffix = _schema_suffix(schema_name)
        topic_path = destination / "topics" / f"{suffix}.mcs.yml"
        topic_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            topic_path.write_text(
                project_dialog(dialog),
                encoding="utf-8",
            )
        except ProjectionError as exc:
            raise ExistingDASetupError(
                f"Could not project topic {schema_name}: {exc}"
            ) from exc
        topic_entries.append(
            {
                "path": topic_path.relative_to(destination).as_posix(),
                "componentKind": component_kind,
                "componentId": component.get("id"),
                "schemaName": schema_name,
                "displayName": component.get("displayName"),
                "version": component.get("version"),
            }
        )
    if not topic_entries:
        raise ExistingDASetupError(
            "Component fetch did not contain any authorable dialog components."
        )
    return topic_entries, component_counts


def _write_snapshot(
    destination: Path,
    *,
    agent_name: str,
    schema_name: str,
    topics: list[dict[str, Any]],
    counts: Counter[str],
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
    connection = persist_da_connection_state(kit_root, connection)
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
    topics: list[dict[str, Any]]
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
        if unchanged and not refresh:
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

    connection = _record_acquisition(kit_root, connection, changeset)
    if materialize:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(
            tempfile.mkdtemp(prefix=f".{slug}.", dir=destination.parent)
        )
        try:
            topics, component_counts = _materialize_topics(changeset, temporary)
            _write_json(temporary / RAW_CHANGESET, changeset)
            _write_json(
                temporary / ".component-map.json",
                {
                    entry["path"]: {
                        key: value
                        for key, value in entry.items()
                        if key != "path"
                    }
                    for entry in topics
                },
            )
            metadata = {
                "status": "refreshed" if destination.exists() else "created",
                "releaseLine": "da",
                "transport": "agentbuilder",
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
                "componentCounts": dict(sorted(component_counts.items())),
            }
            _write_json(temporary / ATTACH_METADATA, metadata)
            _write_snapshot(
                temporary,
                agent_name=agent_name,
                schema_name=schema_name,
                topics=topics,
                counts=component_counts,
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
        except Exception:
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
    final_state = _record_workspace_ready(
        kit_root,
        connection,
        folder=destination,
        topic_count=int(result["topicCount"]),
        component_counts=component_counts,
    )
    return {
        **result,
        "connectionState": DA_CONNECTION_STATE.as_posix(),
        "connectionStatus": final_state["status"],
        "workspace": final_state["workspace"],
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
            "Copilot Studio agent URL or Power Apps environment URL. "
            "External makers normally use this instead of environment listing."
        ),
    )
    parser.add_argument("--environment-id")
    parser.add_argument(
        "--ring",
        choices=("prod", "preprod", "test"),
        help=(
            "Service ring override. Copilot Studio URLs select their ring; "
            "other targets default to prod."
        ),
    )
    parser.add_argument(
        "--tenant-id",
        help=(
            "Target tenant override. Omit for first-run account selection; "
            "the authenticated token supplies the tenant identity."
        ),
    )
    parser.add_argument("--host")
    parser.add_argument("--api-version", default=DEFAULT_API_VERSION)
    parser.add_argument("--kit-root", type=Path, default=Path.cwd())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "list-environments",
        help="List Power Platform environments without requiring Dataverse.",
    )
    status = commands.add_parser(
        "status",
        help="Show validated temporary DA setup state for resume.",
    )
    status.add_argument("--kit-root", type=Path, default=Path.cwd())
    list_agents = commands.add_parser(
        "list-agents",
        help="List directly discoverable AgentBuilder agents.",
    )
    _add_agentbuilder_target_arguments(list_agents)
    attach = commands.add_parser(
        "attach",
        help="Validate and attach a known existing Dev agent.",
    )
    _add_agentbuilder_target_arguments(attach)
    attach.add_argument(
        "--agent-id",
        help="Agent ID override or fallback when the target URL omits it.",
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
    kit_root = args.kit_root.resolve()
    cache_path = kit_root / ".local" / ".agentbuilder_token_cache.bin"
    if args.tenant_id:
        token = authenticate(
            args.tenant_id,
            ring,
            cache_path=cache_path,
        )
        tenant_id = args.tenant_id
    else:
        token, tenant_id = authenticate_selected_tenant(
            ring,
            cache_path=cache_path,
        )
    return AgentBuilderClient(
        host,
        token,
        ring=ring,
        tenant_id=tenant_id,
        api_version=args.api_version,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "status":
            result = load_da_connection_state(args.kit_root.resolve())
            print(
                f"DA_EXISTING_DEV_STATUS_JSON:"
                f"{json.dumps(result, ensure_ascii=True)}"
            )
            return 0

        if args.command == "list-environments":
            from list_environments import list_environments_with_tenant

            environments, tenant_id = list_environments_with_tenant()
            result = {
                "tenantId": tenant_id,
                "environments": environments,
            }
            print(
                "DA_ENVIRONMENT_LIST_JSON:"
                f"{json.dumps(result, ensure_ascii=True)}"
            )
            return 0

        target = resolve_da_target(
            target_url=args.target_url,
            environment_id=args.environment_id,
            agent_id=getattr(args, "agent_id", None),
            ring=args.ring,
            require_agent=args.command == "attach",
        )
        environment_id = target["environmentId"]
        client = _client_from_args(args, environment_id, target["ring"])
        if args.command == "list-agents":
            result = {
                "environmentId": environment_id,
                "agents": summarize_agents(client.list_agents()),
            }
            print(
                f"DA_AGENT_LIST_JSON:{json.dumps(result, ensure_ascii=True)}"
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
