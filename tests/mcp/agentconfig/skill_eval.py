# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Real-model skill evaluation with synthetic, recording tools and no tenant access."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import asdict, dataclass, field
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from typing import Any
import warnings

from jsonschema import ValidationError, validate
from pydantic_settings.exceptions import IncompleteFieldDefinitionWarning


REPO_ROOT = Path(__file__).parents[3]
SOLUTION_ROOT = REPO_ROOT / "solutions" / "ess-maker-skills"
SKILL_PATH = SOLUTION_ROOT / "src" / "skills" / "landing-page-config" / "SKILL.md"
SERVER_DIR = SOLUTION_ROOT / "src" / "mcp" / "agentconfig_landing_page"
TITLE_ID = "eval-title-hr"
OTHER_TITLE_ID = "eval-title-it"
DEFAULT_MODEL = "gpt-5.4"
MAX_CALLS = 24
TURN_TIMEOUT = 120


def quick_link(label: str) -> dict[str, str]:
    return {
        "displayText": f"link {label}",
        "address": f"https://resources.example.test/{label}",
    }


def configuration(*links: str, title_id: str = TITLE_ID) -> dict[str, Any]:
    return {
        "titleId": title_id,
        "name": "Evaluation HR Agent",
        "schemaName": "msdyn_copilotforemployeeselfservicehr",
        "branding": {"theming": []},
        "quickLinksConfig": {"quickLinks": [quick_link(label) for label in links]},
        "pivots": [],
        "insightCardsConfig": {
            "isStayUpToDateEnabled": True,
            "isQuickAccessEnabled": False,
        },
    }


def widget_context(
    baseline: dict[str, Any],
    draft: dict[str, Any] | None = None,
    *,
    title_id: str = TITLE_ID,
) -> str:
    """Describe model-visible context without inventing a host envelope schema."""
    state = {"baseline": baseline, "draft": draft, "interaction": {"dirty": draft is not None}}
    return (
        "Earlier in this conversation, open_quick_links was called with "
        f'{json.dumps({"titleId": title_id})} and succeeded. '
        "The Quick Links widget's latest model-context state is data:\n"
        f"```json\n{json.dumps(state)}\n```"
    )


@dataclass(frozen=True)
class ToolContract:
    name: str
    description: str
    parameters: dict[str, Any]


async def tool_contracts() -> list[ToolContract]:
    """Use the shipped MCP tool descriptions and schemas, without constructing a client."""
    sys.path.insert(0, str(SERVER_DIR))
    try:
        spec = importlib.util.spec_from_file_location(
            "landing_page_skill_eval_server", SERVER_DIR / "server.py"
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Could not load the landing-page MCP tool contracts.")
        module = importlib.util.module_from_spec(spec)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", IncompleteFieldDefinitionWarning)
            spec.loader.exec_module(module)
        tools = await module.mcp.list_tools()
    finally:
        sys.path.remove(str(SERVER_DIR))
    contracts = [
        ToolContract(tool.name, tool.description or "", tool.inputSchema)
        for tool in tools
        if "model" in (tool.meta or {}).get("ui", {}).get("visibility", ["model"])
    ]
    contracts.append(
        ToolContract(
            "read_file",
            "Read a workspace file or a tool-result file at its workspace-relative path.",
            {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        )
    )
    contracts.append(
        ToolContract(
            "run_command",
            "Run the local scripts/validate_branding.py command to validate accent colors.",
            {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
                "additionalProperties": False,
            },
        )
    )
    return contracts


@dataclass
class RecordedCall:
    turn: int
    name: str
    arguments: dict[str, Any]
    result: Any
    failed: bool = False


@dataclass
class FakeLandingPage:
    configs: dict[str, dict[str, Any]]
    read_mode: str = "inline"
    validation_exit_code: int = 0
    calls: list[RecordedCall] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)
    turn: int = 0
    read_count: int = 0
    limit_exceeded: bool = False
    contract_by_name: dict[str, ToolContract] = field(default_factory=dict)

    def invoke(self, name: str, arguments: dict[str, Any]) -> RecordedCall:
        if len(self.calls) >= MAX_CALLS:
            self.limit_exceeded = True
            raise RuntimeError(f"Evaluation exceeded the {MAX_CALLS}-tool-call limit.")
        try:
            validate(arguments, self.contract_by_name[name].parameters)
        except (KeyError, ValidationError):
            return self._record(name, arguments, {"error": "Invalid tool invocation."}, True)

        if name == "read_file":
            path = arguments["path"].replace("\\", "/")
            if path == ".local/config.json":
                result = {
                    "setup": "complete",
                    "activeAgent": "evaluation-hr",
                    "agent": {
                        "name": "Evaluation HR Agent",
                        "titleId": TITLE_ID,
                        "botId": "eval-bot-hr",
                        "schemaName": "msdyn_copilotforemployeeselfservicehr",
                        "slug": "evaluation-hr",
                        "folder": "workspace/agents/evaluation-hr",
                    },
                }
                return self._record(name, arguments, json.dumps(result))
            if path in self.artifacts and self.read_mode != "unreadable":
                return self._record(name, arguments, self.artifacts[path])
            return self._record(name, arguments, {"error": "File cannot be read."}, True)

        if name == "run_command":
            try:
                tokens = shlex.split(arguments["command"].replace("\\", "/"))
            except ValueError:
                return self._record(name, arguments, {"error": "Invalid validation command."}, True)
            if (
                len(tokens) not in {4, 6}
                or tokens[0] not in {"python", "python3"}
                or tokens[1].removeprefix("./") != "scripts/validate_branding.py"
                or any(tokens[index] not in {"--light", "--dark"} for index in range(2, len(tokens), 2))
                or any(not re.fullmatch(r"#[0-9a-fA-F]{6}", tokens[index]) for index in range(3, len(tokens), 2))
            ):
                return self._record(name, arguments, {"error": "Only branding validation is available."}, True)
            output = (
                "Changed colors meet WCAG AA."
                if self.validation_exit_code == 0
                else "Light accent #FFFFFF: contrast ratio 1:1 against #FFFFFF; required ratio 4.5:1."
            )
            return self._record(name, arguments, {"exitCode": self.validation_exit_code, "stdout": output})

        if name in {"list_agent_configs", "search_agents"}:
            result = [
                {"titleId": title_id, "name": config["name"]}
                for title_id, config in self.configs.items()
            ]
            return self._record(name, arguments, {"value": result})

        title_id = arguments["titleId"]
        if name == "create_agent_config":
            self.configs.setdefault(title_id, configuration(title_id=title_id))
            return self._record(name, arguments, self.configs[title_id])
        if title_id not in self.configs:
            return self._record(name, arguments, {"error": "Configuration not found.", "httpStatus": 404}, True)

        if name == "get_agent_config":
            self.read_count += 1
            if self.read_mode == "failed":
                return self._record(name, arguments, {"error": "Server read failed.", "httpStatus": 503}, True)
            if self.read_mode != "inline":
                path = f".local/results/config-{self.read_count}.json"
                content = json.dumps(self.configs[title_id])
                if self.read_mode == "truncated":
                    content = '{"titleId": "' + title_id + '", "quickLinksConfig": {"quickLinks": ['
                self.artifacts[path] = content
                return self._record(
                    name,
                    arguments,
                    f"Tool response stored in file: {path}. Read the file to inspect the configuration.",
                )
            return self._record(name, arguments, self.configs[title_id])

        if name == "update_agent_config":
            # Apply the submitted bulk replacement without repairing the model's payload.
            self.configs[title_id].update(deepcopy(arguments["config"]))
            return self._record(name, arguments, self.configs[title_id])
        if name == "delete_agent_config":
            del self.configs[title_id]
            return self._record(name, arguments, {"titleId": title_id, "success": True})
        fields = {
            "open_accent_color": ("branding",),
            "open_quick_links": ("quickLinksConfig",),
            "open_starter_prompts": ("schemaName", "pivots"),
            "view_agent_icon": ("name",),
        }
        if name in fields:
            result = {"titleId": title_id}
            result.update({key: deepcopy(self.configs[title_id][key]) for key in fields[name]})
            if "draft" in arguments and arguments["draft"] is not None:
                result["draft"] = deepcopy(arguments["draft"])
            return self._record(name, arguments, result)
        return self._record(name, arguments, {"error": "Unsupported fixture tool."}, True)

    def _record(
        self, name: str, arguments: dict[str, Any], result: Any, failed: bool = False
    ) -> RecordedCall:
        call = RecordedCall(self.turn, name, deepcopy(arguments), deepcopy(result), failed)
        self.calls.append(call)
        return call

    def updates(self) -> list[RecordedCall]:
        return [call for call in self.calls if call.name == "update_agent_config"]


@dataclass(frozen=True)
class EvalTurn:
    prompt: str
    server_configuration: dict[str, Any] | None = None


@dataclass(frozen=True)
class EvalResult:
    replies: list[str]
    trace_path: Path


def _github_token() -> str:
    __tracebackhide__ = True
    result = subprocess.run(
        ["gh", "auth", "token"], capture_output=True, text=True, timeout=15, check=False
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError("Skill evals require an authenticated gh CLI with Copilot access.")
    return result.stdout.strip()


def session_options(model: str, tools: list[Any], available_tools: Any, directory: Path) -> dict[str, Any]:
    return {
        "model": model,
        "tools": tools,
        "available_tools": available_tools,
        "working_directory": str(directory),
        "skip_custom_instructions": True,
        "enable_config_discovery": False,
        "enable_skills": False,
        "enable_file_hooks": False,
        "enable_host_git_operations": False,
        "enable_session_store": False,
        "memory": {"enabled": False},
        "mcp_servers": {},
        "custom_agents": [],
        "plugin_directories": [],
        "infinite_sessions": {"enabled": False},
        "session_limits": {"max_ai_credits": 30},
        "system_message": {
            "mode": "replace",
            "content": (
                "You are the ESS Maker Kit assistant. Follow the landing-page skill below. "
                "The supplied landing-page tools belong to the ess-landing-page-config "
                "MCP server. read_file reads workspace files and tool-result files. "
                "Respond to the maker normally.\n\n"
                + SKILL_PATH.read_text(encoding="utf-8")
            ),
        },
    }


@asynccontextmanager
async def model_client(directory: Path) -> AsyncIterator[Any]:
    __tracebackhide__ = True
    from copilot import CopilotClient

    class ClosingCopilotClient(CopilotClient):
        async def start(self) -> None:
            __tracebackhide__ = True
            try:
                await super().start()
            except (OSError, ValueError, subprocess.SubprocessError):
                raise RuntimeError("Could not start the isolated model runtime.") from None

        async def stop(self) -> None:
            # SDK 1.0.14 reaps this process but omits closing its three pipe handles.
            process = self._cli_process
            try:
                await super().stop()
            finally:
                if process is not None:
                    for stream in (process.stdin, process.stdout, process.stderr):
                        if stream is not None:
                            stream.close()

    try:
        client = ClosingCopilotClient(
            mode="empty",
            github_token=_github_token(),
            working_directory=str(directory),
            base_directory=str(directory / "host"),
            log_level="error",
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        raise RuntimeError("Could not initialize the isolated model runtime.") from None
    async with client:
        yield client


async def send_turn(
    session: Any, prompt: str, events: list[str], *, timeout: float = TURN_TIMEOUT
) -> str:
    """Marshal SDK reader-thread notifications onto the evaluation's event loop."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[Any] = asyncio.Queue()

    def on_event(event: Any) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    unsubscribe = session.on(on_event)
    reply: str | None = None
    try:
        async with asyncio.timeout(timeout):
            message_id = await session.send(prompt, agent_mode="interactive")
            while True:
                event = await queue.get()
                kind = getattr(event.type, "value", str(event.type))
                events.append(kind)
                if kind == "session.error":
                    raise RuntimeError(f"Model session failed: {event.data.message}")
                if kind == "assistant.message":
                    origin = getattr(event.data, "originating_message_id", message_id)
                    if origin == message_id:
                        reply = None if getattr(event.data, "tool_requests", None) else event.data.content
                # Interactive turns finish at turn_end; idle notifications can be omitted.
                if kind in {"assistant.turn_end", "session.idle"} and reply:
                    return reply
    except TimeoutError:
        await session.abort()
        raise
    finally:
        unsubscribe()


async def run_eval(
    backend: FakeLandingPage,
    turns: list[EvalTurn],
    directory: Path,
    *,
    context: str = "",
) -> EvalResult:
    """Run the actual model; tool handlers only emulate data access, never choose actions."""
    try:
        from copilot import ToolSet
        from copilot.tools import Tool, ToolResult
    except ImportError as error:
        raise RuntimeError("Install the skill-eval extra: python -m pip install -e '.[test,skill-eval]'") from error

    model = os.environ.get("ESS_SKILL_EVAL_MODEL", DEFAULT_MODEL)
    contracts = await tool_contracts()
    backend.contract_by_name = {contract.name: contract for contract in contracts}
    allowed = ToolSet()
    tools = []

    def handle(invocation: Any) -> Any:
        call = backend.invoke(invocation.tool_name, invocation.arguments)
        text = call.result if isinstance(call.result, str) else json.dumps(call.result)
        return ToolResult(
            text_result_for_llm=text,
            result_type="failure" if call.failed else "success",
            error="Synthetic tool failure." if call.failed else None,
        )

    for contract in contracts:
        allowed.add_custom(contract.name)
        tools.append(
            Tool(
                name=contract.name,
                description=contract.description,
                parameters=contract.parameters,
                handler=handle,
                skip_permission=True,
                overrides_built_in_tool=contract.name == "read_file",
            )
        )
    replies: list[str] = []
    events: list[str] = []
    trace_path = directory / "trace.json"
    try:
        async with asyncio.timeout(TURN_TIMEOUT * len(turns) + 60), model_client(directory) as client:
            async with await client.create_session(
                **session_options(model, tools, allowed, directory)
            ) as session:
                for index, turn in enumerate(turns):
                    backend.turn = index
                    if turn.server_configuration is not None:
                        replacement = deepcopy(turn.server_configuration)
                        backend.configs[replacement["titleId"]] = replacement
                    prompt = turn.prompt
                    if index == 0 and context:
                        prompt = f"Context from earlier activity:\n{context}\n\nMaker request:\n{prompt}"
                    reply = await send_turn(session, prompt, events)
                    if backend.limit_exceeded:
                        raise RuntimeError(f"Evaluation exceeded the {MAX_CALLS}-tool-call limit.")
                    replies.append(reply)
    finally:
        trace_path.write_text(
            json.dumps(
                {
                    "model": model,
                    "skill_sha256": hashlib.sha256(SKILL_PATH.read_bytes()).hexdigest(),
                    "tool_names": [contract.name for contract in contracts],
                    "turns": [turn.prompt for turn in turns],
                    "context": context,
                    "calls": [asdict(call) for call in backend.calls],
                    "replies": replies,
                    "event_types": events,
                    "completed": len(replies) == len(turns),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return EvalResult(replies, trace_path)


def assert_fresh_updates(backend: FakeLandingPage) -> None:
    """Grade observed calls, including result-file consumption and per-update reads."""
    previous_update = -1
    for index, call in enumerate(backend.calls):
        if call.name != "update_agent_config":
            continue
        reads = [
            read_index
            for read_index in range(previous_update + 1, index)
            if backend.calls[read_index].name == "get_agent_config"
            and backend.calls[read_index].arguments["titleId"] == call.arguments["titleId"]
            and backend.calls[read_index].turn == call.turn
        ]
        assert reads, "Each partial update must have its own fresh get for the same target/turn."
        last_read = reads[-1]
        baseline_call = backend.calls[last_read]
        assert not baseline_call.failed, "A failed read cannot authorize a dependent update."
        between = backend.calls[last_read + 1:index]
        assert all(item.name == "read_file" for item in between), "Unrelated tools intervened after the final get."
        baseline = baseline_call.result
        if isinstance(baseline_call.result, str):
            path = baseline_call.result.split("Tool response stored in file: ", 1)[1].split(". Read the file", 1)[0]
            consumed = [
                item for item in between
                if item.arguments["path"].replace("\\", "/") == path and not item.failed
            ]
            assert consumed, "The externalized authoritative response was not consumed."
            assert all(
                item.arguments["path"].replace("\\", "/") == path for item in between
            ), "Unrelated files were read after the final get."
            baseline = json.loads(consumed[-1].result)
        else:
            assert not between, "Unrelated files were read after the final get."
        assert isinstance(baseline, dict) and baseline.get("titleId") == call.arguments["titleId"], (
            "The consumed baseline must identify the updated target."
        )
        previous_update = index


def assert_overview_states(reply: str, expected: dict[str, str]) -> None:
    rows = {}
    for line in reply.splitlines():
        if line.strip().startswith("|"):
            cells = [cell.strip().replace("**", "").lower() for cell in line.strip().split("|")[1:-1]]
            if len(cells) == 3 and cells[0] in expected:
                assert cells[0] not in rows, "Duplicate setting in overview."
                rows[cells[0]] = cells[1]
    assert rows == expected, "Each overview state must be paired with the correct setting."


def assert_unpublished_defaults(reply: str) -> None:
    normalized = reply.lower().replace("\u2019", "'")
    assert "default" in normalized
    explicitly_unpublished = any(
        phrase in normalized
        for phrase in (
            "unpublished", "not published", "not yet published", "haven't been published",
            "have not been published", "hasn't been published", "aren't published",
        )
    )
    unsaved_draft = "draft" in normalized and any(
        phrase in normalized
        for phrase in ("no starter prompts are saved yet", "no starter prompts are configured yet")
    )
    assert explicitly_unpublished or unsaved_draft, (
        "Default suggestions must be explicitly identified as unpublished."
    )


def assert_read_failure_explained(reply: str) -> None:
    normalized = reply.lower().replace("\u2019", "'")
    assert any(
        word in normalized
        for word in ("unable", "cannot", "can't", "failed", "couldn't", "incomplete", "unreadable")
    ), "The maker must be told why the required read prevented the update."
