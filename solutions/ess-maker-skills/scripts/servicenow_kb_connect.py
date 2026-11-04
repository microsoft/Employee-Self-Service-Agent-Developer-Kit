# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Dev-only, administrator-guided ServiceNow Knowledge connection lifecycle."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from flightcheck.agent_scope import active_agent, validate_agent_slug
from servicenow_kb_contracts import (
    COMMON_FIELDS,
    DENIED_READER_FIELDS,
    PROPERTY_ACCESS_UNRESOLVED,
    KnowledgeConnectError,
    configuration_steps,
    content_query,
    fields_for,
    guid,
    https_url,
    read_handoff,
    target_reference,
    validate_acceptance,
    validate_answer,
    validate_step_answer,
    write_handoff,
)
from workday_connect_workbook import WorkdayConnectWorkbookError

CONFIG_PATH = Path(".local") / "connect" / "servicenow-kb" / "config.json"
SUPPORTED_SCHEMAS = {
    "gptagent_copilotforemployeeselfservicehr",
    "gptagent_copilotforemployeeselfserviceit",
}
OWNERS = ("servicenow", "m365", "validation")


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise KnowledgeConnectError(
            f"Required JSON could not be read: {path.name}."
        ) from exc
    if not isinstance(value, dict):
        raise KnowledgeConnectError(f"{path.name}: expected a JSON object.")
    return value


def resolve_target(root: Path) -> dict[str, str]:
    config = read_json(root / ".local" / "config.json")
    slug = validate_agent_slug(config.get("activeAgent"))
    if not isinstance(config.get("agents", []), list):
        raise KnowledgeConnectError("Selected-agent configuration is malformed.")
    agent = active_agent(config, slug)
    schema = agent.get("schemaName")
    if (
        not isinstance(schema, str)
        or schema not in SUPPORTED_SCHEMAS
        or agent.get("releaseLine", config.get("releaseLine")) != "da"
    ):
        raise KnowledgeConnectError(
            "Select a native ESS HR or IT Development agent; no changes made."
        )
    bot_id = guid(agent.get("botId"), "Selected agent ID")
    setup = read_json(root / ".local" / "setup" / "config.json")
    if setup.get("schema_version") != 4 or not isinstance(setup.get("agents"), dict):
        raise KnowledgeConnectError(
            "Canonical workspace preparation is required; return to Setup."
        )
    candidates = [
        candidate
        for key, candidate in setup["agents"].items()
        if isinstance(key, str) and key.casefold() == bot_id
    ]
    if len(candidates) != 1 or not isinstance(candidates[0], dict):
        raise KnowledgeConnectError("Selected agent has no canonical workspace record.")
    candidate = candidates[0]
    identity = candidate.get("agent")
    if (
        not isinstance(identity, dict)
        or guid(identity.get("id"), "Canonical agent ID") != bot_id
        or identity.get("workspace_slug") != slug
        or identity.get("schema_name") != schema
    ):
        raise KnowledgeConnectError(
            "Selected and canonical agent identities do not match."
        )
    if str(identity.get("realm", "")).casefold() not in {"dev", "development"}:
        raise KnowledgeConnectError(
            "Only a confirmed Development realm is supported; no changes made."
        )
    if str(agent.get("realm", identity["realm"])).casefold() not in {
        "dev",
        "development",
    }:
        raise KnowledgeConnectError(
            "Selected target is not Development; no changes made."
        )
    steps = candidate.get("steps") or {}
    workspace = candidate.get("workspace") or {}
    if not isinstance(steps, dict) or not isinstance(workspace, dict):
        raise KnowledgeConnectError("Canonical workspace preparation is malformed.")
    workspace_step = steps.get("SETUP-07")
    if not isinstance(workspace_step, dict) or workspace_step.get("state") != "done":
        raise KnowledgeConnectError(
            "Prepare the selected agent workspace through Setup first."
        )
    folder_value, agent_value = workspace.get("folder"), workspace.get("agent_path")
    if (
        not isinstance(folder_value, str)
        or not folder_value
        or not isinstance(agent_value, str)
        or not agent_value
    ):
        raise KnowledgeConnectError("Canonical workspace paths are missing.")
    folder = (root / folder_value).resolve()
    agent_path = (folder / agent_value).resolve()
    if (
        not folder.is_relative_to(root)
        or not folder.is_dir()
        or not agent_path.is_relative_to(folder)
        or not agent_path.is_file()
    ):
        raise KnowledgeConnectError(
            "Selected workspace is missing or outside its canonical workspace folder."
        )
    environment = setup.get("environment")
    if not isinstance(environment, dict):
        raise KnowledgeConnectError("Canonical tenant/environment identity is missing.")
    env_id = guid(environment.get("id"), "Environment ID")
    tenant_id = guid(environment.get("tenant_id"), "Microsoft Entra tenant ID")
    foundation = config.get("foundation") or {}
    if not isinstance(foundation, dict):
        raise KnowledgeConnectError("Foundation target is malformed.")
    for value in (config.get("environmentId"), foundation.get("environmentId")):
        if value and guid(value, "Environment ID") != env_id:
            raise KnowledgeConnectError("Selected and canonical environments differ.")
    for value in (config.get("tenantId"), foundation.get("tenantId")):
        if value and guid(value, "Tenant ID") != tenant_id:
            raise KnowledgeConnectError("Selected and canonical tenants differ.")
    return {
        "agentId": bot_id,
        "slug": slug,
        "schemaName": schema,
        "environmentId": env_id,
        "tenantId": tenant_id,
        "realm": "dev",
    }


def values(state: dict[str, Any], owner: str) -> dict[str, str]:
    return state["evidence"].get(owner, {}).get("values", {})


def step_complete(state: dict[str, Any], step: dict[str, Any]) -> bool:
    if step["id"] == "property-reads":
        return values(state, "servicenow").get(step["field"]) in {
            "confirmed",
            "proceed-without-access",
        }
    if step["id"] == "connection-ready":
        return step["id"] in state.get("checkpoints", {}) and step["field"] in values(
            state, step["owner"]
        )
    if step["id"] == "permission-setup" and step["id"] not in state.get(
        "checkpoints", {}
    ):
        verified = {
            "Common table reads",
            "Permission property reads",
            "HR scoped reads",
        }
        if state["scope"]["flow"] == "simple":
            verified.add("Simple attribute reads")
        return verified <= values(state, "servicenow").keys()
    return step["field"] in values(state, step["owner"]) or step["id"] in state.get(
        "checkpoints", {}
    )


def next_step(state: dict[str, Any]) -> dict[str, Any] | None:
    return next(
        (
            step
            for step in configuration_steps(state["scope"])
            if not step_complete(state, step)
        ),
        None,
    )


def summary(state: dict[str, Any]) -> dict[str, Any]:
    warnings = []
    denied_skipped = any(
        state.get("checkpoints", {})
        .get(step["id"], {})
        .get("value", values(state, "validation").get(step["field"]))
        == "skipped"
        for step in configuration_steps(state["scope"])
        if step["field"] in DENIED_READER_FIELDS
    )
    if denied_skipped:
        warnings.append(
            {
                "step": "denied-reader",
                "status": "skipped",
                "message": "The optional, recommended denied-reader comparison was "
                "skipped. Denied-user source/index permission parity is not tested. "
                "Continuing setup or a successful ESS answer does not verify it.",
            }
        )
    property_access = values(state, "servicenow").get("Permission property reads")
    if property_access in PROPERTY_ACCESS_UNRESOLVED:
        warnings.append(
            {
                "step": "property-reads",
                "status": property_access,
                "continuationApproved": property_access == "proceed-without-access",
                "message": "Permission-property access remains unresolved. The connector "
                "needs to read glide.knowman.apply_article_read_criteria and "
                "glide.knowman.block_access_with_no_user_criteria from sys_properties. "
                "If unreadable, Microsoft documents defaults of true for both, which "
                "block articles without explicit user criteria from search results. "
                "No error is shown in the admin center. Consult your ServiceNow "
                "administrator to resolve access; do not change the property values. "
                "Continuing setup or passing representative reader tests does not "
                "verify this access.",
            }
        )
    for owner in ("servicenow", "m365"):
        missing = [
            field
            for field in fields_for(owner, state["scope"])
            if field not in values(state, owner)
        ]
        if missing:
            return {
                "status": "blocked" if state["issues"] else "in-progress",
                "nextMilestone": owner,
                "missingFields": missing,
                "targetReference": target_reference(state["scope"]),
                "warnings": warnings,
                "nextStep": next_step(state),
                "state": state,
            }
    pending = next_step(state)
    complete = (
        bool(values(state, "validation")) and not state["issues"] and pending is None
    )
    return {
        "status": "guided-complete-with-warnings"
        if complete and denied_skipped
        else "guided-validated"
        if complete
        else "blocked"
        if state["issues"]
        else "in-progress",
        "nextMilestone": pending["owner"] if pending else None,
        "targetReference": target_reference(state["scope"]),
        "warnings": warnings,
        "nextStep": pending,
        "state": state,
        "evidenceBoundary": "Recorded administrator confirmations and tested reader/article cases; "
        "skipped checks are not verified permission parity; "
        "not universal coverage, deployed employee readiness or a revocation SLA.",
    }


def validate_state(state: dict[str, Any]) -> None:
    version = state.get("schemaVersion")
    expected = {"schemaVersion", "scope", "evidence", "issues", "updatedAt"}
    if version == 2:
        expected.add("checkpoints")
    if set(state) != expected or type(version) is not int or version not in {1, 2}:
        raise KnowledgeConnectError(
            "Knowledge progress has an unsupported or malformed schema."
        )
    scope = state["scope"]
    if not isinstance(scope, dict) or set(scope) != {
        "target",
        "instance",
        "query",
        "flow",
        "hrContent",
    }:
        raise KnowledgeConnectError("Knowledge progress has malformed scope.")
    if (
        not isinstance(scope["flow"], str)
        or scope["flow"] not in {"simple", "advanced"}
        or (scope["hrContent"] is not None and type(scope["hrContent"]) is not bool)
    ):
        raise KnowledgeConnectError("Knowledge progress has invalid flow or HR scope.")
    https_url(scope["instance"], "Instance URL")
    content_query(scope["query"])
    target = scope["target"]
    if not isinstance(target, dict) or set(target) != {
        "agentId",
        "slug",
        "schemaName",
        "environmentId",
        "tenantId",
        "realm",
    }:
        raise KnowledgeConnectError("Knowledge progress has malformed target identity.")
    for key in ("agentId", "environmentId", "tenantId"):
        guid(target[key], key)
    validate_agent_slug(target["slug"])
    if (
        not isinstance(target["schemaName"], str)
        or target["schemaName"] not in SUPPORTED_SCHEMAS
        or target["realm"] != "dev"
    ):
        raise KnowledgeConnectError(
            "Knowledge progress is not for a supported native Dev target."
        )
    if not isinstance(state["evidence"], dict) or set(state["evidence"]) - set(OWNERS):
        raise KnowledgeConnectError("Knowledge progress has unsupported evidence.")
    if not isinstance(state["issues"], dict) or set(state["issues"]) - set(OWNERS):
        raise KnowledgeConnectError("Knowledge progress has malformed blockers.")
    m365 = state["evidence"].get("m365", {})
    legacy_connection = (
        isinstance(m365, dict)
        and isinstance(m365.get("values"), dict)
        and "Connection ID" in m365["values"]
        and "Connection name" not in m365["values"]
    )
    required_fields = {
        owner: set(
            fields_for(
                owner,
                scope,
                legacy_connection=owner == "m365" and legacy_connection,
            )
        )
        for owner in ("servicenow", "m365")
    }
    for owner, issues in state["issues"].items():
        allowed = (
            {"validation"} if owner == "validation" else set(fields_for(owner, scope))
        )
        if owner == "m365":
            allowed.add("Connection ID")
        if (
            not isinstance(issues, dict)
            or not issues
            or set(issues) - allowed
            or any(
                not isinstance(message, str) or len(message) > 2048
                for message in issues.values()
            )
        ):
            raise KnowledgeConnectError(
                "Knowledge progress has malformed blocker fields."
            )
    timestamps = [state["updatedAt"]]
    for owner, record in state["evidence"].items():
        if (
            not isinstance(record, dict)
            or set(record) != {"kind", "recordedAt", "values"}
            or record["kind"]
            != ("maker-tested" if owner == "validation" else "admin-confirmed")
            or not isinstance(record["values"], dict)
        ):
            raise KnowledgeConnectError(
                "Knowledge progress has malformed evidence provenance."
            )
        timestamps.append(record["recordedAt"])
        if owner == "validation":
            if any(
                field not in values(state, phase)
                for phase in ("servicenow", "m365")
                for field in required_fields[phase]
            ):
                raise KnowledgeConnectError(
                    "Validation cannot bypass incomplete administrator work."
                )
            legacy_connection = "connectionId" in record["values"]
            validate_acceptance(
                record["values"],
                scope,
                values(state, "m365").get(
                    "Connection ID" if legacy_connection else "Connection name"
                ),
                legacy_connection=legacy_connection,
            )
        else:
            allowed = set(fields_for(owner, scope))
            if owner == "m365":
                allowed.add("Connection ID")
            if set(record["values"]) - allowed:
                raise KnowledgeConnectError(
                    "Knowledge progress contains unsupported answer fields."
                )
            for label, value in record["values"].items():
                validate_answer(label, value, scope)
    steps = configuration_steps(scope)
    checkpoints = state.get("checkpoints", {})
    allowed_checkpoints = {step["id"]: step for step in steps if step["checkpoint"]}
    if not isinstance(checkpoints, dict) or set(checkpoints) - set(allowed_checkpoints):
        raise KnowledgeConnectError("Knowledge progress has unsupported checkpoints.")
    for step_id, checkpoint in checkpoints.items():
        step = allowed_checkpoints[step_id]
        if (
            not isinstance(checkpoint, dict)
            or set(checkpoint) != {"kind", "recordedAt", "value"}
            or checkpoint["kind"]
            != ("maker-tested" if step["owner"] == "validation" else "admin-confirmed")
        ):
            raise KnowledgeConnectError("Knowledge progress has malformed checkpoints.")
        validate_step_answer(step, checkpoint["value"], scope)
        recorded_value = values(state, step["owner"]).get(step["field"])
        if recorded_value is not None and recorded_value != checkpoint["value"]:
            raise KnowledgeConnectError(
                "Knowledge checkpoint contradicts its recorded milestone."
            )
        timestamps.append(checkpoint["recordedAt"])
        if any(
            not step_complete(state, previous)
            for previous in steps[: steps.index(step)]
            # Retain older observations without completing newly preceding gates.
            if not (
                (
                    previous["id"] == "connection-ready"
                    and values(state, "m365").get("Connection ready") == "confirmed"
                )
                or (
                    previous["id"] == "property-reads"
                    and values(state, "servicenow").get("Permission property reads")
                    in PROPERTY_ACCESS_UNRESOLVED
                )
                or (
                    previous["id"] == "connection-name"
                    and "Connection ID" in values(state, "m365")
                )
                or (
                    step_id == "source-attached" and previous["id"] == "article-indexed"
                )
                or (
                    step_id in {"source-attached", "source-isolated"}
                    and previous["id"]
                    in {
                        "allowed-native",
                        "allowed-indexed",
                        "denied-native",
                        "denied-indexed",
                    }
                )
            )
        ):
            raise KnowledgeConnectError(
                "Knowledge checkpoints cannot bypass incomplete configuration steps."
            )
    for stamp in timestamps:
        if not isinstance(stamp, str):
            raise KnowledgeConnectError("Knowledge progress has malformed timestamps.")
        try:
            parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise KnowledgeConnectError(
                "Knowledge progress has malformed timestamps."
            ) from exc
        if parsed.tzinfo is None:
            raise KnowledgeConnectError(
                "Knowledge progress timestamps must include a timezone."
            )


@contextmanager
def transaction(root: Path):
    path = root / CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(".lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise KnowledgeConnectError(
            "Another Knowledge operation owns the progress lock. Wait for it; "
            "a stale lock requires explicit recovery, not automatic deletion."
        ) from exc
    os.close(descriptor)
    temporary: Path | None = None
    try:
        state = read_json(path) if path.exists() else {}
        if state:
            validate_state(state)
            if state["schemaVersion"] == 1:
                state.update(schemaVersion=2, checkpoints={})
        yield state
        validate_state(state)
        state["updatedAt"] = now()
        with tempfile.NamedTemporaryFile(
            dir=path.parent, delete=False, suffix=".tmp", mode="w", encoding="utf-8"
        ) as stream:
            temporary = Path(stream.name)
            json.dump(state, stream, indent=2, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
        lock.unlink()


def require_current(state: dict[str, Any], root: Path) -> None:
    if not state:
        raise KnowledgeConnectError(
            "Start the guided Knowledge journey before recording evidence."
        )
    if state["scope"]["target"] != resolve_target(root):
        raise KnowledgeConnectError(
            "The selected target changed. Start again to revalidate scope; no evidence accepted."
        )


def invalidate(state: dict[str, Any], owner: str) -> None:
    downstream = {
        "servicenow": ("m365", "validation"),
        "m365": ("validation",),
        "validation": (),
    }
    for phase in downstream[owner]:
        state["evidence"].pop(phase, None)
        state["issues"].pop(phase, None)
        clear_checkpoints(state, phase)


def clear_checkpoints(state: dict[str, Any], owner: str) -> None:
    for step in configuration_steps(state["scope"]):
        if step["owner"] == owner:
            state.get("checkpoints", {}).pop(step["id"], None)


def record(state: dict[str, Any], owner: str, answers: dict[str, str]) -> None:
    state["evidence"][owner] = {
        "kind": "maker-tested" if owner == "validation" else "admin-confirmed",
        "recordedAt": now(),
        "values": answers,
    }


def complete_guided_validation(state: dict[str, Any]) -> None:
    steps = configuration_steps(state["scope"])
    if state["issues"] or any(
        not step_complete(state, step)
        for step in steps
        if step["id"] != "observation-time"
    ):
        return
    validation_steps = [step for step in steps if step["owner"] == "validation"]
    observation = next(
        step for step in validation_steps if step["id"] == "observation-time"
    )
    if not step_complete(state, observation):
        timestamp = max(
            (
                state["checkpoints"][step["id"]]["recordedAt"]
                for step in validation_steps
                if step["id"] != "observation-time"
            ),
            key=lambda stamp: datetime.fromisoformat(stamp.replace("Z", "+00:00")),
        )
        timestamp = (
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            .astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
        state["checkpoints"]["observation-time"] = {
            "kind": "maker-tested",
            "recordedAt": timestamp,
            "value": timestamp,
        }
    if not values(state, "validation"):
        evidence = {
            step["field"]: state["checkpoints"][step["id"]]["value"]
            for step in validation_steps
        }
        evidence.update(
            targetReference=target_reference(state["scope"]),
            connectionName=values(state, "m365")["Connection name"],
        )
        record(
            state,
            "validation",
            validate_acceptance(evidence, state["scope"], evidence["connectionName"]),
        )


def start(
    root: Path, *, instance: str, query: str, flow: str, hr_content: bool | None = None
) -> dict[str, Any]:
    target = resolve_target(root)
    if flow not in {"simple", "advanced"} or (
        hr_content is not None and type(hr_content) is not bool
    ):
        raise KnowledgeConnectError(
            "Require an explicit Simple/Advanced flow and a Boolean or omitted HR-content scope."
        )
    scope = {
        "target": target,
        "instance": https_url(instance, "Instance URL"),
        "query": content_query(query),
        "flow": flow,
        "hrContent": hr_content,
    }
    with transaction(root) as state:
        if (
            state
            and hr_content is None
            and state["scope"]["instance"] == scope["instance"]
            and state["scope"]["query"] == scope["query"]
            and state["scope"]["target"]["tenantId"] == target["tenantId"]
        ):
            scope["hrContent"] = state["scope"]["hrContent"]
        if not state:
            state.update(
                schemaVersion=2,
                scope=scope,
                evidence={},
                issues={},
                checkpoints={},
                updatedAt=now(),
            )
        elif state["scope"] != scope:
            previous = state["scope"]
            if (
                previous["instance"] != scope["instance"]
                or previous["target"]["tenantId"] != target["tenantId"]
            ):
                state["evidence"].clear()
                state["checkpoints"].clear()
            elif any(
                previous[key] != scope[key] for key in ("query", "flow", "hrContent")
            ):
                healthy = {
                    key: value
                    for key, value in values(state, "servicenow").items()
                    if key in COMMON_FIELDS
                    and key
                    not in {"Scope assessment", "Assessment date", "HR scoped reads"}
                }
                state["evidence"].clear()
                state["checkpoints"].clear()
                if healthy:
                    record(state, "servicenow", healthy)
            else:
                state["evidence"].pop("validation", None)
                clear_checkpoints(state, "validation")
            state["scope"] = scope
            state["issues"].clear()
        complete_guided_validation(state)
    return summary(state)


def reset_guided_from(state: dict[str, Any], step: dict[str, Any]) -> None:
    steps = configuration_steps(state["scope"])
    affected = steps[steps.index(step) :]
    for previous in steps[: steps.index(step)]:
        evidence = state["evidence"].get(previous["owner"])
        if (
            previous["checkpoint"]
            and evidence
            and previous["field"] in evidence["values"]
            and step_complete(state, previous)
        ):
            state["checkpoints"].setdefault(
                previous["id"],
                {
                    "kind": evidence["kind"],
                    "recordedAt": evidence["recordedAt"],
                    "value": evidence["values"][previous["field"]],
                },
            )
    for owner in OWNERS:
        fields = {item["field"] for item in affected if item["owner"] == owner}
        if owner == "m365" and "Connection name" in fields:
            fields.add("Connection ID")
        if not fields:
            continue
        if owner == "validation":
            previous = state["evidence"].get(owner)
            if previous:
                for item in steps[: steps.index(step)]:
                    if item["owner"] == "validation":
                        state["checkpoints"].setdefault(
                            item["id"],
                            {
                                "kind": previous["kind"],
                                "recordedAt": previous["recordedAt"],
                                "value": previous["values"][item["field"]],
                            },
                        )
            state["evidence"].pop(owner, None)
        else:
            retained = {
                field: value
                for field, value in values(state, owner).items()
                if field not in fields
            }
            if retained:
                record(state, owner, retained)
            else:
                state["evidence"].pop(owner, None)
        state["issues"].pop(owner, None)
    for item in affected:
        state["checkpoints"].pop(item["id"], None)


def confirm(
    root: Path,
    step_id: str,
    value: str,
    reference: str,
    connection_name: str | None = None,
) -> dict[str, Any]:
    error: str | None = None
    with transaction(root) as state:
        require_current(state, root)
        if reference != target_reference(state["scope"]):
            raise KnowledgeConnectError(
                "Confirmation belongs to a different target or scope; refresh status."
            )
        steps = configuration_steps(state["scope"])
        grouped_denied = step_id == "denied-reader"
        step = next(
            (
                item
                for item in steps
                if item["id"] == ("denied-native" if grouped_denied else step_id)
            ),
            None,
        )
        if step is None:
            raise KnowledgeConnectError(
                "Choose a configuration step in the selected flow."
            )
        if (step["owner"] == "validation" or step_id == "connection-ready") and (
            connection_name is None
            or connection_name != values(state, "m365").get("Connection name")
        ):
            raise KnowledgeConnectError(
                "Runtime and reader confirmation requires the exact recorded connection name."
            )
        if any(
            not step_complete(state, previous)
            for previous in steps[: steps.index(step)]
        ):
            raise KnowledgeConnectError(
                "Complete the preceding configuration steps first."
            )
        if value == "skipped":
            if not grouped_denied:
                raise KnowledgeConnectError(
                    "Use the grouped denied-reader action to skip the whole comparison."
                )
            if state["issues"].get("validation"):
                raise KnowledgeConnectError(
                    "Resolve the reported validation failure before skipping; "
                    "a skip cannot clear an observed access failure."
                )
        if (
            step_id == "property-reads"
            and value == "proceed-without-access"
            and values(state, "servicenow").get(step["field"])
            not in PROPERTY_ACCESS_UNRESOLVED
        ):
            raise KnowledgeConnectError(
                "Record the reported property-access result before asking for "
                "explicit approval to continue without access."
            )
        try:
            accepted = validate_step_answer(step, value, state["scope"])
        except KnowledgeConnectError as exc:
            reset_guided_from(state, step)
            error = f"denied-reader: {exc}" if grouped_denied else str(exc)
            field = "validation" if step["owner"] == "validation" else step["field"]
            state["issues"][step["owner"]] = {field: error}
        else:
            previous = (
                state["checkpoints"]
                .get(step["id"], {})
                .get("value", values(state, step["owner"]).get(step["field"]))
                if step["checkpoint"]
                else values(state, step["owner"]).get(step["field"])
            )
            property_decision = (
                step_id == "property-reads"
                and previous in PROPERTY_ACCESS_UNRESOLVED
                and accepted in PROPERTY_ACCESS_UNRESOLVED
            )
            if previous is not None and previous != accepted and not property_decision:
                reset_guided_from(state, step)
            if step["checkpoint"]:
                checkpoint = {
                    "kind": "maker-tested"
                    if step["owner"] == "validation"
                    else "admin-confirmed",
                    "recordedAt": now(),
                    "value": accepted,
                }
                if grouped_denied:
                    for item in steps:
                        if (
                            item["field"] in DENIED_READER_FIELDS
                            and state["checkpoints"].get(item["id"], {}).get("value")
                            != accepted
                        ):
                            state["checkpoints"][item["id"]] = dict(checkpoint)
                else:
                    state["checkpoints"][step["id"]] = checkpoint
                if step_id == "connection-ready":
                    record(
                        state,
                        "m365",
                        {**values(state, "m365"), step["field"]: accepted},
                    )
            else:
                record(
                    state,
                    step["owner"],
                    {**values(state, step["owner"]), step["field"]: accepted},
                )
                if step_id == "scope-assessment" and "Assessment date" not in values(
                    state, "servicenow"
                ):
                    assessment = state["evidence"]["servicenow"]
                    assessment["values"]["Assessment date"] = assessment["recordedAt"][
                        :10
                    ]
                    state["issues"].get("servicenow", {}).pop("Assessment date", None)
            field = "validation" if step["owner"] == "validation" else step["field"]
            issues = state["issues"].get(step["owner"], {})
            denied_failure = step["owner"] == "validation" and any(
                issues.get(field, "").startswith(f"{label}:")
                for label in (*DENIED_READER_FIELDS, "denied-reader")
            )
            if (
                not denied_failure
                or grouped_denied
                or issues[field].startswith(f"{step['field']}:")
            ):
                issues.pop(field, None)
            if step_id == "connection-name":
                issues.pop("Connection ID", None)
            if not issues:
                state["issues"].pop(step["owner"], None)
            complete_guided_validation(state)
    return {"accepted": error is None, "stepError": error, **summary(state)}


def handoff(root: Path, owner: str, output: Path) -> dict[str, Any]:
    path = root / CONFIG_PATH
    state = read_json(path)
    validate_state(state)
    require_current(state, root)
    if owner == "m365" and any(
        field not in values(state, "servicenow")
        for field in fields_for("servicenow", state["scope"])
    ):
        raise KnowledgeConnectError(
            "Complete ServiceNow confirmations before issuing the Microsoft 365 handoff."
        )
    if output.exists():
        raise KnowledgeConnectError(
            "Handoff output already exists; choose a new path to preserve returned workbooks."
        )
    write_handoff(output, owner, state["scope"], values(state, owner))
    return {"workbook": str(output), **summary(state)}


def import_handoff(root: Path, owner: str, path: Path) -> dict[str, Any]:
    errors: dict[str, str] = {}
    with transaction(root) as state:
        require_current(state, root)
        if owner == "m365" and any(
            field not in values(state, "servicenow")
            for field in fields_for("servicenow", state["scope"])
        ):
            raise KnowledgeConnectError("ServiceNow confirmations are incomplete.")
        submitted = read_handoff(path, owner, state["scope"])
        accepted: dict[str, str] = {}
        for label, value in submitted.items():
            try:
                accepted[label] = validate_answer(label, value, state["scope"])
            except KnowledgeConnectError as exc:
                errors[label] = str(exc)
        if accepted != values(state, owner) or errors:
            invalidate(state, owner)
            clear_checkpoints(state, owner)
        record(state, owner, accepted)
        if errors:
            state["issues"][owner] = errors
        else:
            state["issues"].pop(owner, None)
    return {"accepted": not errors, "fieldErrors": errors, **summary(state)}


def accept(root: Path, evidence: dict[str, Any]) -> dict[str, Any]:
    with transaction(root) as state:
        require_current(state, root)
        if (
            isinstance(evidence, dict)
            and any(evidence.get(field) == "skipped" for field in DENIED_READER_FIELDS)
            and state["issues"].get("validation")
        ):
            raise KnowledgeConnectError(
                "Resolve the reported validation failure before skipping; "
                "a skip cannot clear an observed access failure."
            )
        if values(state, "servicenow").get("Permission property reads") in (
            PROPERTY_ACCESS_UNRESOLVED - {"proceed-without-access"}
        ):
            raise KnowledgeConnectError(
                "Verify property access or explicitly approve continuing without it "
                "before maker validation."
            )
        for owner in ("servicenow", "m365"):
            if any(
                field not in values(state, owner)
                for field in fields_for(owner, state["scope"])
            ):
                raise KnowledgeConnectError(
                    "Complete both administrator milestones before maker validation."
                )
        readiness = next(
            step
            for step in configuration_steps(state["scope"])
            if step["id"] == "connection-ready"
        )
        if not step_complete(state, readiness):
            raise KnowledgeConnectError(
                "Confirm post-Create operation for the exact connection before maker validation."
            )
        try:
            answers = validate_acceptance(
                evidence, state["scope"], values(state, "m365")["Connection name"]
            )
        except KnowledgeConnectError as exc:
            state["evidence"].pop("validation", None)
            clear_checkpoints(state, "validation")
            state["issues"]["validation"] = {"validation": str(exc)}
        else:
            record(state, "validation", answers)
            state["issues"].pop("validation", None)
    return summary(state)


def reopen(root: Path, owner: str, field: str) -> dict[str, Any]:
    with transaction(root) as state:
        require_current(state, root)
        if owner == "validation":
            if field != "validation":
                raise KnowledgeConnectError(
                    "Reopen the validation milestone using field 'validation'."
                )
            state["evidence"].pop(owner, None)
            clear_checkpoints(state, owner)
        else:
            if field not in fields_for(owner, state["scope"]):
                raise KnowledgeConnectError(
                    "Choose a documented field owned by this administrator."
                )
            step = next(
                item
                for item in configuration_steps(state["scope"])
                if item["owner"] == owner and item["field"] == field
            )
            reset_guided_from(state, step)
        invalidate(state, owner)
        state["issues"][owner] = {
            field: "Reconfirmation required after a reported change or failure."
        }
    return summary(state)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("preflight")
    commands.add_parser("status")
    begin = commands.add_parser("start")
    begin.add_argument("--instance", required=True)
    begin.add_argument("--query", required=True)
    begin.add_argument("--flow", choices=("simple", "advanced"), required=True)
    begin.add_argument(
        "--hr-content",
        choices=("yes", "no"),
        help="Optional administrator-established HRSD scope; not an upfront maker question.",
    )
    confirmation = commands.add_parser("confirm")
    confirmation.add_argument("--step", required=True)
    confirmation.add_argument("--value", required=True)
    confirmation.add_argument("--target-reference", required=True)
    confirmation.add_argument("--connection-name")
    for name in ("handoff", "import-handoff"):
        command = commands.add_parser(name)
        command.add_argument("--owner", choices=("servicenow", "m365"), required=True)
        command.add_argument("--file", type=Path, required=True)
    validation = commands.add_parser("accept")
    validation.add_argument("--evidence-file", type=Path, required=True)
    correction = commands.add_parser("reopen")
    correction.add_argument("--owner", choices=OWNERS, required=True)
    correction.add_argument("--field", required=True)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "preflight":
            result = {
                "target": resolve_target(root),
                "kind": "workspace-confirmed",
                "liveTargetVerified": False,
            }
        elif args.command == "status":
            path = root / CONFIG_PATH
            if not path.exists():
                result = {"status": "not-started"}
            else:
                state = read_json(path)
                validate_state(state)
                require_current(state, root)
                result = summary(state)
        elif args.command == "start":
            result = start(
                root,
                instance=args.instance,
                query=args.query,
                flow=args.flow,
                hr_content=None
                if args.hr_content is None
                else args.hr_content == "yes",
            )
        elif args.command == "handoff":
            result = handoff(root, args.owner, args.file.resolve())
        elif args.command == "import-handoff":
            result = import_handoff(root, args.owner, args.file.resolve())
        elif args.command == "accept":
            result = accept(root, read_json(args.evidence_file))
        elif args.command == "confirm":
            result = confirm(
                root, args.step, args.value, args.target_reference, args.connection_name
            )
        else:
            result = reopen(root, args.owner, args.field)
        print("SERVICENOW_KB_RESULT_JSON:" + json.dumps(result, sort_keys=True))
        return (
            1
            if result.get("accepted") is False or result.get("status") == "blocked"
            else 0
        )
    except (
        KnowledgeConnectError,
        WorkdayConnectWorkbookError,
        OSError,
        ValueError,
    ) as exc:
        print(
            "SERVICENOW_KB_ERROR_JSON:"
            + json.dumps({"error": str(exc), "noRemoteChanges": True})
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
