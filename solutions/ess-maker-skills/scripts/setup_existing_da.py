# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Attach an existing editable DA Dev agent without using Dataverse."""

from __future__ import annotations

import argparse
import copy
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
    cached_account_names,
    canonical_json,
    derive_environment_host,
    list_environments,
    validate_environment_host,
)
from agentbuilder_object_model import (
    ObjectModelConverterError,
    object_models_to_yaml,
    validate_object_model_runtime,
)
from da_product_registry import (
    DAProductRegistryError,
    resolve_product_setup,
)


ATTACH_METADATA = ".agentbuilder/attach.json"
RAW_CHANGESET = ".agentbuilder/components.json"
CANONICAL_SETUP_STATE = Path(".local/setup/config.json")
CANONICAL_SETUP_SCHEMA_VERSION = 4
SETUP_INTENT = "DA foundation setup"
SETUP_STEP_ORDER = (
    "SETUP-01",
    "SETUP-02.1",
    "SETUP-02.2",
    "SETUP-03",
    "SETUP-04",
    "SETUP-05",
    "SETUP-06",
    "SETUP-07",
)
SETUP_STEP_NOTES = {
    "SETUP-01": (
        "Records locked environment identity, endpoint, and DA foundation "
        "setup intent."
    ),
    "SETUP-02.1": (
        "Native environment and exact editable-agent access verified by "
        "DA-AGENT-001."
    ),
    "SETUP-02.2": (
        "Copilot Studio message capacity verified by ENV-CAPACITY-001. "
        "Non-queryable governance prerequisites remain maker-owned."
    ),
    "SETUP-03": (
        "Confirms the environment and exact editable Dev agent."
    ),
    "SETUP-04": (
        "Preferred-solution configuration does not apply to the DA-only "
        "foundation path."
    ),
    "SETUP-05": (
        "The product registry declares whether a connection is required for "
        "foundation readiness."
    ),
    "SETUP-06": (
        "Exact native agent content footprint verified by DA-CONTENT-001."
    ),
    "SETUP-07": (
        "Confirms workspace materialization and that integration "
        "configuration can begin safely."
    ),
}
SETUP_FLIGHTCHECK_STEPS = {
    "DA-AGENT-001": "SETUP-02.1",
    "ENV-CAPACITY-001": "SETUP-02.2",
    "DA-CONTENT-001": "SETUP-06",
}
SETUP_PERMANENTLY_SKIPPED_STEPS = {"SETUP-04"}
SUPPORTED_SETUP_SOURCES = {
    "existing-dev",
    "alm-import",
    "prod-to-dev",
    "mos-starter",
}
PROJECTION_ENGINE = "microsoft-agents-objectmodel"
WORKSPACE_PROJECTION_VERSION = 2
SETUP_SOURCE_PRIORITY = {
    "existing-dev": 0,
    "alm-import": 1,
    "prod-to-dev": 2,
    "mos-starter": 3,
}
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


def _print_exception(error: BaseException) -> None:
    print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
    for note in getattr(error, "__notes__", ()):
        print(f"NOTE: {note}", file=sys.stderr)


def _find_http_error(
    error: BaseException,
) -> AgentBuilderHTTPError | None:
    current: BaseException | None = error
    seen: set[int] = set()
    while (
        current is not None
        and id(current) not in seen
        and not isinstance(current, AgentBuilderHTTPError)
    ):
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return current if isinstance(current, AgentBuilderHTTPError) else None


def _print_http_error_response(
    error: BaseException,
    *,
    marker: str,
) -> None:
    current = _find_http_error(error)
    if (
        current is None
        or current.response is None
    ):
        return
    try:
        body = current.response.json()
    except ValueError:
        print(f"{marker}_RESPONSE_TEXT:{current.response.text}")
    else:
        print(
            f"{marker}_RESPONSE_JSON:"
            f"{json.dumps(body, ensure_ascii=True)}"
        )


def _require_object_model_dependencies() -> None:
    """Fail before remote setup when the local projection runtime is absent."""
    try:
        validate_object_model_runtime()
    except ObjectModelConverterError as exc:
        raise ExistingDASetupError(
            "Local Microsoft Object Model prerequisites failed before "
            f"authentication or remote agent validation: {exc}"
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


def _validate_setup_source(value: str) -> str:
    if value not in SUPPORTED_SETUP_SOURCES:
        raise ExistingDASetupError(
            f"Unsupported DA setup source: {value!r}."
        )
    return value


def _preferred_setup_source(existing: str, requested: str) -> str:
    """Preserve the strongest provenance for the same DA identity."""
    return max(
        (existing, requested),
        key=SETUP_SOURCE_PRIORITY.__getitem__,
    )


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
        "intent",
        "environment",
        "agents",
        "created_at",
        "updated_at",
    }
    if set(state) != required_fields:
        raise ExistingDASetupError(
            "This workspace contains setup state in an incompatible format. "
            "Nothing was changed. Use a separate workspace for DA setup."
        )
    if (
        state.get("schema_version") != CANONICAL_SETUP_SCHEMA_VERSION
        or state.get("intent") != SETUP_INTENT
    ):
        raise ExistingDASetupError(
            "This workspace contains setup state in an incompatible format. "
            "Nothing was changed. Use a separate workspace for DA setup."
        )
    environment = state.get("environment")
    if (
        not isinstance(environment, dict)
        or not isinstance(state.get("agents"), dict)
        or not state["agents"]
    ):
        raise ExistingDASetupError(
            "Canonical DA setup state is incomplete or malformed."
        )
    for agent_id, agent_state in state["agents"].items():
        _validate_canonical_agent_state(agent_id, agent_state)
    return state


def _validate_canonical_agent_state(
    agent_id: str,
    agent_state: Any,
) -> None:
    required_fields = {
        "setup_source",
        "agent",
        "workspace",
        "steps",
        "active_step",
        "connect_ready",
        "open_issues",
        "created_at",
        "updated_at",
        "completed_at",
    }
    if not isinstance(agent_state, dict) or set(agent_state) != required_fields:
        raise ExistingDASetupError(
            f"Canonical DA setup state for agent {agent_id} is malformed."
        )
    agent = agent_state.get("agent")
    workspace = agent_state.get("workspace")
    steps = agent_state.get("steps")
    if (
        agent_state.get("setup_source") not in SUPPORTED_SETUP_SOURCES
        or not isinstance(agent, dict)
        or str(agent.get("id") or "").casefold() != agent_id.casefold()
        or not isinstance(workspace, dict)
        or not isinstance(steps, dict)
        or set(steps) != set(SETUP_STEP_ORDER)
        or not isinstance(agent_state.get("open_issues"), list)
    ):
        raise ExistingDASetupError(
            f"Canonical DA setup state for agent {agent_id} is incomplete."
        )
    for step_id, record in steps.items():
        if not isinstance(record, dict):
            raise ExistingDASetupError(
                f"Canonical DA setup step {step_id} for agent {agent_id} "
                "is malformed."
            )
        if record.get("state") not in {
            "pending",
            "in-progress",
            "blocked",
            "done",
        }:
            raise ExistingDASetupError(
                f"Canonical DA setup step {step_id} has an invalid state."
            )
        if record.get("mode") not in {
            None,
            "automated",
            "manual-attested",
            "skipped",
        }:
            raise ExistingDASetupError(
                f"Canonical DA setup step {step_id} has an invalid mode."
            )
        if record.get("state") == "done" and (
            not record.get("note")
            or not record.get("mode")
            or not record.get("recorded_at")
        ):
            raise ExistingDASetupError(
                f"Canonical DA setup step {step_id} lacks completion evidence."
            )
        requirement = record.get("requirement")
        if requirement is not None and (
            step_id != "SETUP-05"
            or not isinstance(requirement, dict)
            or not isinstance(requirement.get("productKey"), str)
            or not isinstance(requirement.get("displayName"), str)
            or not str(requirement.get("connectorApiName") or "")
            .casefold()
            .startswith("shared_")
        ):
            raise ExistingDASetupError(
                f"Canonical DA setup step {step_id} has an invalid "
                "connection requirement."
            )
    expected_active = next(
        (
            step_id
            for step_id in SETUP_STEP_ORDER
            if steps[step_id].get("state") != "done"
        ),
        SETUP_STEP_ORDER[-1],
    )
    if agent_state.get("active_step") != expected_active:
        raise ExistingDASetupError(
            f"Canonical DA setup state for agent {agent_id} has an invalid "
            "active step."
        )
    connect_ready = agent_state.get("connect_ready")
    all_steps_done = all(
        steps[step_id].get("state") == "done"
        for step_id in SETUP_STEP_ORDER
    )
    if not isinstance(connect_ready, bool):
        raise ExistingDASetupError(
            f"Canonical DA setup state for agent {agent_id} has an invalid "
            "connect-ready marker."
        )
    if connect_ready != all_steps_done:
        raise ExistingDASetupError(
            "Canonical DA setup readiness does not match its step results."
        )
    if connect_ready:
        if (
            not agent_state.get("completed_at")
            or not workspace.get("folder")
            or not workspace.get("agent_path")
        ):
            raise ExistingDASetupError(
                f"Canonical DA setup state for agent {agent_id} claims "
                "readiness without complete step and workspace evidence."
            )
    else:
        if agent_state.get("completed_at") is not None:
            raise ExistingDASetupError(
                f"Incomplete canonical DA setup state for agent {agent_id} "
                "has a completion time."
            )


def _canonical_environment_matches_connection(
    state: dict[str, Any],
    connection: dict[str, Any],
) -> bool:
    environment = state["environment"]
    return (
        environment.get("id") == connection["environment"]["id"]
        and environment.get("tenant_id")
        == connection["environment"]["tenantId"]
        and environment.get("power_platform_api_endpoint")
        == connection["environment"]["powerPlatformApiEndpoint"]
        and environment.get("ring") == connection["environment"]["ring"]
        and environment.get("api_version")
        == connection["environment"]["apiVersion"]
    )


def _canonical_agent_matches_connection(
    agent_state: dict[str, Any],
    connection: dict[str, Any],
) -> bool:
    agent = agent_state["agent"]
    return (
        agent.get("id") == connection["agent"]["id"]
        and agent.get("schema_name") == connection["agent"]["schemaName"]
        and agent.get("realm") == connection["agent"]["realm"]
        and (
            not agent.get("alm_family_id")
            or not connection["agent"].get("almFamilyId")
            or agent.get("alm_family_id")
            == connection["agent"].get("almFamilyId")
        )
    )


def _step_record(
    state: str = "pending",
    *,
    mode: str | None = None,
    note: str | None = None,
    recorded_at: str | None = None,
    failure_causes: list[str] | None = None,
    checkpoint: str | None = None,
    requirement: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record = {
        "state": state,
        "updated_at": recorded_at,
        "failure_causes": failure_causes or [],
        "checkpoint": checkpoint,
        "note": note,
        "mode": mode,
        "recorded_at": recorded_at,
    }
    if requirement is not None:
        record["requirement"] = copy.deepcopy(requirement)
    return record


def _next_setup_step(steps: dict[str, dict[str, Any]]) -> str:
    return next(
        (
            step_id
            for step_id in SETUP_STEP_ORDER
            if steps[step_id]["state"] != "done"
        ),
        SETUP_STEP_ORDER[-1],
    )


def _remove_directory(path: Path, label: str) -> str | None:
    if not path.exists():
        return None
    try:
        shutil.rmtree(path)
    except OSError as exc:
        return f"{label} cleanup failed ({type(exc).__name__}: {exc})"
    return None


def _setup_connection_policy(
    connection: dict[str, Any],
) -> tuple[dict[str, Any] | None, bool]:
    try:
        product = resolve_product_setup(
            catalog_name=connection["agent"].get("name"),
            agent_schema_name=connection["agent"].get("schemaName"),
        )
    except DAProductRegistryError as exc:
        raise ExistingDASetupError(str(exc)) from exc
    if product is None:
        return None, False
    if product["requiredConnection"] is None:
        return None, True
    return (
        {
            "productKey": product["productKey"],
            "matchedBy": product["matchedBy"],
            **product["requiredConnection"],
        },
        True,
    )


def _setup_connection_step(
    requirement: dict[str, Any] | None,
    now: str,
    *,
    product_recognized: bool,
) -> dict[str, Any]:
    if requirement is None:
        note = (
            "The product registry declares no foundation connection "
            "requirement for this agent."
            if product_recognized
            else (
                "This agent's product identity is not registered in the "
                "product setup registry; no foundation connection "
                "requirement was applied."
            )
        )
        return _step_record(
            "done",
            mode="skipped",
            note=note,
            recorded_at=now,
        )
    return _step_record(
        recorded_at=now,
        checkpoint="DA-CONN-*",
        requirement=requirement,
    )


def _setup_steps_in_progress(
    now: str,
    connection_requirement: dict[str, Any] | None,
    *,
    product_recognized: bool,
) -> dict[str, dict[str, Any]]:
    steps = {
        step_id: _step_record()
        for step_id in SETUP_STEP_ORDER
    }
    for step_id in ("SETUP-01", "SETUP-03"):
        steps[step_id] = _step_record(
            "done",
            mode="automated",
            note=SETUP_STEP_NOTES[step_id],
            recorded_at=now,
        )
    for step_id in SETUP_FLIGHTCHECK_STEPS.values():
        steps[step_id] = _step_record(
            "done",
            mode="skipped",
            note=(
                "Native FlightCheck maintenance starts after workspace "
                "materialization."
            ),
            recorded_at=now,
        )
    for step_id in sorted(SETUP_PERMANENTLY_SKIPPED_STEPS):
        steps[step_id] = _step_record(
            "done",
            mode="skipped",
            note=SETUP_STEP_NOTES[step_id],
            recorded_at=now,
        )
    steps["SETUP-05"] = _setup_connection_step(
        connection_requirement,
        now,
        product_recognized=product_recognized,
    )
    steps["SETUP-07"] = _step_record(
        "in-progress",
        recorded_at=now,
    )
    return steps


def _begin_flightcheck_maintenance(
    steps: dict[str, dict[str, Any]],
    now: str,
    connection_requirement: dict[str, Any] | None,
    *,
    product_recognized: bool,
) -> None:
    """Require fresh setup-owned FlightCheck evidence after every attachment."""
    for step_id in SETUP_FLIGHTCHECK_STEPS.values():
        steps[step_id] = _step_record(recorded_at=now)
    steps["SETUP-05"] = _setup_connection_step(
        connection_requirement,
        now,
        product_recognized=product_recognized,
    )


def _build_canonical_setup_progress(
    connection: dict[str, Any],
    existing: dict[str, Any] | None,
    *,
    reopen_flightchecks: bool,
) -> dict[str, Any]:
    now = _utc_now()
    connection_requirement, product_recognized = _setup_connection_policy(
        connection
    )
    steps = (
        copy.deepcopy(existing["steps"])
        if existing
        else _setup_steps_in_progress(
            now,
            connection_requirement,
            product_recognized=product_recognized,
        )
    )
    if reopen_flightchecks:
        _begin_flightcheck_maintenance(
            steps,
            now,
            connection_requirement,
            product_recognized=product_recognized,
        )
    if all(
        steps[step_id]["state"] == "done"
        for step_id in SETUP_STEP_ORDER[:-1]
    ):
        steps["SETUP-07"] = _step_record(
            "in-progress",
            recorded_at=now,
        )
    return {
        "setup_source": (
            existing["setup_source"]
            if existing
            else connection["setupSource"]
        ),
        "agent": {
            "id": connection["agent"]["id"],
            "name": connection["agent"]["name"],
            "schema_name": connection["agent"]["schemaName"],
            "realm": connection["agent"]["realm"],
            "alm_family_id": connection["agent"].get("almFamilyId"),
            "workspace_slug": connection["agent"]["workspaceSlug"],
        },
        "workspace": existing.get("workspace", {}) if existing else {},
        "steps": steps,
        "active_step": _next_setup_step(steps),
        "connect_ready": False,
        "open_issues": list(existing.get("open_issues", [])) if existing else [],
        "created_at": existing.get("created_at", now) if existing else now,
        "updated_at": now,
        "completed_at": None,
    }


def _new_canonical_setup_state(
    connection: dict[str, Any],
) -> dict[str, Any]:
    now = _utc_now()
    return {
        "schema_version": CANONICAL_SETUP_SCHEMA_VERSION,
        "intent": SETUP_INTENT,
        "environment": {
            "id": connection["environment"]["id"],
            "tenant_id": connection["environment"]["tenantId"],
            "power_platform_api_endpoint": connection["environment"][
                "powerPlatformApiEndpoint"
            ],
            "ring": connection["environment"]["ring"],
            "api_version": connection["environment"]["apiVersion"],
        },
        "agents": {},
        "created_at": now,
        "updated_at": now,
    }


def _store_canonical_agent_state(
    kit_root: Path,
    state: dict[str, Any] | None,
    connection: dict[str, Any],
    agent_state: dict[str, Any],
) -> dict[str, Any]:
    updated = copy.deepcopy(state) if state is not None else (
        _new_canonical_setup_state(connection)
    )
    if not _canonical_environment_matches_connection(updated, connection):
        raise ExistingDASetupError(
            "This workspace already targets another Power Platform "
            "environment. Create and open a new workspace for that environment."
        )
    updated["agents"][connection["agent"]["id"]] = agent_state
    updated["updated_at"] = _utc_now()
    _write_json(kit_root / CANONICAL_SETUP_STATE, updated)
    return updated


def _matching_flightcheck_rows(
    checkpoint: str,
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if checkpoint.endswith("*"):
        prefix = checkpoint[:-1]
        return [
            row
            for row in results
            if str(row.get("checkpoint_id") or "").startswith(prefix)
        ]
    return [
        row
        for row in results
        if row.get("checkpoint_id") == checkpoint
    ]


def maintain_setup_flightcheck(
    kit_root: Path,
    *,
    agent_id: str,
    checkpoint: str,
    results_path: Path,
    manual_attested: bool = False,
) -> dict[str, Any]:
    """Persist one supported FlightCheck result into canonical setup state."""
    state = _load_canonical_setup_state(kit_root)
    if state is None:
        raise ExistingDASetupError(
            "Canonical DA setup state is unavailable. Attach the agent first."
        )
    normalized_agent_id = _normalize_guid(agent_id, "Agent ID")
    agent_state = state["agents"].get(normalized_agent_id)
    if agent_state is None:
        raise ExistingDASetupError(
            "Canonical DA setup state does not contain the requested agent."
        )
    requirement: dict[str, Any] | None = None
    if checkpoint == "DA-CONN-*":
        step_id = "SETUP-05"
        candidate = agent_state["steps"][step_id].get("requirement")
        if not isinstance(candidate, dict):
            raise ExistingDASetupError(
                "This agent has no registry-declared setup connection "
                "requirement."
            )
        requirement = candidate
    else:
        step_id = SETUP_FLIGHTCHECK_STEPS.get(checkpoint)
        if step_id is None:
            raise ExistingDASetupError(
                f"Unsupported setup FlightCheck checkpoint: {checkpoint}"
            )
    try:
        payload = _load_json(results_path)
    except (OSError, ValueError) as exc:
        raise ExistingDASetupError(
            "FlightCheck results could not be read."
        ) from exc
    if not isinstance(payload, dict):
        raise ExistingDASetupError(
            "FlightCheck results have an invalid document shape."
        )
    if payload.get("scope") != f"checkpoint:{checkpoint}":
        raise ExistingDASetupError(
            f"FlightCheck results do not belong to {checkpoint}."
        )
    step_updated_at = agent_state["steps"][step_id].get("updated_at")
    if not isinstance(step_updated_at, str):
        raise ExistingDASetupError(
            f"Setup step {step_id} is not ready for FlightCheck maintenance."
        )
    try:
        step_started = datetime.fromisoformat(step_updated_at).timestamp()
        results_modified = results_path.stat().st_mtime
    except (OSError, ValueError) as exc:
        raise ExistingDASetupError(
            "FlightCheck result freshness could not be verified."
        ) from exc
    if results_modified < step_started:
        raise ExistingDASetupError(
            "FlightCheck results predate the current setup maintenance run."
        )
    rows = payload.get("results")
    if not isinstance(rows, list) or not all(
        isinstance(row, dict) for row in rows
    ):
        raise ExistingDASetupError(
            "FlightCheck results have an invalid result-row shape."
        )
    if requirement is not None:
        description = (
            "Native connection reference: "
            f"{requirement['connectorApiName']}"
        )
        matching = [
            row
            for row in rows
            if str(row.get("description") or "").casefold()
            == description.casefold()
        ]
    else:
        matching = _matching_flightcheck_rows(checkpoint, rows)
    if not matching and requirement is None:
        raise ExistingDASetupError(
            f"FlightCheck results contain no rows for {checkpoint}."
        )

    statuses = {
        str(row.get("status") or "")
        for row in matching
    }
    if manual_attested:
        if checkpoint != "ENV-CAPACITY-001":
            raise ExistingDASetupError(
                "Manual attestation is supported only for "
                "ENV-CAPACITY-001."
            )
        if (
            len(matching) != 1
            or statuses != {"Manual"}
            or payload.get("failed") != 0
            or payload.get("errors") != 0
        ):
            raise ExistingDASetupError(
                "Manual attestation requires a current Manual "
                "ENV-CAPACITY-001 result."
            )
        complete = True
    elif requirement is not None:
        complete = bool(statuses) and statuses <= {"Passed", "Warning"}
    else:
        run_blocked = (
            payload.get("failed") != 0
            or payload.get("errors") != 0
        )
        complete = not run_blocked and statuses == {"Passed"}

    now = _utc_now()
    if complete:
        note = SETUP_STEP_NOTES[step_id]
        mode = "automated"
        if manual_attested:
            mode = "manual-attested"
            note = (
                "A maker explicitly confirmed that Copilot Studio message "
                "capacity is allocated to this environment after the "
                "Licensing API result required manual verification."
            )
        if requirement is not None:
            note = (
                f"{requirement['displayName']} satisfies the "
                "registry-declared setup requirement."
            )
        agent_state["steps"][step_id] = _step_record(
            "done",
            mode=mode,
            note=note,
            recorded_at=now,
            checkpoint=checkpoint,
            requirement=requirement,
        )
    else:
        causes = (
            [
                str(
                    row.get("result")
                    or row.get("status")
                    or "FlightCheck failed"
                )
                for row in matching
                if str(row.get("status") or "") not in {"Passed", "Warning"}
            ]
            if matching
            else [
                "The required connection result was not returned by "
                "FlightCheck."
            ]
        )
        agent_state["steps"][step_id] = _step_record(
            "blocked",
            recorded_at=now,
            failure_causes=causes,
            checkpoint=checkpoint,
            requirement=requirement,
        )

    agent_state["active_step"] = _next_setup_step(agent_state["steps"])
    agent_state["connect_ready"] = all(
        agent_state["steps"][candidate]["state"] == "done"
        for candidate in SETUP_STEP_ORDER
    )
    agent_state["updated_at"] = now
    agent_state["completed_at"] = now if agent_state["connect_ready"] else None
    state["updated_at"] = now
    _write_json(kit_root / CANONICAL_SETUP_STATE, state)
    return {
        "agentId": normalized_agent_id,
        "checkpoint": checkpoint,
        "step": step_id,
        "state": agent_state["steps"][step_id]["state"],
        "evidenceStatuses": sorted(statuses),
        "failureCauses": list(
            agent_state["steps"][step_id].get("failure_causes", [])
        ),
        "mode": agent_state["steps"][step_id].get("mode"),
        "connectReady": agent_state["connect_ready"],
        "activeStep": agent_state["active_step"],
    }


def _record_canonical_setup_progress(
    kit_root: Path,
    connection: dict[str, Any],
    state: dict[str, Any] | None,
    existing: dict[str, Any] | None,
) -> dict[str, Any]:
    agent_state = _build_canonical_setup_progress(
        connection,
        existing,
        reopen_flightchecks=False,
    )
    _store_canonical_agent_state(
        kit_root,
        state,
        connection,
        agent_state,
    )
    return agent_state


def _record_canonical_setup_blocked(
    kit_root: Path,
    agent_id: str,
    error: Exception,
    *,
    secondary_failures: list[str] | None = None,
) -> None:
    state = _load_canonical_setup_state(kit_root)
    agent_state = state["agents"].get(agent_id) if state is not None else None
    if agent_state is None or agent_state["connect_ready"]:
        return
    now = _utc_now()
    failure_causes = [f"{type(error).__name__}: {error}"]
    failure_causes.extend(secondary_failures or [])
    agent_state["steps"]["SETUP-07"] = _step_record(
        "blocked",
        failure_causes=failure_causes,
        recorded_at=now,
    )
    agent_state["active_step"] = _next_setup_step(agent_state["steps"])
    agent_state["connect_ready"] = False
    agent_state["updated_at"] = now
    agent_state["completed_at"] = None
    state["updated_at"] = now
    _write_json(kit_root / CANONICAL_SETUP_STATE, state)


def _preserve_secondary_failures(
    error: Exception,
    failures: list[str],
) -> None:
    for failure in failures:
        print(f"WARNING: {failure}", file=sys.stderr)
        error.add_note(f"Secondary failure: {failure}")


def _try_record_canonical_setup_blocked(
    kit_root: Path,
    agent_id: str,
    error: Exception,
    *,
    secondary_failures: list[str] | None = None,
) -> None:
    try:
        _record_canonical_setup_blocked(
            kit_root,
            agent_id,
            error,
            secondary_failures=secondary_failures,
        )
    except Exception as persistence_error:
        _preserve_secondary_failures(
            error,
            [
                "Canonical blocked-state persistence failed "
                f"({type(persistence_error).__name__}: {persistence_error})"
            ],
        )


def _record_canonical_setup_ready(
    kit_root: Path,
    connection: dict[str, Any],
    workspace: dict[str, Any],
) -> dict[str, Any]:
    """Record the completed setup after the workspace is materialized."""
    existing = _load_canonical_setup_state(kit_root)
    if existing is not None and not _canonical_environment_matches_connection(
        existing, connection
    ):
        raise ExistingDASetupError(
            "Canonical setup state identifies a different environment. "
            "Create and open a new workspace before changing environments."
        )
    existing_agent = (
        existing["agents"].get(connection["agent"]["id"])
        if existing is not None
        else None
    )
    if existing_agent is not None and not _canonical_agent_matches_connection(
        existing_agent, connection
    ):
        raise ExistingDASetupError(
            "Canonical setup state contains conflicting identity for this agent."
        )
    agent_state = _build_canonical_setup_progress(
        connection,
        existing_agent,
        reopen_flightchecks=True,
    )
    now = _utc_now()
    agent_state["workspace"] = {
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
    }
    agent_state["steps"]["SETUP-07"] = _step_record(
        "done",
        mode="automated",
        note=SETUP_STEP_NOTES["SETUP-07"],
        recorded_at=now,
    )
    agent_state["connect_ready"] = all(
        agent_state["steps"][step_id]["state"] == "done"
        for step_id in SETUP_STEP_ORDER
    )
    agent_state["active_step"] = _next_setup_step(agent_state["steps"])
    agent_state["updated_at"] = now
    if agent_state["connect_ready"]:
        agent_state["completed_at"] = (
            existing_agent["completed_at"]
            if existing_agent is not None
            and existing_agent["connect_ready"]
            and existing_agent["completed_at"]
            else now
        )
    else:
        agent_state["completed_at"] = None
    _store_canonical_agent_state(
        kit_root,
        existing,
        connection,
        agent_state,
    )
    return agent_state


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
        except ExistingDASetupError as exc:
            print(
                f"WARNING: Listed agent ID {agent_id!r}: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            unverified += 1
            continue
        try:
            metadata = client.get_agent(normalized_agent_id)
        except AgentBuilderHTTPError as exc:
            if exc.status_code not in (403, 404):
                raise
            print(
                f"WARNING: Agent {normalized_agent_id}: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            _print_http_error_response(
                exc,
                marker="DA_AGENT_LIST_WARNING",
            )
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


def _confirm_dev_route(
    agent_id: str,
    agent: dict[str, Any],
    realms: dict[str, Any],
    *,
    expected_schema_name: str | None,
    allow_missing_schema: bool = False,
) -> str | None:
    route_realm = realms.get("routeRealm")
    if route_realm not in (0, "dev", "Dev"):
        raise ExistingDASetupError(
            f"Agent realm discovery returned realm {route_realm!r}."
        )
    returned_id = _normalize_guid(
        str(
            agent.get("botId")
            or agent.get("cdsBotId")
            or agent.get("componentIdUnique")
            or ""
        ),
        "Direct agent ID",
    )
    if returned_id.casefold() != agent_id.casefold():
        raise ExistingDASetupError(
            "Direct agent lookup returned a different agent identity."
        )
    card_realm = agent.get("realm")
    if card_realm not in (None, 0, "dev", "Dev"):
        raise ExistingDASetupError(
            f"Direct agent lookup identified a non-Dev realm: {card_realm!r}."
        )
    expected_schema = str(expected_schema_name or "").strip()
    schema_name = str(agent.get("schemaName") or expected_schema).strip()
    if not schema_name:
        if allow_missing_schema:
            return None
        raise ExistingDASetupError(
            "Direct agent lookup did not return a schema name."
        )
    if (
        expected_schema
        and schema_name.casefold() != expected_schema.casefold()
    ):
        raise ExistingDASetupError(
            "Direct agent lookup returned a different schema name."
        )
    return schema_name


def validate_existing_dev_connection(
    client: AgentBuilderClient,
    *,
    environment_id: str,
    agent_id: str,
    selection_source: str | None = None,
    setup_source: str = "existing-dev",
    require_alm_family: bool = True,
    expected_schema_name: str | None = None,
    allow_missing_schema: bool = False,
) -> dict[str, Any]:
    """Validate a directly addressable agent as editable Dev identity."""
    normalized_setup_source = _validate_setup_source(setup_source)
    normalized_environment_id = _normalize_environment_id(environment_id)
    normalized_agent_id = _normalize_guid(agent_id, "Agent ID")
    agent = client.get_agent(normalized_agent_id)
    if require_alm_family:
        configuration = client.get_dev_configuration(normalized_agent_id)
        schema_name, family_id = _confirm_dev(
            normalized_agent_id,
            agent,
            configuration,
        )
        expected_schema = str(expected_schema_name or "").strip()
        if (
            expected_schema
            and schema_name.casefold() != expected_schema.casefold()
        ):
            raise ExistingDASetupError(
                "Explicit Dev configuration returned a different schema name."
            )
    else:
        realms = client.get_realms(normalized_agent_id)
        schema_name = _confirm_dev_route(
            normalized_agent_id,
            agent,
            realms,
            expected_schema_name=expected_schema_name,
            allow_missing_schema=allow_missing_schema,
        )
        family_id = None
    agent_name = str(
        agent.get("fullBotName")
        or agent.get("displayName")
        or agent.get("shortBotName")
        or schema_name
        or normalized_agent_id
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
        "setupSource": normalized_setup_source,
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
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return workspace and agent state after enforcing one environment."""
    canonical_state = _load_canonical_setup_state(kit_root)
    if canonical_state is None:
        operational = _load_config(kit_root / ".local" / "config.json")
        recorded_environment = str(operational.get("environmentId") or "")
        if (
            recorded_environment
            and recorded_environment.casefold()
            != connection["environment"]["id"].casefold()
        ):
            raise ExistingDASetupError(
                "This workspace already targets another Power Platform "
                "environment. Create and open a new workspace for that "
                "environment."
            )
        return None, None
    if not _canonical_environment_matches_connection(
        canonical_state,
        connection,
    ):
        raise ExistingDASetupError(
            "This workspace already targets another Power Platform "
            "environment. Create and open a new workspace for that environment."
        )
    agent_state = canonical_state["agents"].get(connection["agent"]["id"])
    if agent_state is not None and not _canonical_agent_matches_connection(
        agent_state,
        connection,
    ):
        raise ExistingDASetupError(
            "This workspace contains conflicting identity for the requested "
            "agent."
        )
    return canonical_state, agent_state


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
    *,
    expected_schema_name: str | None = None,
) -> str:
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
    fetched_schema = str(bot.get("schemaName") or "").strip()
    if not fetched_schema:
        raise ExistingDASetupError(
            "Component fetch did not return a schema name."
        )
    expected_schema = str(expected_schema_name or "").strip()
    if (
        expected_schema
        and fetched_schema.casefold() != expected_schema.casefold()
    ):
        raise ExistingDASetupError(
            "Component fetch returned content for a different schema."
        )
    return fetched_schema


def _materialize_workspace(
    changeset: dict[str, Any],
    destination: Path,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    Counter[str],
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
    )


def _write_snapshot(
    destination: Path,
    *,
    agent_name: str,
    schema_name: str,
    topics: list[dict[str, Any]],
    variable_count: int,
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
        "- Source: AgentBuilder MinimalBot",
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
    ring: str,
    api_version: str,
    component_counts: Counter[str],
) -> None:
    existing = _load_config(config_path)
    existing.pop("transport", None)
    agents = existing.get("agents", [])
    if not isinstance(agents, list):
        raise ExistingDASetupError(
            "Existing local config contains a malformed agents list."
        )
    agents = [
        {
            key: value
            for key, value in item.items()
            if key != "transport"
        }
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
        "environmentId": environment_id,
        "powerPlatformApiEndpoint": host,
        "ring": ring,
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


def _workspace_slug_for_connection(
    kit_root: Path,
    connection: dict[str, Any],
    canonical_state: dict[str, Any] | None,
    existing_agent_state: dict[str, Any] | None,
) -> str:
    if existing_agent_state is not None:
        return str(existing_agent_state["agent"]["workspace_slug"])

    agent_id = connection["agent"]["id"]
    config = _load_config(kit_root / ".local" / "config.json")
    configured_agents = config.get("agents", [])
    if not isinstance(configured_agents, list):
        raise ExistingDASetupError(
            "Existing local config contains a malformed agents list."
        )
    for item in configured_agents:
        if (
            isinstance(item, dict)
            and str(item.get("botId") or "").casefold() == agent_id.casefold()
            and isinstance(item.get("slug"), str)
            and item["slug"]
        ):
            return str(item["slug"])

    occupied = {
        str(item.get("slug"))
        for item in configured_agents
        if isinstance(item, dict) and item.get("slug")
    }
    if canonical_state is not None:
        occupied.update(
            str(item["agent"]["workspace_slug"])
            for item in canonical_state["agents"].values()
        )
    base = connection["agent"]["workspaceSlug"]
    if base not in occupied:
        return base
    suffix = agent_id.replace("-", "")[:8]
    candidate = f"{base}-{suffix}"
    if candidate not in occupied:
        return candidate
    raise ExistingDASetupError(
        "A different configured agent already uses the deterministic local "
        f"workspace folder {candidate}."
    )


def select_local_agent(
    kit_root: Path,
    *,
    agent_id: str,
) -> dict[str, Any]:
    """Select one configured local agent without remote operations."""
    normalized_agent_id = _normalize_guid(agent_id, "Agent ID")
    config_path = kit_root / ".local" / "config.json"
    config = _load_config(config_path)
    agents = config.get("agents")
    if not isinstance(agents, list):
        raise ExistingDASetupError(
            "Existing local config contains a malformed agents list."
        )
    selected = next(
        (
            item
            for item in agents
            if isinstance(item, dict)
            and str(item.get("botId") or "").casefold()
            == normalized_agent_id.casefold()
        ),
        None,
    )
    if selected is None:
        raise ExistingDASetupError(
            "The requested agent is not configured in this workspace."
        )
    slug = selected.get("slug")
    if not isinstance(slug, str) or not slug:
        raise ExistingDASetupError(
            "The requested agent does not have a valid local workspace folder."
        )
    updated = {
        **config,
        "agent": selected,
        "activeAgent": slug,
    }
    _write_json(config_path, updated)
    canonical = _load_canonical_setup_state(kit_root)
    setup_state = (
        canonical["agents"].get(normalized_agent_id)
        if canonical is not None
        else None
    )
    return {
        "agentId": normalized_agent_id,
        "agentName": str(selected.get("name") or normalized_agent_id),
        "activeAgent": slug,
        "workspaceFolder": selected.get("folder"),
        "connectReady": (
            setup_state.get("connect_ready")
            if isinstance(setup_state, dict)
            else None
        ),
        "activeStep": (
            setup_state.get("active_step")
            if isinstance(setup_state, dict)
            else None
        ),
    }


def attach_existing_dev(
    client: AgentBuilderClient,
    *,
    environment_id: str,
    agent_id: str,
    kit_root: Path,
    refresh: bool = False,
    selection_source: str | None = None,
    setup_source: str = "existing-dev",
    expected_schema_name: str | None = None,
) -> dict[str, Any]:
    """Resolve an existing Dev agent and materialize its local DA workspace."""
    connection = validate_existing_dev_connection(
        client,
        environment_id=environment_id,
        agent_id=agent_id,
        selection_source=selection_source,
        setup_source=setup_source,
        require_alm_family=False,
        expected_schema_name=expected_schema_name,
        allow_missing_schema=True,
    )
    normalized_environment_id = connection["environment"]["id"]
    normalized_agent_id = connection["agent"]["id"]
    prefetched_changeset: dict[str, Any] | None = None
    if not connection["agent"]["schemaName"]:
        prefetched_changeset = client.fetch_components(normalized_agent_id)
        connection["agent"]["schemaName"] = _validate_changeset_identity(
            prefetched_changeset,
            normalized_agent_id,
        )
    canonical_state, existing_setup = _validate_setup_target(
        kit_root,
        connection,
    )
    if existing_setup is not None:
        connection["setupSource"] = _preferred_setup_source(
            _validate_setup_source(str(existing_setup["setup_source"])),
            connection["setupSource"],
        )
        connection["agent"]["workspaceSlug"] = existing_setup["agent"][
            "workspace_slug"
        ]
        if (
            not connection["agent"].get("almFamilyId")
            and existing_setup["agent"].get("alm_family_id")
        ):
            connection["agent"]["almFamilyId"] = existing_setup["agent"][
                "alm_family_id"
            ]
    connection["agent"]["workspaceSlug"] = _workspace_slug_for_connection(
        kit_root,
        connection,
        canonical_state,
        existing_setup,
    )
    progress_recorded = (
        existing_setup is not None
        and existing_setup["connect_ready"] is False
    )
    if existing_setup is None or progress_recorded:
        _record_canonical_setup_progress(
            kit_root,
            connection,
            canonical_state,
            existing_setup,
        )
        progress_recorded = True
    schema_name = connection["agent"]["schemaName"]
    family_id = connection["agent"].get("almFamilyId")
    agent_name = connection["agent"]["name"]
    try:
        changeset = (
            prefetched_changeset
            if prefetched_changeset is not None
            else client.fetch_components(normalized_agent_id)
        )
        _validate_changeset_identity(
            changeset,
            normalized_agent_id,
            expected_schema_name=expected_schema_name or schema_name,
        )
    except Exception as exc:
        if progress_recorded:
            _try_record_canonical_setup_blocked(
                kit_root,
                normalized_agent_id,
                exc,
            )
        raise
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
    projected_entries: list[dict[str, Any]] = []
    cleanup_warnings: list[str] = []
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
            had_unprojected_dialogs = "unprojectedDialogs" in metadata
            metadata.pop("unprojectedDialogs", None)
            if (
                metadata.get("changesetSha256") != changeset_sha
                or metadata.get("selectedBy") != connection["selectedBy"]
                or had_unprojected_dialogs
                or metadata.get("setupSource")
                != connection["setupSource"]
            ):
                metadata = {
                    **metadata,
                    "changesetSha256": changeset_sha,
                    "selectedBy": connection["selectedBy"],
                    "setupSource": connection["setupSource"],
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
        if not progress_recorded:
            _record_canonical_setup_progress(
                kit_root,
                connection,
                canonical_state,
                existing_setup,
            )
            progress_recorded = True
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
                "setupSource": connection["setupSource"],
                "selectedBy": connection["selectedBy"],
                "changesetSha256": changeset_sha,
                "topicCount": len(topics),
                "topicPaths": sorted(entry["path"] for entry in topics),
                "agentPath": "agent.mcs.yml",
                "variableCount": len(variable_paths),
                "variablePaths": variable_paths,
                "componentCounts": dict(sorted(component_counts.items())),
            }
            _write_json(temporary / ATTACH_METADATA, metadata)
            _write_snapshot(
                temporary,
                agent_name=agent_name,
                schema_name=schema_name,
                topics=topics,
                variable_count=len(variable_paths),
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
                cleanup_failure = _remove_directory(
                    temporary,
                    "Temporary workspace",
                )
                if cleanup_failure:
                    cleanup_warnings.append(cleanup_failure)
                result = {
                    **metadata,
                    "checkpoint": checkpoint_number,
                }
            else:
                temporary.rename(destination)
                result = metadata
        except Exception as exc:
            secondary_failures: list[str] = []
            try:
                _write_json(
                    kit_root
                    / ".local"
                    / "setup"
                    / "agents"
                    / normalized_agent_id
                    / "projection-failure.json",
                    {
                        "environmentId": normalized_environment_id,
                        "agentId": normalized_agent_id,
                        "changesetSha256": changeset_sha,
                        "errorType": type(exc).__name__,
                        "message": str(exc),
                        "changeset": changeset,
                    },
                )
            except Exception as evidence_error:
                secondary_failures.append(
                    "Projection-failure evidence persistence failed "
                    f"({type(evidence_error).__name__}: {evidence_error})"
                )
            cleanup_failure = _remove_directory(
                temporary,
                "Temporary workspace",
            )
            if cleanup_failure:
                secondary_failures.append(cleanup_failure)
            _preserve_secondary_failures(exc, secondary_failures)
            _try_record_canonical_setup_blocked(
                kit_root,
                normalized_agent_id,
                exc,
                secondary_failures=secondary_failures,
            )
            raise

    agent_entry = {
        "name": agent_name,
        "botId": normalized_agent_id,
        "schemaName": schema_name,
        "isManaged": connection["agent"]["isManaged"],
        "slug": slug,
        "folder": destination.relative_to(kit_root).as_posix(),
        "releaseLine": "da",
        "environmentId": normalized_environment_id,
        "powerPlatformApiEndpoint": client.host,
        "realm": "dev",
        "almFamilyId": family_id,
        "setupSource": connection["setupSource"],
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
            ring=client.ring,
            api_version=client.api_version,
            component_counts=component_counts,
        )
    except Exception as exc:
        _preserve_secondary_failures(exc, cleanup_warnings)
        _try_record_canonical_setup_blocked(
            kit_root,
            normalized_agent_id,
            exc,
            secondary_failures=cleanup_warnings,
        )
        raise
    failure_evidence = (
        kit_root
        / ".local"
        / "setup"
        / "agents"
        / normalized_agent_id
        / "projection-failure.json"
    )
    if failure_evidence.exists():
        try:
            failure_evidence.unlink()
        except OSError as cleanup_error:
            cleanup_warnings.append(
                "Projection-failure evidence cleanup failed "
                f"({type(cleanup_error).__name__}: {cleanup_error})"
            )
    projected_kinds = {
        "DialogComponent",
        "GlobalVariableComponent",
        "GptComponent",
    }
    workspace = {
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
        "completedAt": _utc_now(),
    }
    canonical_agent = _record_canonical_setup_ready(
        kit_root,
        connection,
        workspace,
    )
    response = {
        **result,
        "connectionStatus": "workspace-ready",
        "workspace": workspace,
        "setupState": CANONICAL_SETUP_STATE.as_posix(),
        "connectReady": canonical_agent["connect_ready"],
    }
    if cleanup_warnings:
        response["cleanupWarnings"] = cleanup_warnings
    return response


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


def summarize_environments(
    environments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return stable maker-selection fields for visible environments."""
    choices: list[dict[str, Any]] = []
    for environment in environments:
        environment_id = _normalize_environment_id(
            str(environment.get("id") or "")
        )
        display_name = str(
            environment.get("displayName") or environment_id
        ).strip()
        choices.append(
            {
                "id": environment_id,
                "name": display_name or environment_id,
                "type": str(environment.get("type") or ""),
                "state": str(environment.get("state") or ""),
                "region": str(
                    environment.get("geo")
                    or environment.get("azureRegion")
                    or ""
                ),
            }
        )
    return sorted(
        choices,
        key=lambda item: (item["name"].casefold(), item["id"]),
    )


def write_environment_list_evidence(
    kit_root: Path,
    *,
    tenant_id: str,
    ring: str,
    environments: list[dict[str, Any]],
) -> Path:
    """Persist the complete service response outside the picker payload."""
    evidence_path = (
        kit_root.resolve()
        / ".local"
        / "setup"
        / f"environment-list-{ring}.json"
    )
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        json.dumps(
            {
                "tenantId": tenant_id,
                "ring": ring,
                "environments": environments,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return evidence_path


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
    parser.add_argument(
        "--account",
        help=(
            "Optional Microsoft account sign-in name used to access the target "
            "Power Platform environment. Reuse its cached AgentBuilder token "
            "when available or prefill Microsoft sign-in."
        ),
    )
    parser.add_argument("--host")
    parser.add_argument("--api-version", default=DEFAULT_API_VERSION)
    parser.add_argument("--kit-root", type=Path, default=Path.cwd())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    cached_accounts = commands.add_parser(
        "cached-accounts",
        help="List cached AgentBuilder sign-in names without authenticating.",
    )
    cached_accounts.add_argument("--kit-root", type=Path, default=Path.cwd())
    maintain_flightcheck = commands.add_parser(
        "maintain-flightcheck",
        help="Apply one native FlightCheck result to canonical setup state.",
    )
    maintain_flightcheck.add_argument(
        "--checkpoint",
        choices=(*SETUP_FLIGHTCHECK_STEPS, "DA-CONN-*"),
        required=True,
    )
    maintain_flightcheck.add_argument(
        "--agent-id",
        required=True,
        help="Exact configured agent whose setup evidence is maintained.",
    )
    maintain_flightcheck.add_argument(
        "--results",
        type=Path,
        required=True,
        help="Path to the FlightCheck results.json file.",
    )
    maintain_flightcheck.add_argument(
        "--manual-attested",
        action="store_true",
        help=(
            "Record an explicit maker attestation for a current Manual "
            "ENV-CAPACITY-001 result."
        ),
    )
    maintain_flightcheck.add_argument(
        "--kit-root",
        type=Path,
        default=Path.cwd(),
    )
    select_agent = commands.add_parser(
        "select-agent",
        help="Select one already configured local agent. No remote operations.",
    )
    select_agent.add_argument("--agent-id", required=True)
    select_agent.add_argument("--kit-root", type=Path, default=Path.cwd())
    list_environment_choices = commands.add_parser(
        "list-environments",
        help="List Power Platform environments visible to one account.",
    )
    list_environment_choices.add_argument(
        "--ring",
        choices=("prod", "preprod", "test"),
        required=True,
    )
    list_environment_choices.add_argument("--tenant-id")
    list_environment_choices.add_argument(
        "--select-account",
        action="store_true",
    )
    list_environment_choices.add_argument("--account")
    list_environment_choices.add_argument(
        "--api-version",
        default=DEFAULT_API_VERSION,
    )
    list_environment_choices.add_argument(
        "--kit-root",
        type=Path,
        default=Path.cwd(),
    )
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
    attach.add_argument(
        "--setup-source",
        choices=sorted(SUPPORTED_SETUP_SOURCES),
        default="existing-dev",
        help=argparse.SUPPRESS,
    )
    attach.add_argument("--expected-schema-name", help=argparse.SUPPRESS)
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
    account = getattr(args, "account", None)
    kit_root = args.kit_root.resolve()
    cache_path = kit_root / ".local" / ".agentbuilder_token_cache.bin"
    if args.tenant_id:
        token = authenticate(
            args.tenant_id,
            ring,
            cache_path=cache_path,
            force_account_selection=args.select_account,
            account_hint=account,
        )
        tenant_id = args.tenant_id
    else:
        token, tenant_id = authenticate_selected_tenant(
            ring,
            cache_path=cache_path,
            force_account_selection=args.select_account,
            account_hint=account,
        )
    return token, tenant_id


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "cached-accounts":
            cache_path = (
                args.kit_root.resolve()
                / ".local"
                / ".agentbuilder_token_cache.bin"
            )
            result = {"accounts": cached_account_names(cache_path)}
            print(
                "DA_AGENTBUILDER_ACCOUNTS_JSON:"
                f"{json.dumps(result, ensure_ascii=True)}"
            )
            return 0
        if args.command == "list-environments":
            token, tenant_id = _authentication_from_args(args, args.ring)
            environments = list_environments(
                token,
                args.ring,
                api_version=args.api_version,
            )
            evidence_path = write_environment_list_evidence(
                args.kit_root,
                tenant_id=tenant_id,
                ring=args.ring,
                environments=environments,
            )
            result = {
                "tenantId": tenant_id,
                "ring": args.ring,
                "environments": summarize_environments(environments),
                "evidencePath": str(evidence_path),
            }
            print(
                "DA_ENVIRONMENT_LIST_JSON:"
                f"{json.dumps(result, ensure_ascii=True)}"
            )
            return 0
        if args.command == "maintain-flightcheck":
            kit_root = args.kit_root.resolve()
            results_path = args.results
            if not results_path.is_absolute():
                results_path = kit_root / results_path
            result = maintain_setup_flightcheck(
                kit_root,
                agent_id=args.agent_id,
                checkpoint=args.checkpoint,
                results_path=results_path,
                manual_attested=args.manual_attested,
            )
            print(
                "DA_SETUP_FLIGHTCHECK_JSON:"
                f"{json.dumps(result, ensure_ascii=True)}"
            )
            return 0 if result["state"] == "done" else 1
        if args.command == "select-agent":
            result = select_local_agent(
                args.kit_root.resolve(),
                agent_id=args.agent_id,
            )
            print(
                "DA_ACTIVE_AGENT_JSON:"
                f"{json.dumps(result, ensure_ascii=True)}"
            )
            return 0
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
            selection_source=(
                "alm-import-result"
                if args.setup_source == "alm-import"
                else (
                    "prod-to-dev-result"
                    if args.setup_source == "prod-to-dev"
                    else (
                        "mos-starter-result"
                        if args.setup_source == "mos-starter"
                        else target.get("agentSelection")
                    )
                )
            ),
            setup_source=args.setup_source,
            expected_schema_name=args.expected_schema_name,
        )
    except (
        AgentBuilderError,
        ExistingDASetupError,
        OSError,
        ValueError,
    ) as exc:
        if args.command == "list-environments":
            http_error = _find_http_error(exc)
            if http_error is not None:
                error_result = {
                    "statusCode": http_error.status_code,
                    "errorCode": http_error.error_code,
                    "requestId": http_error.request_id,
                    "authorizationFailure": (
                        http_error.status_code in (401, 403)
                    ),
                }
                print(
                    "DA_ENVIRONMENT_LIST_ERROR_JSON:"
                    f"{json.dumps(error_result, ensure_ascii=True)}"
                )
        _print_http_error_response(
            exc,
            marker=(
                "DA_ENVIRONMENT_LIST_ERROR"
                if args.command == "list-environments"
                else "DA_EXISTING_DEV_ERROR"
            ),
        )
        _print_exception(exc)
        return 1
    print(f"DA_EXISTING_DEV_SETUP_JSON:{json.dumps(result, ensure_ascii=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
