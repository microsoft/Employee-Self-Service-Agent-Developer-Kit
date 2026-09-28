# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Real-model evaluation harness with synthetic curator files and commands."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import subprocess
from typing import Any

from jsonschema import ValidationError, validate


REPO_ROOT = Path(__file__).parents[3]
SOLUTION_ROOT = REPO_ROOT / "solutions" / "ess-maker-skills"
PROMPT_PATH = SOLUTION_ROOT / ".github" / "prompts" / "evaluate.prompt.md"
DISPATCHER_PATH = SOLUTION_ROOT / "src" / "skills" / "evaluations" / "dispatcher" / "SKILL.md"
WRAPPER_PATH = SOLUTION_ROOT / "src" / "skills" / "evaluations" / "curate" / "SKILL.md"
REAL_CURATOR_PATH = (
    SOLUTION_ROOT / "vendor" / "evals-curator" / "skills" / "curate-evals" / "SKILL.md"
)
VALIDATOR_SKILL_PATH = (
    SOLUTION_ROOT / "src" / "skills" / "evaluations" / "validate" / "SKILL.md"
)
QUALITY_FIX_FLOW_FILE = (
    SOLUTION_ROOT / "src" / "skills" / "evaluations" / "quality-fix-flow.md"
)
UPDATE_SKILL_FILE = (
    SOLUTION_ROOT / "src" / "skills" / "evaluations" / "update" / "SKILL.md"
)

SYNTHETIC_REPO_ROOT = REPO_ROOT / ".synthetic-eval-repo"
SYNTHETIC_SOLUTION_ROOT = SYNTHETIC_REPO_ROOT / "solutions" / "ess-maker-skills"
EVALUATE_PROMPT_PATH = ".github/prompts/evaluate.prompt.md"
DISPATCHER_SKILL_PATH = "src/skills/evaluations/dispatcher/SKILL.md"
WRAPPER_SKILL_PATH = "src/skills/evaluations/curate/SKILL.md"
CURATOR_SKILL_PATH = "vendor/evals-curator/skills/curate-evals/SKILL.md"
STRUCTURAL_VALIDATOR_PATH = "vendor/evals-curator/scripts/check_eval_artifacts.py"
KNOWLEDGE_PATH = "fixtures/knowledge/leave-policy.md"
AGENT_INSTRUCTIONS_PATH = "fixtures/agent/instructions.md"
MAKER_VALIDATOR_SKILL_PATH = "src/skills/evaluations/validate/SKILL.md"
QUALITY_FIX_FLOW_PATH = "src/skills/evaluations/quality-fix-flow.md"
UPDATE_SKILL_PATH = "src/skills/evaluations/update/SKILL.md"
SYNTHETIC_SOLUTION_PATH_KEYS = (
    EVALUATE_PROMPT_PATH,
    DISPATCHER_SKILL_PATH,
    WRAPPER_SKILL_PATH,
    CURATOR_SKILL_PATH,
    STRUCTURAL_VALIDATOR_PATH,
    KNOWLEDGE_PATH,
    AGENT_INSTRUCTIONS_PATH,
    MAKER_VALIDATOR_SKILL_PATH,
    QUALITY_FIX_FLOW_PATH,
    UPDATE_SKILL_PATH,
    "scripts/eval_curator_submodule.py",
    "scripts/evaluate_evals.py",
    "scripts/push.py",
)
DEFAULT_MODEL = "gpt-5.4"
MAX_CALLS = 40
TURN_TIMEOUT = 120

KNOWLEDGE_TEXT = """# Leave policy

## Annual leave

Employees receive 20 days of annual leave each calendar year. Up to 5 unused
days carry into the next calendar year and must be used by March 31.

## Sick leave

Employees should notify their manager before the start of the workday when
they need sick leave. A medical certificate is required after three
consecutive sick days.
"""

AGENT_INSTRUCTIONS_TEXT = """# HR policy assistant

Answer only questions about the supplied HR policies. Use a concise,
professional, and empathetic tone. If the supplied policy does not contain
the answer, say that the information is unavailable and offer to connect the
employee with HR. Do not provide legal advice or invent policy details.
"""


@dataclass(frozen=True)
class ToolContract:
    name: str
    description: str
    parameters: dict[str, Any]


def tool_contracts() -> list[ToolContract]:
    return [
        ToolContract(
            "read_file",
            (
                "Read one complete synthetic workspace file. Available files include "
                "the curator contract paths, sample knowledge, sample agent instructions, "
                "and Maker Kit validator skill."
            ),
            {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        ),
        ToolContract(
            "write_file",
            (
                "Record a requested synthetic workspace file write. Only paths beneath "
                "workspace/evaluations are accepted; no host file is changed."
            ),
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        ),
        ToolContract(
            "run_command",
            (
                "Record and simulate only the curator preflight, returned structural "
                "validator, Maker Kit evaluation validator, and scoped push commands. "
                "No command, network request, tenant operation, or push is executed."
            ),
            {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
                "additionalProperties": False,
            },
        ),
    ]


@dataclass
class RecordedCall:
    turn: int
    name: str
    arguments: dict[str, Any]
    result: Any
    failed: bool = False
    kind: str = "other"
    validator_type: str | None = None


@dataclass
class FakeEvaluationWorkspace:
    calls: list[RecordedCall] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)
    turn: int = 0
    limit_exceeded: bool = False
    contract_by_name: dict[str, ToolContract] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.files.update(
            {
                EVALUATE_PROMPT_PATH: PROMPT_PATH.read_text(encoding="utf-8"),
                DISPATCHER_SKILL_PATH: DISPATCHER_PATH.read_text(encoding="utf-8"),
                WRAPPER_SKILL_PATH: WRAPPER_PATH.read_text(encoding="utf-8"),
                CURATOR_SKILL_PATH: REAL_CURATOR_PATH.read_text(encoding="utf-8"),
                KNOWLEDGE_PATH: KNOWLEDGE_TEXT,
                AGENT_INSTRUCTIONS_PATH: AGENT_INSTRUCTIONS_TEXT,
                MAKER_VALIDATOR_SKILL_PATH: VALIDATOR_SKILL_PATH.read_text(
                    encoding="utf-8"
                ),
                QUALITY_FIX_FLOW_PATH: QUALITY_FIX_FLOW_FILE.read_text(encoding="utf-8"),
                UPDATE_SKILL_PATH: UPDATE_SKILL_FILE.read_text(encoding="utf-8"),
            }
        )

    def invoke(self, name: str, arguments: dict[str, Any]) -> RecordedCall:
        if len(self.calls) >= MAX_CALLS:
            self.limit_exceeded = True
            raise RuntimeError(f"Evaluation exceeded the {MAX_CALLS}-tool-call limit.")
        try:
            validate(arguments, self.contract_by_name[name].parameters)
        except (KeyError, ValidationError):
            return self._record(
                name, arguments, {"error": "Invalid tool invocation."}, failed=True
            )

        if name == "read_file":
            path = self._normalize(arguments["path"])
            file_key = self._matching_file_key(path)
            if file_key is None:
                return self._record(
                    name, arguments, {"error": "Synthetic file not found."}, failed=True
                )
            return self._record(name, arguments, self.files[file_key], kind="read")

        if name == "write_file":
            path = self._normalize(arguments["path"])
            if (
                ".." in PurePosixPath(path).parts
                or not path.startswith("workspace/evaluations/")
                or path.endswith("/")
            ):
                return self._record(
                    name,
                    arguments,
                    {"error": "Writes are restricted to workspace/evaluations."},
                    failed=True,
                    kind="write",
                )
            self.files[path] = arguments["content"]
            return self._record(
                name, arguments, {"path": path, "written": True}, kind="write"
            )

        return self._run_command(arguments)

    def _run_command(self, arguments: dict[str, Any]) -> RecordedCall:
        command = arguments["command"]
        normalized = command.replace("\\", "/")
        try:
            tokens = shlex.split(normalized, posix=True)
        except ValueError:
            return self._record(
                "run_command",
                arguments,
                {"exitCode": 2, "stderr": "Invalid command."},
                failed=True,
                kind="command",
            )
        cleaned = [token.strip("\"'") for token in tokens]
        preflight_index = self._matching_token_index(
            cleaned, "scripts/eval_curator_submodule.py"
        )

        if (
            preflight_index is not None
            and "status" in cleaned
            and cleaned.index("status") == preflight_index + 1
            and "--repo-root" in cleaned
        ):
            result = {
                "available": True,
                "schemaVersion": 1,
                "submoduleRoot": str(
                    SYNTHETIC_SOLUTION_ROOT / "vendor" / "evals-curator"
                ),
                "skillPath": str(SYNTHETIC_SOLUTION_ROOT / CURATOR_SKILL_PATH),
                "structuralValidatorPath": str(
                    SYNTHETIC_SOLUTION_ROOT / STRUCTURAL_VALIDATOR_PATH
                ),
                "defaultOutputRoot": "workspace/evaluations",
                "supportsHostOutputOverride": True,
                "supportsHostLifecycleHandoff": True,
            }
            return self._record(
                "run_command",
                arguments,
                {"exitCode": 0, "stdout": json.dumps(result)},
                kind="preflight",
            )

        if self._matching_token_index(cleaned, STRUCTURAL_VALIDATOR_PATH) is not None:
            evaluation_folder, error = self._validated_evaluation_folder(cleaned)
            if error is not None:
                return self._validation_failure(arguments, error, "structural")
            return self._record(
                "run_command",
                arguments,
                {
                    "exitCode": 0,
                    "stdout": "Structural validation passed.",
                    "evaluationFolder": evaluation_folder,
                },
                kind="structural_validation",
                validator_type="structural",
            )

        if self._matching_token_index(cleaned, "scripts/evaluate_evals.py") is not None:
            evaluation_folder, error = self._validated_evaluation_folder(cleaned)
            if error is not None:
                return self._validation_failure(arguments, error, "maker_kit")
            validator_read_index = self._last_matching_read_index(
                MAKER_VALIDATOR_SKILL_PATH
            )
            if validator_read_index is None:
                return self._validation_failure(
                    arguments,
                    "Maker validator skill must be read before Maker Kit validation.",
                    "maker_kit",
                )
            last_write_index = self._last_set_write_index(evaluation_folder)
            structural_index = self._last_structural_validation_index(
                evaluation_folder
            )
            if structural_index is None or (
                last_write_index is not None and structural_index < last_write_index
            ):
                return self._validation_failure(
                    arguments,
                    "Maker Kit validation requires structural validation for the "
                    "same evaluation set after its final write.",
                    "maker_kit",
                )
            missing_structural = [
                generated_folder
                for generated_folder in sorted(self.generated_set_folders())
                if not self._has_current_structural_validation(generated_folder)
            ]
            if missing_structural:
                return self._validation_failure(
                    arguments,
                    "Maker Kit validation requires successful structural validation "
                    "for every generated evaluation set after its latest write; "
                    f"missing {missing_structural}.",
                    "maker_kit",
                )
            return self._record(
                "run_command",
                arguments,
                {
                    "exitCode": 0,
                    "stdout": json.dumps(
                        {
                            "overallScore": 5,
                            "gate": "passed",
                            "flaggedCases": [],
                        }
                    ),
                    "evaluationFolder": evaluation_folder,
                },
                kind="maker_kit_validation",
                validator_type="maker_kit",
            )

        if self._matching_token_index(cleaned, "scripts/push.py") is not None:
            return self._record(
                "run_command",
                arguments,
                {"exitCode": 2, "stderr": "Synthetic pushes are disabled."},
                failed=True,
                kind="push",
            )

        return self._record(
            "run_command",
            arguments,
            {"exitCode": 2, "stderr": "Command is not available in this evaluation."},
            failed=True,
            kind="command",
        )

    @staticmethod
    def _normalize(path: str) -> str:
        return str(PurePosixPath(path.replace("\\", "/").removeprefix("./")))

    @classmethod
    def path_matches(cls, path: str, expected_key: str) -> bool:
        normalized_path = cls._normalize(path)
        normalized_key = cls._normalize(expected_key)
        repo_prefix = "solutions/ess-maker-skills/"
        if (
            ".." in PurePosixPath(normalized_path).parts
            or ".." in PurePosixPath(normalized_key).parts
        ):
            return False

        solution_key = (
            normalized_key.removeprefix(repo_prefix)
            if normalized_key.startswith(repo_prefix)
            else normalized_key
        )
        if solution_key not in SYNTHETIC_SOLUTION_PATH_KEYS:
            return False
        allowed_relative = {
            solution_key,
            f"{repo_prefix}{solution_key}",
        }
        allowed_absolute = cls._normalize(
            str(SYNTHETIC_SOLUTION_ROOT / solution_key)
        )
        return normalized_path in allowed_relative | {allowed_absolute}

    def _matching_file_key(self, path: str) -> str | None:
        return next(
            (
                file_key
                for file_key in self.files
                if self.path_matches(path, file_key)
            ),
            None,
        )

    @classmethod
    def _matching_token_index(
        cls, tokens: list[str], expected_suffix: str
    ) -> int | None:
        return next(
            (
                index
                for index, token in enumerate(tokens)
                if cls.path_matches(token, expected_suffix)
            ),
            None,
        )

    @classmethod
    def evaluation_folder_from_command(cls, command: str) -> str | None:
        try:
            tokens = shlex.split(command.replace("\\", "/"), posix=True)
        except ValueError:
            return None
        return cls._evaluation_folder_from_tokens(tokens)

    @classmethod
    def _evaluation_folder_from_tokens(cls, tokens: list[str]) -> str | None:
        option = "--evaluation-folder"
        for index, token in enumerate(tokens):
            cleaned = token.strip("\"'")
            if cleaned == option:
                if index + 1 >= len(tokens):
                    return None
                return cls._normalize(tokens[index + 1].strip("\"'"))
            if cleaned.startswith(f"{option}="):
                return cls._normalize(cleaned.removeprefix(f"{option}="))
        return None

    def generated_set_folders(self) -> set[str]:
        folders: set[str] = set()
        for call in self.calls:
            if call.name != "write_file" or call.failed:
                continue
            path = self._normalize(call.arguments["path"])
            if not path.endswith(".mcs.yml"):
                continue
            parts = PurePosixPath(path).parts
            if (
                len(parts) >= 4
                and parts[:2] == ("workspace", "evaluations")
                and parts[2] != "exports"
            ):
                folders.add("/".join(parts[:3]))
        return folders

    def _validated_evaluation_folder(
        self, tokens: list[str]
    ) -> tuple[str | None, str | None]:
        evaluation_folder = self._evaluation_folder_from_tokens(tokens)
        if evaluation_folder is None:
            return None, "Missing --evaluation-folder value."
        if ".." in PurePosixPath(evaluation_folder).parts:
            return None, "Evaluation folder cannot contain parent traversal."

        generated_folders = self.generated_set_folders()
        matching_folder = next(
            (
                generated_folder
                for generated_folder in generated_folders
                if evaluation_folder
                in {
                    generated_folder,
                    self._normalize(
                        str(SYNTHETIC_REPO_ROOT / generated_folder)
                    ),
                }
            ),
            None,
        )
        if matching_folder is None:
            return (
                None,
                "Validator must target one of the generated evaluation set folders "
                f"{sorted(generated_folders)}; got {evaluation_folder}.",
            )
        return matching_folder, None

    def _last_set_write_index(self, evaluation_folder: str) -> int | None:
        folder_prefix = f"{evaluation_folder}/"
        return next(
            (
                index
                for index in range(len(self.calls) - 1, -1, -1)
                if self.calls[index].name == "write_file"
                and not self.calls[index].failed
                and self._normalize(
                    self.calls[index].arguments["path"]
                ).startswith(folder_prefix)
                and self._normalize(
                    self.calls[index].arguments["path"]
                ).endswith(".mcs.yml")
            ),
            None,
        )

    def _last_structural_validation_index(
        self, evaluation_folder: str
    ) -> int | None:
        return next(
            (
                index
                for index in range(len(self.calls) - 1, -1, -1)
                if self.calls[index].kind == "structural_validation"
                and not self.calls[index].failed
                and self.calls[index].result.get("evaluationFolder")
                == evaluation_folder
            ),
            None,
        )

    def _has_current_structural_validation(self, evaluation_folder: str) -> bool:
        last_write_index = self._last_set_write_index(evaluation_folder)
        structural_index = self._last_structural_validation_index(evaluation_folder)
        return structural_index is not None and (
            last_write_index is None or structural_index > last_write_index
        )

    def maker_validation_ordering_violations(self) -> list[str]:
        generated_folders = sorted(self.generated_set_folders())
        final_write_indices = {
            folder: self._last_set_write_index(folder) for folder in generated_folders
        }
        violations: list[str] = []
        for attempt_index, call in enumerate(self.calls):
            if call.validator_type != "maker_kit":
                continue
            missing_structural = [
                folder
                for folder in generated_folders
                if not any(
                    structural_index < attempt_index
                    and structural_call.validator_type == "structural"
                    and not structural_call.failed
                    and structural_call.result.get("evaluationFolder") == folder
                    and (
                        final_write_indices[folder] is None
                        or structural_index > final_write_indices[folder]
                    )
                    for structural_index, structural_call in enumerate(self.calls)
                )
            ]
            if missing_structural:
                violations.append(
                    "Maker Kit validation attempt at call "
                    f"{attempt_index} occurred before current structural validation "
                    f"for every generated set; missing {missing_structural}."
                )
        return violations

    def _last_matching_read_index(self, expected_key: str) -> int | None:
        return next(
            (
                index
                for index in range(len(self.calls) - 1, -1, -1)
                if self.calls[index].name == "read_file"
                and not self.calls[index].failed
                and self.path_matches(
                    self.calls[index].arguments["path"], expected_key
                )
            ),
            None,
        )

    def _validation_failure(
        self, arguments: dict[str, Any], message: str, validator_type: str
    ) -> RecordedCall:
        return self._record(
            "run_command",
            arguments,
            {"exitCode": 2, "stderr": message},
            failed=True,
            kind="validation",
            validator_type=validator_type,
        )

    def _record(
        self,
        name: str,
        arguments: dict[str, Any],
        result: Any,
        *,
        failed: bool = False,
        kind: str = "other",
        validator_type: str | None = None,
    ) -> RecordedCall:
        call = RecordedCall(
            self.turn,
            name,
            deepcopy(arguments),
            deepcopy(result),
            failed,
            kind,
            validator_type,
        )
        self.calls.append(call)
        return call


@dataclass(frozen=True)
class EvalTurn:
    prompt: str


@dataclass(frozen=True)
class EvalResult:
    replies: list[str]
    trace_path: Path


def _github_token() -> str:
    __tracebackhide__ = True
    result = subprocess.run(
        ["gh", "auth", "token"],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError("Skill evals require an authenticated gh CLI with Copilot access.")
    return result.stdout.strip()


def session_options(
    model: str, tools: list[Any], available_tools: Any, directory: Path
) -> dict[str, Any]:
    instructions = "\n\n".join(
        path.read_text(encoding="utf-8")
        for path in (PROMPT_PATH, DISPATCHER_PATH, WRAPPER_PATH)
    )
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
                "You are the ESS Maker Kit assistant in a synthetic evaluation. "
                "Follow the supplied Maker Kit instructions completely. Use only the "
                "provided tools. read_file exposes only synthetic contract, skill, "
                "knowledge, and agent-instruction data. write_file records writes "
                "without changing the host. run_command records validator calls but "
                "never executes commands or contacts a tenant. Do not push unless the "
                "maker gives a separate explicit push approval after all prior gates.\n\n"
                + instructions
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
                        reply = (
                            None
                            if getattr(event.data, "tool_requests", None)
                            else event.data.content
                        )
                if kind in {"assistant.turn_end", "session.idle"} and reply:
                    return reply
    except TimeoutError:
        await session.abort()
        raise
    finally:
        unsubscribe()


async def run_eval(
    backend: FakeEvaluationWorkspace,
    turns: list[EvalTurn],
    directory: Path,
) -> EvalResult:
    try:
        from copilot import ToolSet
        from copilot.tools import Tool, ToolResult
    except ImportError as error:
        raise RuntimeError(
            "Install the skill-eval extra: python -m pip install -e '.[test,skill-eval]'"
        ) from error

    model = os.environ.get("ESS_SKILL_EVAL_MODEL", DEFAULT_MODEL)
    contracts = tool_contracts()
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
        async with (
            asyncio.timeout(TURN_TIMEOUT * len(turns) + 60),
            model_client(directory) as client,
        ):
            async with await client.create_session(
                **session_options(model, tools, allowed, directory)
            ) as session:
                for index, turn in enumerate(turns):
                    backend.turn = index
                    reply = await send_turn(session, turn.prompt, events)
                    if backend.limit_exceeded:
                        raise RuntimeError(
                            f"Evaluation exceeded the {MAX_CALLS}-tool-call limit."
                        )
                    replies.append(reply)
    finally:
        trace_path.write_text(
            json.dumps(
                {
                    "model": model,
                    "wrapper_sha256": hashlib.sha256(WRAPPER_PATH.read_bytes()).hexdigest(),
                    "curator_sha256": hashlib.sha256(
                        REAL_CURATOR_PATH.read_bytes()
                    ).hexdigest(),
                    "tool_names": [contract.name for contract in contracts],
                    "turns": [turn.prompt for turn in turns],
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
