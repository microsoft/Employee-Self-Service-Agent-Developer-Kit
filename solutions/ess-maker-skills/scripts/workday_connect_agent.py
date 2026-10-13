# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Live native-agent verification for Workday lifecycle completion."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping

import yaml

from agentbuilder_object_model import (
    ObjectModelConverterError,
    yaml_to_object_models,
)
from minimalbot_evaluation import (
    MinimalBotEvaluationClient,
    MinimalBotEvaluationError,
    resolve_workday_dialogs,
)


class WorkdayConnectAgentError(RuntimeError):
    """Raised when native Workday agent readiness cannot be proven."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkdayConnectAgentError(
            f"Required workspace state could not be read: {path}: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise WorkdayConnectAgentError(
            f"Required workspace state must contain an object: {path}"
        )
    return document


def _required_text(
    values: Mapping[str, Any],
    key: str,
    label: str,
) -> str:
    value = str(values.get(key) or "").strip()
    if not value:
        raise WorkdayConnectAgentError(f"{label} is missing.")
    return value


def _active_agent(config: Mapping[str, Any]) -> dict[str, Any]:
    active_slug = str(config.get("activeAgent") or "").strip()
    agents = config.get("agents")
    if isinstance(agents, list) and active_slug:
        matches = [
            dict(agent)
            for agent in agents
            if isinstance(agent, Mapping)
            and str(agent.get("slug") or "") == active_slug
        ]
        if len(matches) == 1:
            return matches[0]
    agent = config.get("agent")
    if isinstance(agent, Mapping) and str(agent.get("slug") or "") == active_slug:
        return dict(agent)
    raise WorkdayConnectAgentError(
        "The active agent could not be resolved from foundation setup state."
    )


def _agent_folder(
    workspace_root: Path,
    agent: Mapping[str, Any],
) -> Path:
    configured = str(agent.get("folder") or "").strip()
    if configured:
        candidate = Path(configured)
        if not candidate.is_absolute():
            candidate = workspace_root / candidate
    else:
        candidate = (
            workspace_root
            / "workspace"
            / "agents"
            / _required_text(agent, "slug", "Active agent slug")
        )
    candidate = candidate.resolve()
    agents_root = (workspace_root / "workspace" / "agents").resolve()
    try:
        candidate.relative_to(agents_root)
    except ValueError as exc:
        raise WorkdayConnectAgentError(
            "The active agent folder is outside workspace/agents."
        ) from exc
    if not candidate.is_dir():
        raise WorkdayConnectAgentError(
            f"The active agent workspace folder does not exist: {candidate}"
        )
    return candidate


def _mapped_dialog(
    agent_folder: Path,
    display_name: str,
    expected_schema_name: str,
) -> dict[str, str]:
    component_map = _read_json(agent_folder / ".component-map.json")
    matches = []
    for raw_path, raw_entry in component_map.items():
        if (
            isinstance(raw_path, str)
            and isinstance(raw_entry, Mapping)
            and raw_entry.get("componentKind") == "DialogComponent"
            and str(raw_entry.get("displayName") or "") == display_name
        ):
            normalized_path = raw_path.replace("\\", "/")
            relative_path = PurePosixPath(normalized_path)
            if (
                relative_path.is_absolute()
                or ".." in relative_path.parts
                or not relative_path.parts
                or relative_path.parts[0] != "topics"
                or not normalized_path.endswith(".mcs.yml")
            ):
                raise WorkdayConnectAgentError(
                    f"Unsafe mapped topic path for {display_name}: {raw_path}"
                )
            local_path = agent_folder.joinpath(
                *relative_path.parts
            ).resolve()
            try:
                local_path.relative_to(agent_folder)
            except ValueError as exc:
                raise WorkdayConnectAgentError(
                    f"Mapped topic is outside the active agent: {raw_path}"
                ) from exc
            if not local_path.is_file():
                raise WorkdayConnectAgentError(
                    f"Mapped topic file is missing: {raw_path}"
                )
            matches.append(
                {
                    "path": normalized_path,
                    "localPath": str(local_path),
                    "componentId": _required_text(
                        raw_entry,
                        "componentId",
                        f"{display_name} component ID",
                    ),
                    "schemaName": _required_text(
                        raw_entry,
                        "schemaName",
                        f"{display_name} schema name",
                    ),
                }
            )
    if len(matches) != 1:
        raise WorkdayConnectAgentError(
            f"Expected exactly one mapped {display_name} topic; found "
            f"{len(matches)}."
        )
    match = matches[0]
    if match["schemaName"].casefold() != expected_schema_name.casefold():
        raise WorkdayConnectAgentError(
            f"Mapped {display_name} schema name does not match the reviewed "
            f"agent contract: {match['schemaName']}."
        )
    return match


def _topic_document(topic: Mapping[str, str]) -> dict[str, Any]:
    path = Path(topic["localPath"])
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise WorkdayConnectAgentError(
            f"Mapped topic could not be read: {path}: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise WorkdayConnectAgentError(
            f"Mapped topic must contain an object: {path}"
        )
    return document


def _begin_dialog_targets(
    value: Any,
    *,
    _seen: set[int] | None = None,
    _depth: int = 0,
) -> list[str]:
    if _depth > 100:
        raise WorkdayConnectAgentError(
            "Mapped topic nesting exceeds the supported verification depth."
        )
    seen = _seen if _seen is not None else set()
    targets = []
    if isinstance(value, (Mapping, list)):
        identity = id(value)
        if identity in seen:
            raise WorkdayConnectAgentError(
                "Mapped topic contains a recursive YAML alias."
            )
        seen.add(identity)
    if isinstance(value, Mapping):
        if value.get("kind") == "BeginDialog":
            target = str(value.get("dialog") or "").strip()
            if target:
                targets.append(target)
        for child in value.values():
            targets.extend(
                _begin_dialog_targets(
                    child,
                    _seen=seen,
                    _depth=_depth + 1,
                )
            )
    elif isinstance(value, list):
        for child in value:
            targets.extend(
                _begin_dialog_targets(
                    child,
                    _seen=seen,
                    _depth=_depth + 1,
                )
            )
    if isinstance(value, (Mapping, list)):
        seen.remove(id(value))
    return targets


def verify_runtime_template_wiring(
    workspace_root: Path,
    state: Mapping[str, Any],
    *,
    client_factory: Callable[
        [dict[str, Any]], MinimalBotEvaluationClient
    ] = MinimalBotEvaluationClient.from_config,
    converter: Callable[
        [list[dict[str, Any]]], list[dict[str, Any]]
    ] = yaml_to_object_models,
) -> dict[str, Any]:
    """Verify Conversation Start initializes Workday templates exactly once."""
    context = _agent_verification_context(workspace_root, state)
    agent_folder = Path(context["agentFolder"])
    agent_schema = str(context["agentSchema"])
    conversation_start = _mapped_dialog(
        agent_folder,
        "Conversation Start",
        f"{agent_schema}.topic.ConversationStart",
    )
    runtime_template = _mapped_dialog(
        agent_folder,
        "Workday [System] - 1: Set Runtime Template Configurations",
        (
            f"{agent_schema}.topic."
            "WorkdaySystemSetRuntimeTemplateConfigurations"
        ),
    )
    user_context = _mapped_dialog(
        agent_folder,
        "Workday [System] - 1: Set User Context V2",
        f"{agent_schema}.topic.WorkdaySystemGetUserContextV2",
    )
    target_schema = runtime_template["schemaName"]
    validation_schema = (
        f"{agent_schema}.topic.System-UserContext-Validate"
    )
    conversation_document = _topic_document(conversation_start)
    begin_dialog = conversation_document.get("beginDialog")
    actions = (
        begin_dialog.get("actions")
        if isinstance(begin_dialog, Mapping)
        else None
    )
    if not isinstance(actions, list) or not actions:
        raise WorkdayConnectAgentError(
            "Conversation Start has no actions to initialize Workday runtime "
            "templates."
        )
    all_targets = _begin_dialog_targets(conversation_document)
    top_level_targets = [
        str(action.get("dialog") or "").strip()
        if (
            isinstance(action, Mapping)
            and action.get("kind") == "BeginDialog"
        )
        else ""
        for action in actions
    ]
    validation_positions = [
        index
        for index, target in enumerate(top_level_targets)
        if target == validation_schema
    ]
    runtime_precedes_validation = (
        len(validation_positions) == 1
        and validation_positions[0] > 0
        and top_level_targets[validation_positions[0] - 1] == target_schema
    )
    if (
        all_targets.count(target_schema) != 1
        or not runtime_precedes_validation
    ):
        raise WorkdayConnectAgentError(
            "Conversation Start must call the Workday runtime template "
            "configuration topic exactly once immediately before User "
            "Context Validate."
        )
    user_context_document = _topic_document(user_context)
    if target_schema in _begin_dialog_targets(user_context_document):
        raise WorkdayConnectAgentError(
            "The obsolete nested Workday runtime template initialization "
            "still exists in User Context V2."
        )
    conversion_items = [
        {
            "key": topic["path"],
            "yaml": Path(topic["localPath"]).read_text(encoding="utf-8"),
        }
        for topic in (
            conversation_start,
            runtime_template,
            user_context,
        )
    ]
    try:
        converted = converter(conversion_items)
    except ObjectModelConverterError as exc:
        raise WorkdayConnectAgentError(
            f"Workday topic conversion failed: {exc}"
        ) from exc
    converted_by_key = {
        str(item.get("key") or ""): item
        for item in converted
        if isinstance(item, Mapping)
    }
    expectations = []
    for topic in (
        conversation_start,
        runtime_template,
        user_context,
    ):
        converted_topic = converted_by_key.get(topic["path"])
        if (
            not isinstance(converted_topic, Mapping)
            or converted_topic.get("success") is not True
            or not isinstance(converted_topic.get("objectModel"), dict)
        ):
            raise WorkdayConnectAgentError(
                f"Workday topic conversion failed for {topic['path']}."
            )
        expectation = {
            "componentId": topic["componentId"],
            "schemaName": topic["schemaName"],
            "dialog": converted_topic["objectModel"],
            "requireCleanDiagnostics": topic is conversation_start,
        }
        if topic is conversation_start:
            expectation.update(
                {
                    "state": "Active",
                    "status": "Active",
                }
            )
        expectations.append(expectation)
    try:
        client = client_factory(dict(context["foundation"]))
        client.authenticate(
            preferred_username=str(context["makerUsername"]),
        )
        verification = client.verify_dialog_components(expectations)
    except MinimalBotEvaluationError as exc:
        raise WorkdayConnectAgentError(
            "Copilot Studio did not retain the reviewed Workday runtime "
            f"template wiring: {exc}"
        ) from exc
    return {
        "environmentId": context["environmentId"],
        "botId": context["botId"],
        "makerUsername": str(
            client.signed_in_username or context["makerUsername"]
        ),
        "conversationStart": conversation_start["schemaName"],
        "runtimeTemplate": target_schema,
        "userContextValidate": validation_schema,
        "userContext": user_context["schemaName"],
        "verifiedComponents": verification["verifiedComponents"],
        "blockingDiagnostics": verification["blockingDiagnostics"],
    }


def verify_agent_binding(
    workspace_root: Path,
    state: Mapping[str, Any],
    *,
    client_factory: Callable[
        [dict[str, Any]], MinimalBotEvaluationClient
    ] = MinimalBotEvaluationClient.from_config,
) -> dict[str, Any]:
    """Verify Workday binding without using topic diagnostics as runtime proof."""
    context = _agent_verification_context(workspace_root, state)
    return _verify_workday_topics(
        context,
        client_factory=client_factory,
        require_clean_diagnostics=False,
    )


def _agent_verification_context(
    workspace_root: Path,
    state: Mapping[str, Any],
) -> dict[str, Any]:
    foundation = _read_json(workspace_root / ".local" / "config.json")
    scope = state.get("scope") or {}
    recorded_agent = scope.get("agent") or {}
    active_agent = _active_agent(foundation)
    environment_id = _required_text(
        scope,
        "environmentId",
        "Recorded environment ID",
    )
    foundation_environment = _required_text(
        foundation,
        "environmentId",
        "Foundation environment ID",
    )
    if foundation_environment.casefold() != environment_id.casefold():
        raise WorkdayConnectAgentError(
            "Foundation setup and Workday state target different environments."
        )
    recorded_slug = _required_text(
        recorded_agent,
        "slug",
        "Recorded agent slug",
    )
    if (
        _required_text(active_agent, "slug", "Active agent slug").casefold()
        != recorded_slug.casefold()
    ):
        raise WorkdayConnectAgentError(
            "Foundation setup and Workday state target different agents."
        )
    bot_id = _required_text(recorded_agent, "botId", "Recorded agent bot ID")
    if (
        _required_text(active_agent, "botId", "Active agent bot ID").casefold()
        != bot_id.casefold()
    ):
        raise WorkdayConnectAgentError(
            "Foundation setup and Workday state target different agents."
        )
    agent_schema = _required_text(
        active_agent,
        "schemaName",
        "Active agent schema name",
    )
    if (
        _required_text(
            recorded_agent,
            "schemaName",
            "Recorded agent schema name",
        ).casefold()
        != agent_schema.casefold()
    ):
        raise WorkdayConnectAgentError(
            "Foundation setup and Workday state contain different agent schemas."
        )
    maker = _required_text(
        (state.get("operators") or {}).get("powerPlatformMaker") or {},
        "username",
        "Power Platform maker account",
    )
    return {
        "foundation": foundation,
        "environmentId": environment_id,
        "botId": bot_id,
        "makerUsername": maker,
        "agentSchema": agent_schema,
        "agentFolder": _agent_folder(workspace_root, active_agent),
    }


def _verify_workday_topics(
    context: Mapping[str, Any],
    *,
    client_factory: Callable[[dict[str, Any]], MinimalBotEvaluationClient],
    require_clean_diagnostics: bool,
) -> dict[str, Any]:
    topics = resolve_workday_dialogs(
        context["agentFolder"],
        str(context["agentSchema"]),
    )
    expectations = [
        {
            **topic,
            "state": "Active",
            "status": "Active",
            "requireCleanDiagnostics": require_clean_diagnostics,
        }
        for topic in topics
    ]
    try:
        client = client_factory(dict(context["foundation"]))
        client.authenticate(
            preferred_username=str(context["makerUsername"]),
        )
        verification = client.verify_dialog_components(expectations)
    except MinimalBotEvaluationError as exc:
        customer_safe = (
            str(exc)
            .replace("MinimalBot dialog", "Copilot Studio topic")
            .replace("MinimalBot", "Copilot Studio")
            .replace("component map", "topic inventory")
        )
        raise WorkdayConnectAgentError(customer_safe) from exc

    return {
        "environmentId": context["environmentId"],
        "botId": context["botId"],
        "makerUsername": str(client.signed_in_username or context["makerUsername"]),
        "workdayTopics": {
            "expected": len(topics),
            "verified": verification["verifiedComponents"],
            "active": verification["activeComponents"],
            "blockingDiagnostics": verification["blockingDiagnostics"],
        },
    }


def verify_topic_activation(
    workspace_root: Path,
    state: Mapping[str, Any],
    *,
    client_factory: Callable[
        [dict[str, Any]], MinimalBotEvaluationClient
    ] = MinimalBotEvaluationClient.from_config,
) -> dict[str, Any]:
    """Verify live topic activation without treating dependency health as state."""
    return _verify_workday_topics(
        _agent_verification_context(workspace_root, state),
        client_factory=client_factory,
        require_clean_diagnostics=False,
    )
