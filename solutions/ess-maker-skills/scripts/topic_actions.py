# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Topic-set actions with fail-closed native preview and in-memory caller results."""

from __future__ import annotations

import argparse

from copy import deepcopy

import json

from pathlib import Path

import sys

from typing import Any

import uuid

import requests

from agentbuilder import (
    DEFAULT_TOKEN_CACHE,
    AgentBuilderClient,
    AgentBuilderError,
    AgentBuilderHTTPError,
    authenticate_flightcheck,
    environment_id_from_host,
    validate_environment_host,
)

from flightcheck.agent_scope import active_agent

RESULT_MARKER = "TOPIC_ACTIONS_RESULT_JSON:"

TARGET_FIELDS = frozenset({"tenantId", "environmentId", "agentId"})

REQUEST_FIELDS = frozenset(
    {"contractVersion", "target", "action", "setKeys", "entry", "callerContext"}
)

class TopicActionsError(ValueError):
    """A safe, structured entry failure without raw input or service bodies."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason

def _entry_message(reason: str, message: str) -> str:
    if reason == "cancelled":
        return "Canceled. No topics were changed."
    if reason == "setup_not_run":
        message = (
            "ADK setup has not established the account, agent and environment "
            "in this workspace. Run /setup here, then return to this conversation "
            "and start a new topic-change request."
        )
    elif reason == "setup_incomplete":
        message += (
            " Run /setup in this workspace to continue setup for the same agent, "
            "keeping completed steps. Then return to this conversation and "
            "start a new topic-change request."
        )
    elif reason in ("setup_broken", "workspace_missing", "target_unverified", "target_not_found"):
        if reason == "target_not_found":
            message = (
                "The selected agent could not be accessed. Its availability "
                "could not be established; do not assume it was deleted."
            )
        message += (
            " Keep the existing target and completed setup steps. A supported "
            "recovery route for this problem has not been confirmed; do not "
            "create or select a replacement agent to continue this request."
        )
    elif reason == "access_denied":
        message = (
            "The signed-in account was denied read access to the selected agent "
            "or environment. Ask the administrator responsible for that agent "
            "and environment to check read access, then return here with a new "
            "request. Topic-edit permission is still unverified."
        )
    elif reason == "authentication_failed":
        message = (
            "I couldn't verify the signed-in account. This does not establish "
            "that the account lacks topic-edit permission. Return here with a "
            "new request after account access can be verified."
        )
    elif reason in ("authentication_or_evidence_failed", "evidence_read_failed"):
        message = (
            "I couldn't complete the topic review because account or topic "
            "evidence was unavailable. This does not establish an access denial, "
            "missing packages or already-correct topic states. Any new request "
            "will check the evidence again."
        )
    return message if "No topics were changed." in message else message + " No topics were changed."

def _guid(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("An identity must be a GUID string.")
    return str(uuid.UUID(value))

def validate_request(value: Any) -> dict[str, Any]:
    """Validate provisional logical inputs, not topic-set membership."""
    if not isinstance(value, dict) or set(value) - REQUEST_FIELDS:
        raise TopicActionsError("invalid_request", "Unsupported request shape.")
    version = value.get("contractVersion", 1)
    if type(version) is not int or version != 1:
        raise TopicActionsError("invalid_request", "Unsupported request contract version.")
    target = value.get("target")
    try:
        if not isinstance(target, dict) or set(target) != TARGET_FIELDS:
            raise ValueError("Incomplete target.")
        target = {key: _guid(target[key]) for key in sorted(TARGET_FIELDS)}
    except ValueError as exc:
        raise TopicActionsError(
            "invalid_request", "Provide one tenant, environment and agent ID."
        ) from exc
    if value.get("action") not in ("enable", "disable"):
        raise TopicActionsError(
            "invalid_request", "Choose one action: enable or disable."
        )
    keys = value.get("setKeys")
    if (
        not isinstance(keys, list)
        or not keys
        or any(
            not isinstance(key, str)
            or not key
            or key != key.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in key)
            for key in keys
        )
        or len(set(keys)) != len(keys)
    ):
        raise TopicActionsError(
            "invalid_request", "Provide distinct, nonempty topic-set keys."
        )
    entry = value.get("entry")
    context = value.get("callerContext", {})
    if (
        entry not in ("direct", "caller")
        or not isinstance(context, dict)
        or (entry == "caller" and not context)
    ):
        raise TopicActionsError(
            "invalid_request", "Provide a valid entry and retained caller context."
        )
    try:
        json.dumps(context, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise TopicActionsError(
            "invalid_request", "Caller context must be a JSON object."
        ) from exc
    return {
        "contractVersion": version,
        "target": target,
        "action": value["action"],
        "setKeys": list(keys),
        "entry": entry,
        "callerContext": deepcopy(context),
    }

def _read_object(path: Path, missing_reason: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise TopicActionsError(
            missing_reason, "The active agent's workspace information is missing."
        ) from exc
    except (OSError, ValueError) as exc:
        raise TopicActionsError(
            "setup_broken", "The existing setup information could not be read."
        ) from exc
    if not isinstance(value, dict):
        raise TopicActionsError(
            "setup_broken", "The existing setup information is malformed."
        )
    return value

def _workspace_target(
    root: Path, target: dict[str, str], *, require_connect_ready: bool = True,
) -> dict[str, str]:
    setup = _read_object(root / ".local" / "setup" / "config.json", "setup_not_run")
    config = _read_object(root / ".local" / "config.json", "workspace_missing")
    slug = config.get("activeAgent")
    agents = config.get("agents", [])
    if (
        setup.get("schema_version") != 4
        or not isinstance(slug, str)
        or not slug.strip()
        or not isinstance(agents, list)
        or any(not isinstance(agent, dict) for agent in agents)
        or not isinstance(setup.get("agents"), dict)
    ):
        raise TopicActionsError(
            "setup_broken", "The selected agent's saved setup information cannot be validated."
        )
    selected = active_agent(config, slug)
    matches = [
        (key, record)
        for key, record in setup["agents"].items()
        if isinstance(record, dict)
        and isinstance(record.get("agent"), dict)
        and record["agent"].get("workspace_slug") == slug
    ]
    if not selected or len(matches) != 1:
        raise TopicActionsError(
            "target_unverified", "One active agent could not be established."
        )
    key, record = matches[0]
    environment = setup.get("environment")
    try:
        if not isinstance(environment, dict):
            raise ValueError("Missing canonical environment.")
        observed = {
            "tenantId": _guid(environment.get("tenant_id")),
            "environmentId": _guid(environment.get("id")),
            "agentId": _guid(record["agent"].get("id")),
        }
        if (
            observed != target
            or _guid(key) != target["agentId"]
            or _guid(selected.get("botId")) != target["agentId"]
            or selected.get("releaseLine", config.get("releaseLine")) != "da"
            or any(
                source.get("environmentId") is not None
                and _guid(source["environmentId"]) != target["environmentId"]
                for source in (config, selected)
            )
        ):
            raise ValueError("Conflicting target.")
        ring = environment.get("ring")
        host = validate_environment_host(
            environment.get("power_platform_api_endpoint", ""), ring
        )
        if environment_id_from_host(host, ring) != target["environmentId"]:
            raise ValueError("Conflicting environment host.")
        api_version = environment.get("api_version")
        if not isinstance(api_version, str) or not api_version.strip():
            raise ValueError("Missing API version.")
    except (TypeError, ValueError, AttributeError) as exc:
        raise TopicActionsError(
            "target_unverified", "The request does not match verified workspace identity."
        ) from exc
    workspace = record.get("workspace", {})
    steps = record.get("steps", {})
    if not isinstance(workspace, dict) or not isinstance(steps, dict):
        raise TopicActionsError(
            "setup_broken", "The selected agent's workspace preparation record is malformed.",
        )
    local_step = steps.get("SETUP-07", {})
    if not isinstance(local_step, dict):
        raise TopicActionsError(
            "setup_broken", "The selected agent's local workspace setup step is malformed.",
        )
    workspace_recorded = (
        isinstance(workspace.get("folder"), str) and bool(workspace["folder"].strip())
        and isinstance(workspace.get("agent_path"), str) and bool(workspace["agent_path"].strip())
    )
    if not require_connect_ready and local_step.get("state") == "done" and not workspace_recorded:
        raise TopicActionsError(
            "setup_broken",
            "Local workspace setup is recorded as complete, but its workspace information is missing.",
        )
    prepared = workspace_recorded and local_step.get("state") == "done"
    if (require_connect_ready and record.get("connect_ready") is not True) or (
        not require_connect_ready and not prepared
    ):
        raise TopicActionsError(
            "setup_incomplete",
            "Selected-agent setup is incomplete." if require_connect_ready else
            "Setup has not finished preparing the selected agent's local workspace.",
        )
    return {"host": host, "ring": ring, "api_version": api_version}

def _result(
    reason: str,
    message: str,
    context: dict[str, Any],
    *,
    target: dict[str, str] | None = None,
    verified: bool = False,
) -> dict[str, Any]:
    return {
        "contractVersion": 1,
        "contractStatus": "provisional",
        "status": "cancelled" if reason == "cancelled" else "blocked",
        "reason": reason,
        "message": _entry_message(reason, message),
        "completed": False,
        "writeStatus": "not_attempted",
        "target": target,
        "checks": {
            "account": "verified" if verified else "unverified",
            "targetReadAccess": "verified" if verified else "unverified",
            "writeAuthority": "unverified",
            "topicSets": "unverified",
        },
        "callerContext": deepcopy(context),
    }

def inspect_request(
    value: Any,
    *,
    workspace_root: Path,
    account_hint: str | None = None,
    cancelled: bool = False,
) -> dict[str, Any]:
    """Inspect one target without changing topics, setup or caller progress.

    callerContext is private, in-memory return data; the CLI never emits it.
    """
    context = value.get("callerContext", {}) if isinstance(value, dict) else {}
    context = deepcopy(context) if isinstance(context, dict) else {}
    if cancelled:
        return _result(
            "cancelled", "Cancelled. No topic changes were attempted.", context
        )
    target = None
    stage = "authentication_failed"
    try:
        request = validate_request(value)
        context = request["callerContext"]
        target = request["target"]
        connection = _workspace_target(workspace_root, target, require_connect_ready=False)
        token, tenant_id, account = authenticate_flightcheck(
            connection["ring"],
            cache_path=workspace_root / DEFAULT_TOKEN_CACHE,
            account_hint=account_hint,
            include_connectivity=False,
            allow_write=False,
            emit_account_identity=False,
            return_account_identity=True,
        )
        if (
            _guid(tenant_id) != target["tenantId"]
            or not isinstance(account, str)
            or not account.strip()
            or (
                account_hint is not None
                and account.casefold() != account_hint.strip().casefold()
            )
        ):
            raise TopicActionsError(
                "account_mismatch", "The authenticated account or tenant could not be verified."
            )
        stage = "target_unverified"
        client = AgentBuilderClient(
            connection["host"],
            token,
            ring=connection["ring"],
            tenant_id=tenant_id,
            api_version=connection["api_version"],
        )
        try:
            remote = client.get_agent(target["agentId"])
        finally:
            client.session.close()
        if _guid(remote.get("botId")) != target["agentId"]:
            raise TopicActionsError(
                "target_unverified", "Direct lookup returned a different agent identity."
            )
    except TopicActionsError as exc:
        return _result(exc.reason, str(exc), context, target=target)
    except AgentBuilderHTTPError as exc:
        reason = "authentication_failed" if stage == "authentication_failed" else {
            401: "authentication_failed",
            403: "access_denied",
            404: "target_not_found",
        }.get(exc.status_code, "target_unverified")
        return _result(
            reason, "The selected agent could not be accessed.",
            context, target=target,
        )
    except (AgentBuilderError, requests.RequestException, OSError, ValueError):
        # Service exception text may contain tokens or full response bodies.
        return _result(
            stage, "The read-only target check could not complete. No changes were attempted.",
            context, target=target,
        )
    return _result(
        "implementation_pending",
        "Account and selected-agent read access verified. Topic-set actions are not "
        "available yet; write authority and topic-set readiness remain unverified. "
        "No topics were changed.",
        context, target=target, verified=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, default=Path.cwd())
    parser.add_argument("--account", help="Verify this Microsoft work account.")
    parser.add_argument("--cancel", action="store_true")
    args = parser.parse_args(argv)
    try:
        value = {} if args.cancel else json.load(sys.stdin)
    except (OSError, ValueError):
        result = _result(
            "invalid_request", "Provide one JSON request on standard input.", {}
        )
    else:
        result = inspect_request(
            value, workspace_root=args.workspace_root,
            account_hint=args.account, cancelled=args.cancel,
        )
    public = {key: item for key, item in result.items() if key != "callerContext"}
    print(RESULT_MARKER + json.dumps(public, sort_keys=True))
    return 0 if result["reason"] in ("implementation_pending", "cancelled") else 1


if __name__ == "__main__":
    raise SystemExit(main())
