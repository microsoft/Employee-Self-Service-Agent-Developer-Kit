# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""ESS Maker Kit ADK MCP Server.

Exposes high-level ESS Maker Kit automation as MCP tools for creating topics,
running FlightCheck, and generating evaluation files backed by the local kit
workspace plus Dataverse REST APIs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

import yaml
from mcp.server.fastmcp import FastMCP

# Allow imports from scripts/auth.py when the server is launched directly.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))

from auth import (  # type: ignore  # pylint: disable=import-error
    AuthExpiredError,
    authenticate,
    create_record,
    load_config,
    update_record,
)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
FLIGHTCHECK_RESULTS_PATH = os.path.join(REPO_ROOT, "workspace", "flightcheck", "results.json")

mcp = FastMCP(
    "adk",
    instructions=(
        "ESS Maker Kit automation for Copilot Studio topic authoring, FlightCheck "
        "execution, and evaluation generation. Use these tools to create local "
        "artifacts in the active agent workspace and push them to Dataverse-backed "
        "Copilot Studio components."
    ),
)


class _LiteralSafeDumper(yaml.SafeDumper):
    """Safe dumper that emits multiline strings as YAML block scalars."""


class ADKServerError(RuntimeError):
    """Raised when the ADK server cannot complete the requested operation."""


class DataverseOperationError(ADKServerError):
    """Raised when a Dataverse create/update step fails."""


class _DataverseAuthHolder:
    """Mutable auth wrapper so 401s can refresh the access token in-place."""

    def __init__(self, env_url: str) -> None:
        self.env_url = env_url
        self.token = ""

    def acquire(self) -> str:
        with _repo_cwd():
            self.token = authenticate(self.env_url)
        return self.token

    def refresh(self) -> str:
        return self.acquire()


class _ComponentPushResult(dict):
    """Small dict subclass to make return payload construction clearer."""


def _represent_multiline_str(dumper: yaml.SafeDumper, value: str) -> yaml.nodes.ScalarNode:
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_LiteralSafeDumper.add_representer(str, _represent_multiline_str)


@contextmanager
def _repo_cwd() -> Iterator[None]:
    """Temporarily run relative-path helpers from the solution root."""
    previous = os.getcwd()
    try:
        os.chdir(REPO_ROOT)
        yield
    finally:
        os.chdir(previous)


def _load_runtime_config() -> dict[str, Any]:
    """Load the kit config and normalize the active agent entry."""
    try:
        with _repo_cwd():
            config = load_config()
    except SystemExit as exc:  # load_config prints and exits on user-facing errors.
        raise ADKServerError("Unable to load .local/config.json. Run /setup first.") from exc

    agent_config = _resolve_active_agent(config)
    config["activeAgentConfig"] = agent_config
    config["resolvedEnvUrl"] = _get_env_url(config)
    return config


def _resolve_active_agent(config: dict[str, Any]) -> dict[str, Any]:
    """Resolve the active agent entry from backward-compatible config shapes."""
    active_slug = config.get("activeAgent")
    for candidate in config.get("agents", []):
        if isinstance(candidate, dict) and candidate.get("slug") == active_slug:
            return candidate

    agent = config.get("agent")
    if isinstance(agent, dict) and agent.get("folder"):
        return agent

    agents = config.get("agents", [])
    if agents and isinstance(agents[0], dict) and agents[0].get("folder"):
        return agents[0]

    raise ADKServerError("Active agent configuration is missing from .local/config.json.")


def _get_env_url(config: dict[str, Any]) -> str:
    env_url = config.get("dataverseEndpoint") or config.get("env_url") or config.get("envUrl")
    if not env_url:
        raise ADKServerError("No Dataverse environment URL found in .local/config.json.")
    return str(env_url)


def _resolve_agent_folder(agent_config: dict[str, Any]) -> str:
    folder = agent_config.get("folder")
    if not folder:
        raise ADKServerError("Active agent folder is missing from .local/config.json.")
    folder_path = os.path.join(REPO_ROOT, str(folder).replace("/", os.sep))
    if not os.path.isdir(folder_path):
        raise ADKServerError(f"Agent folder not found: {folder_path}")
    return folder_path


def _get_bot_id(agent_config: dict[str, Any]) -> str:
    bot_id = agent_config.get("botId") or agent_config.get("bot_id")
    if not bot_id:
        raise ADKServerError("Active agent bot ID is missing from .local/config.json.")
    return str(bot_id)


def _get_schema_name(agent_config: dict[str, Any]) -> str:
    schema_name = agent_config.get("schemaName") or agent_config.get("schema_name")
    if not schema_name:
        raise ADKServerError("Active agent schema name is missing from .local/config.json.")
    return str(schema_name)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    if not slug:
        raise ADKServerError("A non-empty name is required.")
    return slug


def _pascal_case(value: str) -> str:
    parts = re.findall(r"[A-Za-z0-9]+", value)
    if not parts:
        raise ADKServerError("A non-empty name is required.")
    return "".join(part[:1].upper() + part[1:] for part in parts)


def _title_case(value: str) -> str:
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    return " ".join(part.capitalize() for part in re.split(r"[-_\s]+", expanded) if part)


def _dump_yaml(data: dict[str, Any]) -> str:
    """Serialize a Python object into readable YAML for Copilot Studio files."""
    return yaml.dump(
        data,
        Dumper=_LiteralSafeDumper,
        sort_keys=False,
        allow_unicode=True,
        width=1000,
        default_flow_style=False,
    )


def _atomic_write_text(path: str, text: str) -> None:
    """Write text via sibling tmp file to avoid partial writes."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError:
            pass
    os.replace(tmp_path, path)


def _load_component_map(agent_folder: str) -> dict[str, Any]:
    map_path = os.path.join(agent_folder, ".component-map.json")
    if not os.path.exists(map_path):
        return {}
    with open(map_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _save_component_map(agent_folder: str, component_map: dict[str, Any]) -> None:
    map_path = os.path.join(agent_folder, ".component-map.json")
    _atomic_write_text(map_path, json.dumps(component_map, indent=2))


def _call_dataverse_with_refresh(auth: _DataverseAuthHolder, operation: Any, *args: Any, **kwargs: Any) -> Any:
    """Run a Dataverse helper and retry once after refreshing the token on 401."""
    try:
        return operation(*args, **kwargs)
    except AuthExpiredError:
        auth.refresh()
        refreshed_args = list(args)
        if len(refreshed_args) >= 2:
            refreshed_args[1] = auth.token
        return operation(*refreshed_args, **kwargs)


def _connector_output_binding_key(connector: str) -> str:
    normalized = re.sub(r"[^a-z0-9]", "", connector.lower())
    if normalized.startswith("workday"):
        return "workdayResponse"
    if normalized.startswith("servicenow"):
        return "ServiceNowData"
    return "systemResponse"


def _build_topic_yaml(topic_name: str, description: str, connector: str, trigger_phrases: list[str], schema_name: str) -> str:
    connector_pascal = _pascal_case(connector)
    topic_pascal = _pascal_case(topic_name)
    connector_response_key = _connector_output_binding_key(connector)
    model_description = f"{description.strip()}\n\nDo NOT trigger for unrelated scenarios."
    parameter_binding = '="{""params"":[{""key"":""{Employee_ID}"",""value"":""" & Global.ESS_UserContext_Employee_Id & """}]}"'

    payload = {
        "kind": "AdaptiveDialog",
        "modelDescription": model_description,
        "beginDialog": {
            "kind": "OnRecognizedIntent",
            "id": "main",
            "intent": {
                "triggerQueries": [phrase.strip() for phrase in trigger_phrases if phrase.strip()],
            },
            "actions": [
                {
                    "kind": "SetVariable",
                    "id": "set_intro_msg",
                    "variable": "Topic.introMsg",
                    "value": '="Let me look that up for you."',
                },
                {
                    "kind": "SendActivity",
                    "id": "intro",
                    "activity": "{Topic.introMsg}",
                },
                {
                    "kind": "BeginDialog",
                    "id": "call_system",
                    "displayName": f"Call {connector_pascal} system execution",
                    "input": {
                        "binding": {
                            "parameters": parameter_binding,
                            "scenarioName": f"msdyn_{topic_pascal}",
                        }
                    },
                    "dialog": f"{schema_name}.topic.{connector_pascal}SystemGetCommonExecution",
                    "output": {
                        "binding": {
                            "errorResponse": "Topic.errorResponse",
                            "isSuccess": "Topic.isSuccess",
                            connector_response_key: "Topic.systemResponse",
                        }
                    },
                },
                {
                    "kind": "ConditionGroup",
                    "id": "handle_result",
                    "conditions": [
                        {
                            "id": "success",
                            "condition": "=Topic.isSuccess = true",
                            "actions": [
                                {
                                    "kind": "AnswerQuestionWithAI",
                                    "id": "format_response",
                                    "autoSend": True,
                                    "variable": "Topic.FormattedResponse",
                                    "userInput": "=Topic.systemResponse",
                                    "additionalInstructions": (
                                        "Format the response in a friendly way and tie it back "
                                        "to the user's original question."
                                    ),
                                }
                            ],
                        }
                    ],
                    "elseActions": [
                        {
                            "kind": "SendActivity",
                            "id": "error_msg",
                            "activity": f"I wasn't able to retrieve that information right now. Please try again or check directly in {connector}.",
                        }
                    ],
                },
            ],
        },
        "inputType": {},
        "outputType": {},
    }
    return _dump_yaml(payload)


def _topic_rel_path(topic_slug: str) -> str:
    return os.path.join("topics", f"{topic_slug}.mcs.yml").replace("\\", "/")


def _eval_rel_path(file_stem: str) -> str:
    return os.path.join("evaluations", f"{file_stem}.mcs.yml").replace("\\", "/")


def _build_component_map_entry(component_id: str, schemaname: str, component_type: int, name: str, parent_id: str | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "botcomponentid": component_id,
        "schemaname": schemaname,
        "componenttype": component_type,
        "name": name,
    }
    if parent_id:
        entry["parentbotcomponentid"] = parent_id
    return entry


def _push_botcomponent(
    *,
    env_url: str,
    auth: _DataverseAuthHolder,
    component_map: dict[str, Any],
    agent_folder: str,
    rel_path: str,
    content: str,
    bot_id: str,
    schemaname: str,
    display_name: str,
    component_type: int,
    parent_component_id: str | None = None,
) -> _ComponentPushResult:
    """Create or update a botcomponent record and persist the component map."""
    existing = component_map.get(rel_path)
    record_data: dict[str, Any] = {
        "componenttype": component_type,
        "data": content,
        "schemaname": schemaname,
        "name": display_name,
        "parentbotid@odata.bind": f"/bots({bot_id})",
    }
    if parent_component_id:
        record_data["ParentBotComponentId@odata.bind"] = f"/botcomponents({parent_component_id})"

    try:
        if existing and existing.get("botcomponentid"):
            component_id = str(existing["botcomponentid"])
            _call_dataverse_with_refresh(
                auth,
                update_record,
                env_url,
                auth.token,
                "botcomponents",
                component_id,
                record_data,
            )
            action = "updated"
        else:
            component_id = str(
                _call_dataverse_with_refresh(
                    auth,
                    create_record,
                    env_url,
                    auth.token,
                    "botcomponents",
                    record_data,
                )
            )
            action = "created"
    except Exception as exc:  # pragma: no cover - depends on live Dataverse.
        raise DataverseOperationError(f"Failed to push {rel_path} to Dataverse: {exc}") from exc

    component_map[rel_path] = _build_component_map_entry(
        component_id=component_id,
        schemaname=schemaname,
        component_type=component_type,
        name=display_name,
        parent_id=parent_component_id,
    )
    _save_component_map(agent_folder, component_map)

    return _ComponentPushResult(
        componentId=component_id,
        action=action,
        relativePath=rel_path,
    )


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _extract_topic_trigger_queries(topic_data: dict[str, Any]) -> list[str]:
    begin_dialog = topic_data.get("beginDialog") or {}
    intent = begin_dialog.get("intent") or {}
    trigger_queries = intent.get("triggerQueries") or []
    return [str(query).strip() for query in trigger_queries if str(query).strip()]


def _topic_matches_filter(file_stem: str, requested_topic_name: str | None) -> bool:
    if not requested_topic_name:
        return True
    normalized_requested = {_slugify(requested_topic_name), _pascal_case(requested_topic_name).lower(), requested_topic_name.lower()}
    return file_stem.lower() in normalized_requested or _pascal_case(file_stem).lower() in normalized_requested


def _build_expected_output(topic_name: str, connector: str, description: str) -> str:
    first_sentence = _normalize_text(description.split("\n\n", 1)[0])
    if not first_sentence:
        first_sentence = f"Handle the {topic_name} scenario."
    return (
        f"The agent should trigger the {topic_name} topic, retrieve the requested information from {connector}, "
        f"and respond helpfully. Context: {first_sentence}"
    )


def _generate_paraphrases(trigger_query: str) -> list[str]:
    """Create lightweight deterministic paraphrases for trigger testing."""
    base = trigger_query.strip().rstrip("?.!")
    if not base:
        return []

    candidates = [
        base,
        f"can you {base}",
        f"please {base}",
        f"help me {base}",
        f"I need to {base}",
    ]

    rewritten = base.replace(" my ", " my current ")
    if rewritten != base:
        candidates.append(rewritten)

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = _normalize_text(candidate).rstrip("?.!")
        if not normalized:
            continue
        prompt = normalized if normalized.endswith("?") else f"{normalized}?"
        key = prompt.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(prompt)
    return unique[:4]


def _build_eval_set_yaml() -> str:
    return _dump_yaml(
        {
            "kind": "EvaluationSet",
            "graders": [{"kind": "GeneralQualityGrader"}],
        }
    )


def _build_eval_data_yaml(rows: list[dict[str, str]], display_order: int) -> str:
    return _dump_yaml(
        {
            "kind": "EvaluationData",
            "rows": rows,
            "extensionData": {"displayOrder": str(display_order)},
        }
    )


def _read_topic_files(agent_folder: str) -> list[tuple[str, dict[str, Any]]]:
    topics_folder = os.path.join(agent_folder, "topics")
    if not os.path.isdir(topics_folder):
        raise ADKServerError(f"Topics folder not found: {topics_folder}")

    topics: list[tuple[str, dict[str, Any]]] = []
    for file_name in sorted(os.listdir(topics_folder)):
        if not file_name.endswith(".mcs.yml"):
            continue
        file_path = os.path.join(topics_folder, file_name)
        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                parsed = yaml.safe_load(handle) or {}
        except yaml.YAMLError as exc:
            raise ADKServerError(f"Failed to parse topic YAML: {file_path}: {exc}") from exc
        if not isinstance(parsed, dict):
            continue
        topics.append((os.path.splitext(os.path.splitext(file_name)[0])[0], parsed))
    return topics


@mcp.tool()
async def create_topic(
    topic_name: str,
    description: str,
    connector: str,
    trigger_phrases: list[str],
) -> dict[str, Any]:
    """Create a new ESS topic locally and push it to Copilot Studio."""
    if not topic_name.strip():
        raise ADKServerError("topic_name is required.")
    if not description.strip():
        raise ADKServerError("description is required.")
    cleaned_triggers = [phrase.strip() for phrase in trigger_phrases if phrase and phrase.strip()]
    if not cleaned_triggers:
        raise ADKServerError("At least one trigger phrase is required.")

    config = _load_runtime_config()
    agent_config = config["activeAgentConfig"]
    env_url = str(config["resolvedEnvUrl"])
    agent_folder = _resolve_agent_folder(agent_config)
    bot_id = _get_bot_id(agent_config)
    schema_name = _get_schema_name(agent_config)

    topic_slug = _slugify(topic_name)
    topic_pascal = _pascal_case(topic_name)
    rel_path = _topic_rel_path(topic_slug)
    file_path = os.path.join(agent_folder, rel_path.replace("/", os.sep))
    component_map = _load_component_map(agent_folder)

    if os.path.exists(file_path) or rel_path in component_map:
        raise ADKServerError(f"Topic already exists: {rel_path}")

    yaml_content = _build_topic_yaml(topic_name, description, connector, cleaned_triggers, schema_name)
    _atomic_write_text(file_path, yaml_content)

    try:
        auth = _DataverseAuthHolder(env_url)
        auth.acquire()
        push_result = _push_botcomponent(
            env_url=env_url,
            auth=auth,
            component_map=component_map,
            agent_folder=agent_folder,
            rel_path=rel_path,
            content=yaml_content,
            bot_id=bot_id,
            schemaname=f"{schema_name}.topic.{topic_pascal}",
            display_name=_title_case(topic_name),
            component_type=9,
        )
        pushed = True
        component_id = push_result["componentId"]
        error = None
    except Exception as exc:  # pragma: no cover - depends on live Dataverse.
        pushed = False
        component_id = None
        error = str(exc)

    result = {
        "topicName": topic_pascal,
        "filePath": file_path,
        "connector": connector,
        "pushedToCopilotStudio": pushed,
        "componentId": component_id,
    }
    if error:
        result["error"] = error
    return result


@mcp.tool()
async def run_flightcheck(scope: str = "full") -> dict[str, Any]:
    """Execute FlightCheck and return the generated results.json payload."""
    command = [sys.executable, os.path.join("scripts", "flightcheck", "cli.py"), "--scope", scope]
    if not sys.executable:
        raise ADKServerError("Python executable could not be resolved for FlightCheck.")

    with _repo_cwd():
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=1800,
            cwd=REPO_ROOT,
        )

    if not os.path.exists(FLIGHTCHECK_RESULTS_PATH):
        raise ADKServerError(
            "FlightCheck did not produce workspace/flightcheck/results.json. "
            f"stdout: {completed.stdout[-4000:]} stderr: {completed.stderr[-4000:]}"
        )

    with open(FLIGHTCHECK_RESULTS_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


@mcp.tool()
async def generate_eval(
    topic_name: str | None = None,
    categories: list[str] | None = None,
) -> dict[str, Any]:
    """Generate evaluation files from local topic trigger phrases and push them."""
    config = _load_runtime_config()
    agent_config = config["activeAgentConfig"]
    env_url = str(config["resolvedEnvUrl"])
    agent_folder = _resolve_agent_folder(agent_config)
    bot_id = _get_bot_id(agent_config)

    requested_categories = [category.strip() for category in (categories or ["topic-triggering"]) if category and category.strip()]
    if not requested_categories:
        raise ADKServerError("At least one evaluation category is required.")

    component_map = _load_component_map(agent_folder)
    auth = _DataverseAuthHolder(env_url)
    auth.acquire()

    generated_paths: list[str] = []
    test_case_count = 0
    eval_set_count = 0
    pushed = True
    errors: list[str] = []

    all_topics = _read_topic_files(agent_folder)
    matching_topics = [
        (file_stem, topic_data)
        for file_stem, topic_data in all_topics
        if _topic_matches_filter(file_stem, topic_name)
    ]

    if topic_name and not matching_topics:
        raise ADKServerError(f"No topic matched '{topic_name}'.")

    if not matching_topics:
        raise ADKServerError("No topics were found to evaluate.")

    for category in requested_categories:
        parent_rel_path = _eval_rel_path(category)
        parent_abs_path = os.path.join(agent_folder, parent_rel_path.replace("/", os.sep))
        parent_yaml = _build_eval_set_yaml()
        _atomic_write_text(parent_abs_path, parent_yaml)
        generated_paths.append(parent_abs_path)

        eval_set_count += 1
        try:
            parent_existing = component_map.get(parent_rel_path)
            parent_schema = str(parent_existing.get("schemaname") if isinstance(parent_existing, dict) else "") or f"mspva_{uuid.uuid4()}"
            parent_result = _push_botcomponent(
                env_url=env_url,
                auth=auth,
                component_map=component_map,
                agent_folder=agent_folder,
                rel_path=parent_rel_path,
                content=parent_yaml,
                bot_id=bot_id,
                schemaname=parent_schema,
                display_name=_title_case(category),
                component_type=19,
            )
            parent_component_id = str(parent_result["componentId"])
        except Exception as exc:  # pragma: no cover - depends on live Dataverse.
            pushed = False
            parent_component_id = ""
            errors.append(str(exc))

        display_order = int(time.time() * 1000)
        for file_stem, topic_data in matching_topics:
            trigger_queries = _extract_topic_trigger_queries(topic_data)
            if not trigger_queries:
                continue

            topic_description = str(topic_data.get("modelDescription") or "")
            connector = "ESS"
            for action in (topic_data.get("beginDialog") or {}).get("actions", []):
                if not isinstance(action, dict):
                    continue
                dialog_name = str(action.get("dialog") or "")
                match = re.search(r"\.topic\.([A-Za-z0-9]+)System", dialog_name)
                if match:
                    connector = match.group(1)
                    break
            expected_output = _build_expected_output(_title_case(file_stem), connector, topic_description)

            rows: list[dict[str, str]] = []
            for trigger_query in trigger_queries:
                for prompt in _generate_paraphrases(trigger_query):
                    rows.append(
                        {
                            "source": "Imported",
                            "input": prompt,
                            "expectedOutput": expected_output,
                        }
                    )
            if not rows:
                continue

            child_stem = f"{category}-{_slugify(file_stem)}"
            child_rel_path = _eval_rel_path(child_stem)
            child_abs_path = os.path.join(agent_folder, child_rel_path.replace("/", os.sep))
            child_yaml = _build_eval_data_yaml(rows, display_order)
            display_order += 1
            _atomic_write_text(child_abs_path, child_yaml)
            generated_paths.append(child_abs_path)
            test_case_count += len(rows)

            if not parent_component_id:
                pushed = False
                continue

            try:
                child_existing = component_map.get(child_rel_path)
                child_schema = str(child_existing.get("schemaname") if isinstance(child_existing, dict) else "") or f"mspva_{uuid.uuid4()}"
                _push_botcomponent(
                    env_url=env_url,
                    auth=auth,
                    component_map=component_map,
                    agent_folder=agent_folder,
                    rel_path=child_rel_path,
                    content=child_yaml,
                    bot_id=bot_id,
                    schemaname=child_schema,
                    display_name=_title_case(child_stem),
                    component_type=19,
                    parent_component_id=parent_component_id,
                )
            except Exception as exc:  # pragma: no cover - depends on live Dataverse.
                pushed = False
                errors.append(str(exc))

    if test_case_count == 0:
        raise ADKServerError("No trigger queries were found for the selected topics.")

    result: dict[str, Any] = {
        "evalSetCount": eval_set_count,
        "testCaseCount": test_case_count,
        "filePaths": generated_paths,
        "pushedToCopilotStudio": pushed,
    }
    if errors:
        result["errors"] = errors
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", choices=["stdio", "sse", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8101)
    args = parser.parse_args()
    if args.transport == "sse":
        # mcp v1.27+ uses positional transport arg; host/port via env or uvicorn
        import uvicorn
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.routing import Mount, Route

        sse = SseServerTransport("/messages/")

        async def handle_sse(request):
            async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
                await mcp._mcp_server.run(streams[0], streams[1], mcp._mcp_server.create_initialization_options())

        starlette_app = Starlette(routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ])
        uvicorn.run(starlette_app, host=args.host, port=args.port)
    else:
        mcp.run()
