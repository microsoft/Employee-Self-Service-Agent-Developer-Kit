# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Run Copilot Studio evaluation test sets and retrieve their results."""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from datetime import datetime, timezone
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import quote, urlparse

import yaml
import requests

from auth import authenticate, discover_tenant, load_config
from agentbuilder import ring_from_environment_host
from evaluation_method_policy import (
    EvaluationMethodError,
    load_evaluation_documents,
    validate_evaluation_documents,
)
from evaluation_review import (
    REVIEW_COMPLETED,
    REVIEW_FILENAME,
    REVIEW_REQUESTED,
    ReviewMetadataError,
    discover_evaluation_sets,
    parse_review_marker,
    parse_review_metadata,
)
from flightcheck.pp_admin_client import PPAdminClient
from flightcheck.powerplatform_client import PowerPlatformClient
from fetch_and_setup import fetch_components
from http_errors import APIError
from minimalbot_evaluation import (
    MinimalBotEvaluationClient,
    MinimalBotEvaluationError,
    is_minimalbot,
)


MCS_CONNECTOR_NAME = "shared_microsoftcopilotstudio"
INSTALLATION_CONFIG_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "reference"
    / "ess-agent-installation"
    / "config.json"
)
RUN_WAIT_GUIDANCE = (
    "I've started running your test set in Copilot Studio. This may take "
    "10-15 minutes. Return here to view the results when the run is complete; "
    "you don't need to open Copilot Studio."
)
RUN_NAVIGATION_WARNING = (
    "The run started, but its Copilot Studio link could not be constructed. "
    "Keep the run ID to retrieve its status; do not start another run to "
    "obtain a link."
)
REVIEW_PENDING_GUIDANCE = (
    "This test set is tagged for review and cannot run until the review is "
    "completed and pushed."
)
REVIEW_COMPLETION_NOT_PUSHED_GUIDANCE = (
    "Review is completed locally, but that completion has not been pushed. "
    "Complete the selected set's Run preparation before running."
)
COPILOT_STUDIO_ORIGIN_BY_RING = {
    "prod": "https://copilotstudio.microsoft.com",
    "preprod": "https://copilotstudio.preprod.microsoft.com",
    "test": "https://copilotstudio.test.microsoft.com",
}
DEFAULT_COPILOT_STUDIO_ORIGIN = COPILOT_STUDIO_ORIGIN_BY_RING["prod"]


def _studio_origin_for_config(config: dict[str, Any]) -> str:
    """Return the ring-appropriate Copilot Studio origin for this environment.

    The ring (prod / preprod / test) is derived from the configured Power
    Platform API endpoint host using the same suffix map ``agentbuilder``
    relies on, then mapped to the confirmed Studio host from
    ``setup_existing_da.STUDIO_RING_BY_HOST``. Falls back to the prod origin
    when the endpoint is absent or the ring cannot be determined.
    """
    endpoint = str(config.get("powerPlatformApiEndpoint") or "")
    try:
        ring = ring_from_environment_host(endpoint)
    except ValueError:
        return DEFAULT_COPILOT_STUDIO_ORIGIN
    return COPILOT_STUDIO_ORIGIN_BY_RING.get(ring, DEFAULT_COPILOT_STUDIO_ORIGIN)


def _agent_studio_url(
    origin: str,
    environment_id: str,
    bot_id: str,
    test_set_id: str | None = None,
    run_id: str | None = None,
    agent_backend: str | None = None,
) -> str | None:
    """Return the Copilot Studio link for a started or completed run, or None.

    When both ``test_set_id`` and ``run_id`` are known, a deep link to the
    exact run's results is built using the confirmed Copilot Studio route
    ``/environments/{env}/copilots/{bot}/evaluation/runsDetails/{testSetId}/{runId}``
    (verified against a live test-ring portal URL). ``agent_backend`` is
    appended as the ``?agentBackend=`` query parameter when supplied (e.g.
    ``cosmos`` for the test-ring MinimalBot).

    When the run/test-set IDs are unavailable, it falls back to the agent's
    overview page via the ``/environments/{env}/bots/{bot}/overview`` path
    already relied on by flightcheck (``checks/publishing.py``,
    ``checks/local_files.py``) and foundation-setup (``da-existing-dev.md``).
    Both forms are combined with the ring-aware ``origin``; no unverified
    route is fabricated.
    """
    if not origin or not environment_id or not bot_id:
        return None
    environment_id = quote(environment_id, safe="")
    bot_id = quote(bot_id, safe="")
    if test_set_id and run_id:
        url = (
            f"{origin}/environments/{environment_id}/copilots/{bot_id}"
            f"/evaluation/runsDetails/{quote(test_set_id, safe='')}"
            f"/{quote(run_id, safe='')}"
        )
        if agent_backend:
            url += f"?agentBackend={quote(agent_backend, safe='')}"
        return url
    return f"{origin}/environments/{environment_id}/bots/{bot_id}/overview"


class EvaluationRunError(RuntimeError):
    """Raised when an evaluation run operation cannot be completed."""


def _normalized_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def match_test_sets(
    test_sets: list[dict[str, Any]],
    query: str | None,
) -> list[dict[str, Any]]:
    """Rank active test sets by exact, substring, and fuzzy name similarity."""
    active = [
        item for item in test_sets
        if str(item.get("state", "Active")).casefold() == "active"
    ]
    if not query:
        return sorted(
            active,
            key=lambda item: str(item.get("displayName", "")).casefold(),
        )

    target = _normalized_name(query)
    ranked = []
    for item in active:
        name = str(item.get("displayName", ""))
        normalized = _normalized_name(name)
        if normalized == target:
            score = 1.0
        elif target and (target in normalized or normalized in target):
            score = 0.9
        else:
            score = SequenceMatcher(None, target, normalized).ratio()
        if score >= 0.45:
            ranked.append((score, name.casefold(), item))
    ranked.sort(key=lambda value: (-value[0], value[1]))
    return [
        {**item, "matchScore": round(score, 3)}
        for score, _, item in ranked
    ]


def resolve_environment_id(
    config: dict[str, Any],
    client: PowerPlatformClient,
) -> str:
    """Resolve the Power Platform environment ID for the Dataverse URL."""
    agent = config.get("agent")
    configured = (
        agent.get("environmentId") if isinstance(agent, dict) else None
    ) or config.get("environmentId")
    if isinstance(configured, str) and configured:
        return configured

    target_url = str(config.get("dataverseEndpoint", "")).rstrip("/")
    target_host = (urlparse(target_url).hostname or "").casefold()
    environments = client.list_environments_for_user()
    _raise_api_error(environments, "list environments")
    for environment in environments:
        url = str(environment.get("url", "")).rstrip("/")
        if not url:
            domain = str(environment.get("domainName", "")).strip()
            if domain:
                url = (
                    domain if domain.startswith("https://")
                    else f"https://{domain}"
                )
        host = (urlparse(url).hostname or "").casefold()
        if host == target_host:
            environment_id = environment.get("id")
            if environment_id:
                return str(environment_id)
    raise EvaluationRunError(
        "Could not resolve the Power Platform environment ID for "
        f"{target_url}."
    )


def _raise_api_error(value: Any, operation: str) -> None:
    if isinstance(value, dict) and value.get("_error"):
        status = value.get("_status", "unknown")
        if value.get("_error") == "not_found":
            raise EvaluationRunError(
                f"The requested evaluation run was not found (HTTP {status})."
            )
        raise EvaluationRunError(
            f"Power Platform API could not {operation} (HTTP {status})."
        )


def _connection_id(connection: dict[str, Any]) -> str:
    name = str(connection.get("name") or "").strip()
    if name:
        return name
    return str(connection.get("id") or "").rstrip("/").rsplit("/", 1)[-1]


def connected_mcs_connections(
    connections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Normalize connected Copilot Studio profiles for safe selection."""
    connected = []
    for connection in connections:
        properties = connection.get("properties") or {}
        statuses = properties.get("statuses") or []
        if not any(
            str(status.get("status", "")).casefold() == "connected"
            for status in statuses
            if isinstance(status, dict)
        ):
            continue
        created_by = properties.get("createdBy") or {}
        connection_id = _connection_id(connection)
        if not connection_id:
            continue
        connected.append({
            "id": connection_id,
            "displayName": (
                properties.get("displayName")
                or properties.get("accountName")
                or connection_id
            ),
            "accountName": properties.get("accountName"),
            "createdByDisplayName": created_by.get("displayName"),
            "createdByUserPrincipalName": (
                created_by.get("userPrincipalName")
                or created_by.get("email")
            ),
            "lastModifiedTime": (
                properties.get("lastModifiedTime")
                or connection.get("lastModifiedTime")
                or properties.get("createdTime")
                or connection.get("createdTime")
                or ""
            ),
        })
    return sorted(
        connected,
        key=lambda item: (
            str(item.get("displayName") or "").casefold(),
            item["id"],
        ),
    )


def select_mcs_connection(
    connections: list[dict[str, Any]],
    signed_in_username: str | None = None,
    requested_id: str | None = None,
) -> dict[str, Any]:
    """Select a connected profile, preferring the signed-in account."""
    connected = connected_mcs_connections(connections)
    if requested_id:
        selected = next(
            (item for item in connected if item["id"] == requested_id),
            None,
        )
        if selected:
            return selected
        raise EvaluationRunError(
            "The selected Copilot Studio connection is missing or is not "
            "Connected. Choose a connected profile and retry."
        )
    if not connected:
        raise EvaluationRunError(
            "No Connected Microsoft Copilot Studio connection was found in "
            "this environment. Create or repair the connection in Power Apps "
            "or Power Automate, then retry the evaluation run."
        )
    if len(connected) == 1:
        return connected[0]

    username = str(signed_in_username or "").casefold()
    if username:
        matching = [
            item for item in connected
            if username in {
                str(item.get("accountName") or "").casefold(),
                str(
                    item.get("createdByUserPrincipalName") or ""
                ).casefold(),
            }
        ]
        if matching:
            return max(
                matching,
                key=lambda item: (
                    str(item.get("lastModifiedTime") or ""),
                    item["id"],
                ),
            )

    raise EvaluationRunError(
        "Multiple Connected Copilot Studio profiles were found, but none "
        "uniquely matches the signed-in account. Sign in with the intended "
        "profile or provide --mcs-connection-id."
    )


def resolve_mcs_connection(
    config: dict[str, Any],
    environment_id: str,
    requested_id: str | None = None,
    signed_in_username: str | None = None,
) -> dict[str, Any]:
    """Discover and select the current user's Copilot Studio connection."""
    connections, effective_username = _discover_mcs_connections(
        config,
        environment_id,
        signed_in_username,
    )
    return select_mcs_connection(
        connections,
        effective_username,
        requested_id,
    )


def _discover_mcs_connections(
    config: dict[str, Any],
    environment_id: str,
    signed_in_username: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Return raw Copilot Studio connections and the authenticated username."""
    env_url = str(config["dataverseEndpoint"]).rstrip("/")
    client = PPAdminClient(discover_tenant(env_url))
    client.authenticate(
        include_flow=False,
        preferred_username=signed_in_username,
    )
    connections = client.get_connector_connections(
        environment_id,
        MCS_CONNECTOR_NAME,
    )
    _raise_api_error(connections, "list Copilot Studio connections")
    if not isinstance(connections, list):
        raise EvaluationRunError(
            "Power Platform API returned an invalid connection list."
        )
    return connections, signed_in_username or client.signed_in_username


def list_mcs_connections(
    config: dict[str, Any],
    environment_id: str,
    signed_in_username: str | None = None,
) -> list[dict[str, Any]]:
    """List connected profiles so the user can explicitly choose one."""
    connections, effective_username = _discover_mcs_connections(
        config,
        environment_id,
        signed_in_username,
    )
    username = str(effective_username or "").casefold()
    return [
        {
            **connection,
            "matchesSignedInAccount": bool(
                username
                and username in {
                    str(connection.get("accountName") or "").casefold(),
                    str(
                        connection.get("createdByUserPrincipalName") or ""
                    ).casefold(),
                }
            ),
        }
        for connection in connected_mcs_connections(connections)
    ]


def list_native_mcs_connections(
    client: MinimalBotEvaluationClient,
) -> list[dict[str, Any]]:
    """Expose the native transport's existing connection discovery for selection."""
    raw = client._connected(MCS_CONNECTOR_NAME)
    normalized = []
    for connection in raw:
        properties = connection.get("properties") or {}
        normalized.append({
            **connection,
            "properties": {
                **properties,
                "statuses": properties.get("statuses") or connection.get("statuses") or [],
            },
        })
    username = str(client.signed_in_username or "").casefold()
    return [
        {
            **connection,
            "matchesSignedInAccount": bool(
                username and username in {
                    str(connection.get("accountName") or "").casefold(),
                    str(connection.get("createdByUserPrincipalName") or "").casefold(),
                }
            ),
        }
        for connection in connected_mcs_connections(normalized)
    ]


def _required_agent_connection(config: dict[str, Any]) -> dict[str, Any] | None:
    """Return the configured agent's required invoker connection, if any."""
    agent = config.get("agent")
    schema_name = (
        str(agent.get("schemaName") or "").casefold()
        if isinstance(agent, dict)
        else ""
    )
    if not schema_name or not INSTALLATION_CONFIG_PATH.is_file():
        return None
    try:
        installation = json.loads(
            INSTALLATION_CONFIG_PATH.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationRunError(
            f"Unable to read agent installation config: {exc}"
        ) from exc
    installations = installation.get("installations")
    if not isinstance(installations, dict):
        return None
    for variant in installations.values():
        if not isinstance(variant, dict):
            continue
        required = variant.get("requiredConnection")
        if not isinstance(required, dict):
            continue
        reference_name = str(
            required.get("referenceLogicalName") or ""
        )
        if reference_name.casefold().startswith(f"{schema_name}."):
            return required
    return None


def resolve_tool_connections(
    config: dict[str, Any],
    environment_id: str,
    bot_id: str,
    signed_in_username: str | None,
) -> list[dict[str, Any]]:
    """Resolve required agent tool connections for the signed-in account."""
    required = _required_agent_connection(config)
    if not required:
        return []
    connector_name = str(required.get("connectorApiName") or "").strip()
    reference_name = str(
        required.get("referenceLogicalName") or ""
    ).strip()
    agent = config.get("agent")
    schema_name = (
        str(agent.get("schemaName") or "").strip()
        if isinstance(agent, dict)
        else ""
    )
    if not connector_name or not reference_name or not schema_name:
        raise EvaluationRunError(
            "The configured agent's required connection metadata is "
            "incomplete."
        )

    env_url = str(config["dataverseEndpoint"]).rstrip("/")
    client = PPAdminClient(discover_tenant(env_url))
    client.authenticate(
        include_flow=False,
        preferred_username=signed_in_username,
    )
    connections = client.get_connector_connections(
        environment_id,
        connector_name,
    )
    _raise_api_error(connections, f"list {connector_name} connections")
    connected = connected_mcs_connections(connections)
    if not connected:
        return []
    if len(connected) > 1:
        username = str(
            signed_in_username or client.signed_in_username or ""
        ).casefold()
        matching = [
            connection for connection in connected
            if username
            and username in {
                str(connection.get("accountName") or "").casefold(),
                str(
                    connection.get("createdByUserPrincipalName") or ""
                ).casefold(),
            }
        ]
        if not matching:
            return []
    selected = select_mcs_connection(
        connections,
        signed_in_username or client.signed_in_username,
    )
    return [{
        "botId": bot_id,
        "botSchemaName": schema_name,
        "connections": [{
            "connectorId": connector_name,
            "connectionId": selected["id"],
            "connectionReferenceName": reference_name,
        }],
    }]


def _runtime(config: dict[str, Any]) -> tuple[
    PowerPlatformClient,
    str,
    str,
    Path,
]:
    env_url = str(config.get("dataverseEndpoint") or "").rstrip("/")
    if not env_url:
        raise EvaluationRunError(
            "Dataverse endpoint is missing from .local/config.json. "
            "Run /setup first."
        )
    agent = config.get("agent")
    if not isinstance(agent, dict):
        raise EvaluationRunError(
            "Configured agent details are missing from .local/config.json. "
            "Run /setup first."
        )
    bot_id = str(agent.get("botId") or "").strip()
    agent_folder_value = str(agent.get("folder") or "").strip()
    if not bot_id or not agent_folder_value:
        raise EvaluationRunError(
            "Configured agent botId or folder is missing from "
            ".local/config.json. Run /setup first."
        )

    client = PowerPlatformClient(discover_tenant(env_url))
    client.authenticate()
    environment_id = resolve_environment_id(config, client)
    agent_folder = Path(agent_folder_value)
    return client, environment_id, bot_id, agent_folder


def list_remote_test_sets(
    client: PowerPlatformClient,
    environment_id: str,
    bot_id: str,
    query: str | None = None,
) -> list[dict[str, Any]]:
    """List active remote test sets, optionally ranked by a name query."""
    test_sets = client.list_maker_evaluation_test_sets(environment_id, bot_id)
    _raise_api_error(test_sets, "list evaluation test sets")
    return match_test_sets(test_sets, query)


def _review_block_reason(
    local_status: str | None,
    baseline_status: str | None,
    deployed_status: str | None,
) -> str | None:
    if local_status != baseline_status:
        if local_status == REVIEW_COMPLETED and deployed_status != REVIEW_COMPLETED:
            return REVIEW_COMPLETION_NOT_PUSHED_GUIDANCE
        if local_status == REVIEW_REQUESTED or baseline_status == REVIEW_REQUESTED:
            return REVIEW_PENDING_GUIDANCE
    elif deployed_status == REVIEW_REQUESTED:
        return REVIEW_PENDING_GUIDANCE
    return None


def _set_payload(folder: Path, *, include_review: bool = True) -> dict[str, str]:
    paths = list(folder.glob("*.mcs.yml"))
    review = folder / REVIEW_FILENAME
    if include_review and review.is_file():
        paths.append(review)
    return {path.name: path.read_text(encoding="utf-8") for path in paths}


def _require_synchronized_local_set(folder: Path, *, include_review: bool = True) -> None:
    baseline = folder.parent.parent / ".baseline" / "evaluations" / folder.name
    try:
        local = _set_payload(folder, include_review=include_review)
        if not baseline.is_dir() or local != _set_payload(baseline, include_review=include_review):
            raise EvaluationRunError(
                f"The selected test set has unprepared local changes: {folder}. "
                "Complete the selected set's Run preparation before starting "
                "its deployed ID; the older remote copy was not run."
            )
    except OSError as exc:
        raise EvaluationRunError(
            f"Unable to compare evaluation files in {folder}: {exc}"
        ) from exc


def list_run_candidates(
    workspace_root: str | Path = "workspace",
    config_path: str | Path = ".local/config.json",
    *,
    remote_sets: list[dict[str, Any]] | None = None,
    query: str | None = None,
    native: bool = False,
) -> list[dict[str, Any]]:
    """Discover exact local Run choices without staging, scoring, or mutations.

    A known deployed ID is not proof that the latest local content can run.
    Without a live remote listing, eligibility remains unverified until the
    selected set completes the action-aware preparation flow.
    """
    remote_by_id = {
        str(item.get("id")): item
        for item in (remote_sets or [])
        if str(item.get("state", "Active")).casefold() == "active"
    }
    candidates = []
    for item in discover_evaluation_sets(workspace_root, config_path):
        folder = Path(item["folder"])
        local_status = item["localStatus"]
        baseline_status = item["deployedStatus"]
        remote = None
        mapped_id = None
        changed = True
        if item["source"] != "Workspace":
            agent_folder = folder.parent.parent
            map_path = agent_folder / ".component-map.json"
            if map_path.is_file():
                try:
                    component_map = json.loads(map_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise EvaluationRunError(
                        f"Unable to read agent component map {map_path}: {exc}"
                    ) from exc
                if not isinstance(component_map, dict):
                    raise EvaluationRunError(
                        f"Agent component map must contain an object: {map_path}"
                    )
                parent_ids = {
                    str(metadata["botcomponentid"])
                    for relative_path, metadata in component_map.items()
                    if isinstance(metadata, dict)
                    and metadata.get("componenttype") == 19
                    and not metadata.get("parentbotcomponentid")
                    and metadata.get("botcomponentid")
                    and (agent_folder / relative_path).resolve().parent == folder
                }
                if len(parent_ids) > 1:
                    raise EvaluationRunError(
                        f"Multiple deployed parents are mapped to {folder}; "
                        "reconcile the selected set before Run."
                    )
                if parent_ids:
                    mapped_id = next(iter(parent_ids))
                    remote = remote_by_id.get(mapped_id)
            baseline = agent_folder / ".baseline" / "evaluations" / folder.name
            try:
                changed = not baseline.is_dir() or (
                    _set_payload(folder, include_review=not native)
                    != _set_payload(baseline, include_review=not native)
                )
            except OSError as exc:
                raise EvaluationRunError(
                    f"Unable to compare evaluation files in {folder}: {exc}"
                ) from exc
        deployed_status = baseline_status
        if remote is not None and not native:
            marker = parse_review_marker(remote.get("description"))
            if marker:
                deployed_status = marker["status"]
            elif remote.get("deployedReviewStatus"):
                deployed_status = remote["deployedReviewStatus"]
        review_block = _review_block_reason(
            local_status, baseline_status, deployed_status,
        )
        if native:
            review_block = REVIEW_PENDING_GUIDANCE if local_status == REVIEW_REQUESTED else None
        # An explicitly saved completion may be deployed by preparation; a
        # still-pending request can never be completed as a Run side effect.
        preparation_block = (
            review_block if review_block != REVIEW_COMPLETION_NOT_PUSHED_GUIDANCE
            else None
        )
        policy_error = None
        display_name = item["name"]
        try:
            parent, cases = load_evaluation_documents(folder)
            display_name = str(parent.get("displayName") or display_name)
            validate_evaluation_documents(parent, cases, context=str(folder))
        except EvaluationMethodError as exc:
            policy_error = str(exc)
        synchronized_candidate = bool(
            remote is not None
            and remote.get("runnable", True)
            and not changed
            and not review_block
            and not policy_error
        )
        blocked_reason = policy_error or review_block
        if (
            not blocked_reason and remote is not None
            and not remote.get("runnable", True)
        ):
            blocked_reason = (
                remote.get("blockedReason")
                or "The deployed set is blocked from running."
            )
            preparation_block = blocked_reason
        candidates.append({
            **item,
            "displayName": display_name,
            "localFolder": str(folder),
            "localSetName": folder.name,
            "id": str(remote["id"]) if remote is not None else None,
            "testSetId": str(remote["id"]) if remote is not None else None,
            "mappedTestSetId": mapped_id,
            "deployedReviewStatus": None if native else deployed_status,
            "hasLocalChanges": changed,
            "deployedIdentityKnown": remote is not None,
            "canPrepare": not (policy_error or preparation_block),
            "currentlyRunnable": None if synchronized_candidate else False,
            "runnable": None if synchronized_candidate else False,
            "requiresPreparation": True,
            "readinessReason": (
                "The local set matches its baseline and its deployed ID is "
                "available. Preparation must still verify the current deployed "
                "definition and the selected connection before Run."
                if synchronized_candidate else
                "Run readiness has not been established. Select this exact set "
                "to resolve its prerequisites and required preparation."
            ),
            "blockedReason": blocked_reason,
        })
    return match_test_sets(candidates, query)


def list_agent_test_sets(
    client: PowerPlatformClient,
    environment_id: str,
    bot_id: str,
    agent_folder: str | Path,
    query: str | None = None,
    include_blocked: bool = False,
) -> list[dict[str, Any]]:
    """List active local sets, optionally including review-blocked sets."""
    agent = Path(agent_folder)
    map_path = agent / ".component-map.json"
    if not map_path.is_file():
        raise EvaluationRunError(
            f"Agent component map not found: {map_path}. Run /setup first."
        )
    try:
        component_map = json.loads(map_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationRunError(
            f"Unable to read agent component map {map_path}: {exc}"
        ) from exc

    remote_sets = client.list_maker_evaluation_test_sets(
        environment_id,
        bot_id,
    )
    _raise_api_error(remote_sets, "list evaluation test sets")
    remote_by_id = {
        str(item.get("id")): item
        for item in remote_sets
        if str(item.get("state", "Active")).casefold() == "active"
    }

    local_sets = []
    seen: set[str] = set()
    for relative_path, metadata in component_map.items():
        if (
            not isinstance(metadata, dict)
            or metadata.get("componenttype") != 19
            or metadata.get("parentbotcomponentid")
            or not str(relative_path).startswith("evaluations/")
        ):
            continue
        parts = Path(str(relative_path)).parts
        if len(parts) != 3:
            continue
        test_set_id = str(metadata.get("botcomponentid") or "")
        remote = remote_by_id.get(test_set_id)
        if not remote or test_set_id in seen:
            continue
        set_folder = agent / "evaluations" / parts[1]
        if not set_folder.is_dir():
            continue
        review_statuses: list[str | None] = []
        for review_path in (
            set_folder / REVIEW_FILENAME,
            agent / ".baseline" / "evaluations" / parts[1] / REVIEW_FILENAME,
        ):
            review_status = None
            if not review_path.is_file():
                review_statuses.append(review_status)
                continue
            try:
                review_status = parse_review_metadata(
                    review_path.read_text(encoding="utf-8")
                )["status"]
            except (OSError, ReviewMetadataError) as exc:
                raise EvaluationRunError(
                    f"Unable to read review metadata {review_path}: {exc}"
                ) from exc
            review_statuses.append(review_status)
        local_review_status, baseline_review_status = review_statuses
        remote_review_status = None
        remote_description = remote.get("description")
        if isinstance(remote_description, str):
            remote_marker = parse_review_marker(remote_description)
            if remote_marker:
                remote_review_status = remote_marker["status"]
        # Reconcile the live remote review marker with any unpushed local
        # transition. A local review.json that differs from the pushed
        # baseline is a genuine pending change and governs eligibility;
        # otherwise the live remote/deployed state decides whether the set
        # can run, so a remote-completed set clears and a remote-requested
        # set blocks even when the local copy is untagged.
        deployed_review_status = (
            remote_review_status
            if remote_review_status is not None
            else baseline_review_status
        )
        blocked_reason = _review_block_reason(
            local_review_status, baseline_review_status, deployed_review_status,
        )
        if blocked_reason and not include_blocked:
            continue
        seen.add(test_set_id)
        local_count = sum(
            1
            for path in set_folder.glob("*.mcs.yml")
            if any(
                marker in path.read_text(encoding="utf-8")
                for marker in (
                    "kind: EvaluationData",
                    "kind: MultiTurnEvaluationCase",
                )
            )
        )
        local_sets.append({
            **remote,
            "localFolder": str(set_folder.resolve()),
            "localSetName": parts[1],
            "localTestCaseCount": local_count,
            "reviewStatus": local_review_status,
            "localReviewStatus": local_review_status,
            "deployedReviewStatus": deployed_review_status,
            "runnable": blocked_reason is None,
            "blockedReason": blocked_reason,
            "source": "Configured agent evaluations folder",
        })
    return match_test_sets(local_sets, query)


def _validate_deployed_dataverse_set(
    config: dict[str, Any],
    environment_id: str,
    bot_id: str,
    test_set_id: str,
) -> None:
    """Validate the selected server documents, never local files or a summary."""
    env_url = str(config.get("dataverseEndpoint") or "").rstrip("/")
    if not env_url:
        raise EvaluationRunError(
            "Dataverse endpoint is required to validate the deployed test set."
        )
    agent = config.get("agent") or {}
    if str(agent.get("botId") or "") != bot_id:
        raise EvaluationRunError(
            "The selected run target differs from the configured agent."
        )
    configured_environment = agent.get("environmentId") or config.get("environmentId")
    if configured_environment and str(configured_environment) != environment_id:
        raise EvaluationRunError(
            "The selected run environment differs from the configured environment."
        )
    with redirect_stdout(sys.stderr):
        token = authenticate(env_url)
    components = fetch_components(env_url, token, bot_id)
    parents = [
        component for component in components
        if str(component.get("botcomponentid") or "") == test_set_id
        and component.get("componenttype") == 19
        and not component.get("parentbotcomponentid")
    ]
    if len(parents) != 1:
        raise EvaluationRunError(
            f"The selected deployed test set {test_set_id} was not found "
            "on the configured agent."
        )
    parent = parents[0]
    marker = parse_review_marker(parent.get("description"))
    if marker and marker["status"] == REVIEW_REQUESTED:
        raise EvaluationRunError(REVIEW_PENDING_GUIDANCE)

    def document(component: dict[str, Any]) -> dict[str, Any]:
        raw = component.get("data")
        if not isinstance(raw, str) or not raw.strip():
            raise EvaluationRunError(
                f"Deployed evaluation component {component.get('botcomponentid')} "
                "has no readable definition; Run did not proceed."
            )
        try:
            value = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise EvaluationRunError(
                f"Unable to read deployed evaluation component "
                f"{component.get('botcomponentid')}: {exc}"
            ) from exc
        if not isinstance(value, dict):
            raise EvaluationRunError(
                "The deployed evaluation definition must contain an object; "
                "Run did not proceed."
            )
        return value

    children = [
        document(component) for component in components
        if str(component.get("parentbotcomponentid") or "") == test_set_id
    ]
    validate_evaluation_documents(
        document(parent), children, context=f"Deployed test set {test_set_id}",
    )


def start_run(
    client: PowerPlatformClient,
    environment_id: str,
    bot_id: str,
    test_set: dict[str, Any],
    mcs_connection_id: str,
    run_name: str | None = None,
    run_on_published_bot: bool = False,
    tools_connections: list[dict[str, Any]] | None = None,
    studio_origin: str = DEFAULT_COPILOT_STUDIO_ORIGIN,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Start an evaluation run and return its initial API state."""
    test_set_id = str(test_set["id"])
    if not test_set.get("runnable", True):
        raise EvaluationRunError(
            test_set.get("blockedReason")
            or "The selected test set is blocked from running."
        )
    if test_set.get("localFolder"):
        _require_synchronized_local_set(Path(test_set["localFolder"]))
    _validate_deployed_dataverse_set(
        config if config is not None else load_config(),
        environment_id, bot_id, test_set_id,
    )
    test_set_name = str(test_set.get("displayName") or test_set_id)
    now = datetime.now(timezone.utc)
    body: dict[str, Any] = {
        "evaluationRunName": (
            run_name
            or f"{test_set_name} - {now.strftime('%Y-%m-%d %H:%M UTC')}"
        ),
        "runOnPublishedBot": run_on_published_bot,
    }
    body["mcsConnectionId"] = mcs_connection_id
    if tools_connections:
        body["toolsConnections"] = tools_connections

    response = client.run_maker_evaluation_test_set(
        environment_id,
        bot_id,
        test_set_id,
        body,
    )
    _raise_api_error(response, "start the evaluation run")
    run_id = response.get("runId")
    if not isinstance(run_id, str) or not run_id.strip():
        raise EvaluationRunError(
            "Power Platform API did not return an evaluation run ID."
        )
    run_details = {
        "runId": str(run_id),
        "testSetId": test_set_id,
        "testSetName": test_set_name,
        "runName": body["evaluationRunName"],
        "startedAt": now.isoformat(),
        "userGuidance": RUN_WAIT_GUIDANCE,
        "agentStudioUrl": _agent_studio_url(
            studio_origin, environment_id, bot_id, test_set_id, run_id,
        ),
    }
    if not run_details["agentStudioUrl"]:
        run_details["navigationWarning"] = RUN_NAVIGATION_WARNING
    return {**response, **run_details}


def _remote_run_history(
    client: PowerPlatformClient,
    environment_id: str,
    bot_id: str,
) -> list[dict[str, Any]]:
    test_sets = client.list_maker_evaluation_test_sets(environment_id, bot_id)
    _raise_api_error(test_sets, "list evaluation test sets")
    names = {
        str(item.get("id")): str(item.get("displayName") or item.get("id"))
        for item in test_sets
    }
    runs = client.list_maker_evaluation_test_runs(environment_id, bot_id)
    _raise_api_error(runs, "list evaluation runs")
    enriched = []
    for run in runs:
        test_set_id = str(run.get("testSetId", ""))
        enriched.append({
            **run,
            "runId": str(run.get("id") or run.get("runId") or ""),
            "testSetName": names.get(test_set_id, "Unknown test set"),
            "source": "Power Platform API",
        })
    return sorted(
        enriched,
        key=lambda item: str(item.get("startTime", "")),
        reverse=True,
    )


def list_runs(
    client: PowerPlatformClient,
    environment_id: str,
    bot_id: str,
) -> list[dict[str, Any]]:
    """List remote runs with test-set display names."""
    return _remote_run_history(client, environment_id, bot_id)


def _case_names(agent_folder: Path) -> dict[str, str]:
    map_path = agent_folder / ".component-map.json"
    if not map_path.is_file():
        return {}
    try:
        component_map = json.loads(map_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    names = {}
    for relative_path, metadata in component_map.items():
        if (
            isinstance(metadata, dict)
            and metadata.get("componenttype") == 19
            and metadata.get("parentbotcomponentid")
            and metadata.get("botcomponentid")
        ):
            names[str(metadata["botcomponentid"])] = str(
                metadata.get("name") or Path(relative_path).stem
            )
    return names


def _metric(
    case: dict[str, Any],
    metric_type: str,
) -> dict[str, Any] | None:
    metrics = case.get("metricsResults")
    if not isinstance(metrics, list):
        return None
    return next(
        (
            metric for metric in metrics
            if isinstance(metric, dict)
            and metric.get("type") == metric_type
        ),
        None,
    )


def _metric_result(metric: dict[str, Any] | None) -> dict[str, Any]:
    result = metric.get("result") if metric else None
    return result if isinstance(result, dict) else {}


def _case_passed(case: dict[str, Any]) -> bool:
    metrics = case.get("metricsResults")
    if not isinstance(metrics, list) or not metrics:
        # A case with no metric results cannot be verified as passing, even if
        # it reached the "completed" state. Treat it as non-pass so it surfaces
        # for review (grouped under "Execution or metric failure") instead of
        # being counted as a silent false-positive.
        return False
    return all(
        str(_metric_result(metric).get("status", "")).casefold() == "pass"
        for metric in metrics
        if isinstance(metric, dict)
    ) and any(isinstance(metric, dict) for metric in metrics)


def _failure_pattern(case: dict[str, Any]) -> dict[str, str]:
    compare = _metric_result(_metric(case, "CompareMeaning"))
    general = _metric_result(_metric(case, "GeneralQuality"))

    if str(compare.get("status", "")).casefold() == "fail":
        evidence = (
            compare.get("aiResultReason")
            or compare.get("errorReason")
            or "CompareMeaning returned Fail."
        )
        return {
            "category": "Expected-meaning mismatch",
            "suggestedAction": (
                "Inspect the agent response against the expected behavior and "
                "correct the operation, grounding, or response."
            ),
            "evidence": str(evidence),
        }

    if str(general.get("status", "")).casefold() == "fail":
        data = general.get("data")
        data = data if isinstance(data, dict) else {}
        abstention = str(data.get("abstention", "NA"))
        completeness = str(data.get("completeness", "NA"))
        compare_reason = str(compare.get("aiResultReason") or "").strip()
        if abstention.casefold() == "yes":
            category = "Abstention graded incomplete"
            action = (
                "Check whether abstention is expected for this case. If it is, "
                "review the General Quality grading behavior before changing "
                "the agent."
            )
        elif completeness.casefold() == "no":
            category = "Incomplete response"
            action = (
                "Add the missing user-facing information while preserving the "
                "expected behavior."
            )
        else:
            category = "General Quality failure"
            action = "Review the General Quality dimensions for this response."
        evidence = (
            f"General Quality: abstention={abstention}, "
            f"completeness={completeness}."
        )
        if compare_reason:
            evidence = f"{evidence} CompareMeaning: {compare_reason}"
        return {
            "category": category,
            "suggestedAction": action,
            "evidence": evidence,
        }

    return {
        "category": "Execution or metric failure",
        "suggestedAction": "Inspect the returned case state and metric errors.",
        "evidence": str(case.get("state") or "Unknown case state"),
    }


def analyze_run_results(result: dict[str, Any]) -> dict[str, Any]:
    """Build deterministic summary and failure-group data for presentation."""
    cases = result.get("testCasesResults")
    cases = [
        case for case in cases
        if isinstance(case, dict)
    ] if isinstance(cases, list) else []
    passed = []
    failed = []
    for case in cases:
        (passed if _case_passed(case) else failed).append(case)
    total = len(cases)
    pass_rate = round((len(passed) / total) * 100, 1) if total else 0.0

    groups: dict[str, dict[str, Any]] = {}
    for case in failed:
        pattern = _failure_pattern(case)
        group = groups.setdefault(pattern["category"], {
            "category": pattern["category"],
            "cases": [],
            "owner": "Unassigned",
            "suggestedAction": pattern["suggestedAction"],
            "representativeEvidence": pattern["evidence"],
        })
        group["cases"].append(
            case.get("testCaseName") or case.get("testCaseId")
        )

    failure_groups = []
    for group in groups.values():
        count = len(group.pop("cases"))
        failure_groups.append({
            **group,
            "caseCount": count,
            "failurePercentage": (
                round((count / len(failed)) * 100, 1) if failed else 0.0
            ),
        })
    failure_groups.sort(
        key=lambda item: (-item["caseCount"], item["category"])
    )

    test_set_name = str(
        result.get("testSetName")
        or result.get("testSetId")
        or "Evaluation set"
    )
    return {
        "summary": {
            "totalCases": total,
            "passedCases": len(passed),
            "failedCases": len(failed),
            "passRate": pass_rate,
        },
        "scenarioGroups": [{
            "group": test_set_name,
            "cases": total,
            "passed": len(passed),
            "failed": len(failed),
            "passRate": pass_rate,
        }],
        "failureGroups": failure_groups,
    }


def get_run_results(
    client: PowerPlatformClient,
    environment_id: str,
    bot_id: str,
    agent_folder: str | Path,
    run_id: str,
    studio_origin: str = DEFAULT_COPILOT_STUDIO_ORIGIN,
) -> dict[str, Any]:
    """Retrieve one run and enrich test case IDs with local case names."""
    result = client.get_maker_evaluation_test_run(
        environment_id,
        bot_id,
        run_id,
    )
    _raise_api_error(result, "retrieve evaluation run results")
    names = _case_names(Path(agent_folder))
    cases = result.get("testCasesResults")
    if isinstance(cases, list):
        result["testCasesResults"] = [
            {
                **case,
                "testCaseName": names.get(
                    str(case.get("testCaseId", "")),
                    str(case.get("testCaseId", "")) or "Unknown test case",
                ),
            }
            for case in cases
            if isinstance(case, dict)
        ]
    test_set_id = str(result.get("testSetId", ""))
    if not result.get("testSetName") and test_set_id:
        test_sets = client.list_maker_evaluation_test_sets(
            environment_id,
            bot_id,
        )
        _raise_api_error(test_sets, "list evaluation test sets")
        selected = next(
            (
                item for item in test_sets
                if str(item.get("id")) == test_set_id
            ),
            None,
        )
        if selected:
            result["testSetName"] = (
                selected.get("displayName") or test_set_id
            )
    result["analysis"] = analyze_run_results(result)
    result["agentStudioUrl"] = _agent_studio_url(
        studio_origin,
        str(environment_id or ""),
        str(bot_id or ""),
        test_set_id=test_set_id or None,
        run_id=str(run_id or "") or None,
    )
    return result


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def _check_native_run_review(
    config: dict[str, Any],
    selected: dict[str, Any],
) -> None:
    agent_folder = Path(str((config.get("agent") or {}).get("folder") or ""))
    map_path = agent_folder / ".component-map.json"
    local_folder = None
    if map_path.is_file():
        try:
            component_map = json.loads(map_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise EvaluationRunError(
                f"Unable to read agent component map {map_path}: {exc}"
            ) from exc
        if not isinstance(component_map, dict):
            raise EvaluationRunError(
                f"Agent component map must contain an object: {map_path}"
            )
        parent_paths = [
            agent_folder / relative_path
            for relative_path, metadata in component_map.items()
            if isinstance(metadata, dict)
            and metadata.get("componenttype") == 19
            and not metadata.get("parentbotcomponentid")
            and str(metadata.get("botcomponentid")) == str(selected["id"])
        ]
        if len(parent_paths) > 1:
            raise EvaluationRunError(
                "The deployed test set maps to more than one local parent."
            )
        if parent_paths:
            folder = parent_paths[0].parent
            local_folder = folder
            review_path = folder / REVIEW_FILENAME
            try:
                local_status = (
                    parse_review_metadata(review_path.read_text(encoding="utf-8"))["status"]
                    if review_path.is_file() else None
                )
            except (OSError, ReviewMetadataError) as exc:
                raise EvaluationRunError(
                    f"Unable to read evaluation review state {review_path}: {exc}"
                ) from exc
            if local_status == REVIEW_REQUESTED:
                raise EvaluationRunError(REVIEW_PENDING_GUIDANCE)
    if not selected.get("runnable", True):
        raise EvaluationRunError(
            selected.get("blockedReason") or "The selected test set is blocked from running."
        )
    if local_folder and any(local_folder.glob("*.mcs.yml")):
        _require_synchronized_local_set(local_folder, include_review=False)


def _start_native_run(
    client: MinimalBotEvaluationClient,
    args: argparse.Namespace,
    config: dict[str, Any],
) -> dict[str, Any]:
    selected = next(
        (
            item for item in client.list_test_sets()
            if str(item.get("id")) == args.test_set_id
            and str(item.get("state", "Active")).casefold() == "active"
        ),
        None,
    )
    if selected is None:
        raise EvaluationRunError(
            "The selected test set is not active or no longer exists."
        )
    _check_native_run_review(config, selected)
    if args.mcs_connection_id and not any(
        connection["id"] == args.mcs_connection_id
        for connection in list_native_mcs_connections(client)
    ):
        raise EvaluationRunError(
            "The selected Copilot Studio connection is missing or is not "
            "Connected. Choose a connected profile and retry."
        )
    result = client.run_test_set(
        args.test_set_id,
        run_name=args.run_name,
        run_on_published_bot=args.published,
        mcs_connection_id=args.mcs_connection_id,
    )
    run_id = result.get("runId")
    if not isinstance(run_id, str) or not run_id.strip():
        raise EvaluationRunError(
            "Power Platform API did not return an evaluation run ID."
        )
    result["userGuidance"] = RUN_WAIT_GUIDANCE
    test_set_id = str(result.get("testSetId") or "")
    result["agentStudioUrl"] = (
        _agent_studio_url(
            COPILOT_STUDIO_ORIGIN_BY_RING.get(
                client.ring, DEFAULT_COPILOT_STUDIO_ORIGIN,
            ),
            client.environment_id,
            client.bot_id,
            test_set_id=test_set_id,
            run_id=run_id,
            agent_backend=client.agent_backend,
        )
        if test_set_id else None
    )
    if not result["agentStudioUrl"]:
        result["navigationWarning"] = RUN_NAVIGATION_WARNING
    return result


def _start_dataverse_run(
    client: PowerPlatformClient,
    environment_id: str,
    bot_id: str,
    agent_folder: Path,
    args: argparse.Namespace,
    config: dict[str, Any],
) -> dict[str, Any]:
    test_sets = list_agent_test_sets(
        client, environment_id, bot_id, agent_folder, include_blocked=True,
    )
    selected = next(
        (item for item in test_sets if str(item.get("id")) == args.test_set_id),
        None,
    )
    if selected is None:
        raise EvaluationRunError(
            "The selected test set is not active or no longer exists."
        )
    if not selected.get("runnable", True):
        raise EvaluationRunError(
            selected.get("blockedReason")
            or "The selected test set is blocked from running."
        )
    connection = resolve_mcs_connection(
        config, environment_id, args.mcs_connection_id, client.signed_in_username,
    )
    tools_connections = resolve_tool_connections(
        config, environment_id, bot_id, client.signed_in_username,
    )
    return start_run(
        client, environment_id, bot_id, selected, connection["id"],
        run_name=args.run_name,
        run_on_published_bot=args.published,
        tools_connections=tools_connections,
        studio_origin=_studio_origin_for_config(config),
        config=config,
    )


def _prepared_run_command(args: argparse.Namespace, config: dict[str, Any]) -> int:
    from evaluation_deployment import SUCCESS_STATUSES, deploy_evaluation_set

    with redirect_stdout(sys.stderr):
        deployment = deploy_evaluation_set(
            args.set_folder, action="run", confirmation_token=args.confirmation_token,
            yes=args.yes, force_delete=args.force_delete, replace=args.replace,
            config=config,
        )
    if deployment.get("status") not in SUCCESS_STATUSES:
        _print_json({
            "status": deployment.get("status") or "failed",
            "stage": "deployment",
            "deployment": deployment,
            "error": deployment.get("error") or "Deployment was not verified; Run did not proceed.",
        })
        return 1
    try:
        sets = deployment.get("sets")
        if not isinstance(sets, list) or len(sets) != 1 or not isinstance(sets[0], dict):
            raise EvaluationRunError("Preparation must return exactly one verified deployed set.")
        selected = sets[0]
        test_set_id = selected.get("testSetId")
        if not isinstance(test_set_id, str) or not test_set_id.strip():
            raise EvaluationRunError("Preparation did not return a verified deployed set ID.")
        if Path(str(selected.get("sourceFolder") or "")).resolve() != Path(args.set_folder).resolve():
            raise EvaluationRunError("Preparation returned a different selected source folder.")
        agent_folder = Path(str((config.get("agent") or {}).get("folder") or "")).resolve()
        destination = Path(str(selected.get("agentSetFolder") or "")).resolve()
        expected_destination = agent_folder / "evaluations" / Path(args.set_folder).name
        if destination != expected_destination:
            raise EvaluationRunError(
                "Preparation returned a different selected set in the configured agent."
            )
        if deployment.get("action") != "run":
            raise EvaluationRunError("Preparation was not confirmed for the Run action.")
        run_args = argparse.Namespace(
            test_set_id=test_set_id,
            run_name=args.run_name,
            published=args.published,
            mcs_connection_id=args.mcs_connection_id,
        )
        with redirect_stdout(sys.stderr):
            if is_minimalbot(config):
                client = MinimalBotEvaluationClient.from_config(config)
                environment_id, bot_id = client.environment_id, client.bot_id
            else:
                client, environment_id, bot_id, _ = _runtime(config)
            if (
                deployment.get("environmentId") != environment_id
                or deployment.get("botId") != bot_id
                or deployment.get("backend") != (
                    "minimalbot" if is_minimalbot(config) else "dataverse"
                )
            ):
                raise EvaluationRunError(
                    "The verified deployment target differs from the run target."
                )
            if is_minimalbot(config):
                client.authenticate()
                result = _start_native_run(client, run_args, config)
            else:
                result = _start_dataverse_run(
                    client, environment_id, bot_id, agent_folder, run_args, config,
                )
        _print_json({**result, "deployment": deployment})
        return 0
    except (
        EvaluationRunError, MinimalBotEvaluationError, EvaluationMethodError,
        ReviewMetadataError, APIError, requests.RequestException,
    ) as exc:
        _print_json({
            "status": "run_failed",
            "stage": "run",
            "deployment": deployment,
            "error": str(exc),
            "userGuidance": (
                "Deployment reported success, but Run did not return a confirmed "
                "start. Check for an existing run before retrying execution; "
                "do not repeat deployment blindly."
            ),
        })
        return 1


def _minimalbot_command(args: argparse.Namespace, config: dict[str, Any]) -> int:
    """Handle evaluation subcommands for Dataverse-free MinimalBot agents.

    ``list-sets``, ``run``, ``list-runs``, and ``results`` are supported on the
    agent's ring (derived from ``powerPlatformApiEndpoint``). Run history and
    results use the standard Power Platform ``makerevaluation/testruns`` API
    (not the MinimalBot components API). ``list-connections`` exposes connected
    profiles through the native transport's existing discovery API.
    """
    client = MinimalBotEvaluationClient.from_config(config)
    client.authenticate()

    if args.command == "list-sets":
        sets = client.list_test_sets()
        if getattr(args, "include_local", False):
            _print_json(list_run_candidates(
                args.workspace_root,
                remote_sets=sets,
                query=args.query,
                native=True,
            ))
            return 0
        if getattr(args, "query", None):
            needle = _normalized_name(args.query)
            sets = [
                item for item in sets
                if needle in _normalized_name(item.get("displayName", ""))
            ]
        _print_json(sets)
        return 0
    if args.command == "run":
        _print_json(_start_native_run(client, args, config))
        return 0
    if args.command == "list-connections":
        _print_json(list_native_mcs_connections(client))
        return 0
    if args.command == "list-runs":
        _print_json(client.list_test_runs())
        return 0
    if args.command == "results":
        result = client.get_test_run(args.run_id)
        if isinstance(result, dict):
            result["agentStudioUrl"] = _agent_studio_url(
                COPILOT_STUDIO_ORIGIN_BY_RING.get(
                    client.ring, DEFAULT_COPILOT_STUDIO_ORIGIN,
                ),
                client.environment_id,
                client.bot_id,
                test_set_id=str(result.get("testSetId", "")) or None,
                run_id=str(args.run_id or "") or None,
                agent_backend=client.agent_backend,
            )
        _print_json(result)
        return 0
    raise MinimalBotEvaluationError(
        f"The '{args.command}' command is not supported for MinimalBot "
        "(Dataverse-free) agents. Use 'list-sets', 'list-connections', 'run', 'list-runs', or "
        "'results'."
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Copilot Studio evaluation test sets and get results."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_sets_parser = subparsers.add_parser("list-sets")
    list_sets_parser.add_argument("--query")
    list_sets_parser.add_argument(
        "--include-local", action="store_true",
        help="Include workspace/current-agent sets that can be prepared for Run.",
    )
    list_sets_parser.add_argument("--workspace-root", default="workspace")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--test-set-id", required=True)
    run_parser.add_argument("--test-set-name")
    run_parser.add_argument("--run-name")
    run_parser.add_argument("--published", action="store_true")
    run_parser.add_argument("--mcs-connection-id")

    prepared_parser = subparsers.add_parser("run-prepared")
    prepared_parser.add_argument("--set-folder", required=True)
    prepared_parser.add_argument("--confirmation-token", required=True)
    prepared_parser.add_argument("--yes", action="store_true")
    prepared_parser.add_argument("--replace", action="store_true")
    prepared_parser.add_argument("--force-delete", action="store_true")
    prepared_parser.add_argument("--run-name")
    prepared_parser.add_argument("--published", action="store_true")
    prepared_parser.add_argument("--mcs-connection-id", required=True)

    subparsers.add_parser("list-connections")
    subparsers.add_parser("list-runs")

    results_parser = subparsers.add_parser("results")
    results_parser.add_argument("--run-id", required=True)

    args = parser.parse_args()
    try:
        if (
            args.command == "list-sets"
            and args.include_local
            and not Path(".local/config.json").is_file()
        ):
            _print_json(list_run_candidates(
                args.workspace_root, query=args.query,
            ))
            return 0
        config = load_config()
        if args.command == "run-prepared":
            return _prepared_run_command(args, config)
        # Dataverse-free MinimalBot agents use the Power Platform MinimalBot
        # components API on their own ring instead of the Dataverse-backed path.
        if is_minimalbot(config):
            return _minimalbot_command(args, config)
        client, environment_id, bot_id, agent_folder = _runtime(config)
        if args.command == "list-sets":
            if args.include_local:
                _print_json(list_run_candidates(
                    args.workspace_root,
                    remote_sets=list_remote_test_sets(
                        client, environment_id, bot_id,
                    ),
                    query=args.query,
                ))
            else:
                _print_json(list_agent_test_sets(
                    client,
                    environment_id,
                    bot_id,
                    agent_folder,
                    args.query,
                    include_blocked=True,
                ))
        elif args.command == "run":
            _print_json(_start_dataverse_run(
                client, environment_id, bot_id, agent_folder, args, config,
            ))
        elif args.command == "list-connections":
            _print_json(list_mcs_connections(
                config,
                environment_id,
                client.signed_in_username,
            ))
        elif args.command == "list-runs":
            _print_json(list_runs(
                client,
                environment_id,
                bot_id,
            ))
        elif args.command == "results":
            _print_json(get_run_results(
                client,
                environment_id,
                bot_id,
                agent_folder,
                args.run_id,
                _studio_origin_for_config(config),
            ))
    except (
        EvaluationRunError, MinimalBotEvaluationError, EvaluationMethodError,
        ReviewMetadataError, APIError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
