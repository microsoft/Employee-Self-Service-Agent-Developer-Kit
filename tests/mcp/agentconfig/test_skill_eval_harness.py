# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Offline tests of the evaluation machinery, not of model compliance."""

from __future__ import annotations

import asyncio
import builtins
from copy import deepcopy
from dataclasses import replace
import importlib.util
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
import threading
import traceback
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
from mcp.server.fastmcp import FastMCP
import pytest

from tests.mcp.agentconfig import skill_eval as harness


@pytest.fixture(scope="module")
def contracts() -> dict[str, harness.ToolContract]:
    return {contract.name: contract for contract in asyncio.run(harness.tool_contracts())}


@pytest.fixture
def backend(contracts) -> harness.FakeLandingPage:
    return harness.FakeLandingPage(
        {
            harness.TITLE_ID: harness.configuration("existing", "newer"),
            harness.OTHER_TITLE_ID: harness.configuration("other", title_id=harness.OTHER_TITLE_ID),
        },
        contract_by_name=contracts,
        turn=1,
    )


def test_contracts_match_the_shipped_model_visible_tools(contracts, monkeypatch) -> None:
    shipped_tools = []
    list_tools = FastMCP.list_tools

    async def capture_tools(server):
        tools = await list_tools(server)
        shipped_tools.extend(tools)
        return tools

    client = Mock(side_effect=AssertionError("Contract discovery must not create a tenant client."))
    monkeypatch.setattr(sys.modules["client"], "AgentConfigClient", client)
    monkeypatch.setattr(FastMCP, "list_tools", capture_tools)
    actual = {contract.name: contract for contract in asyncio.run(harness.tool_contracts())}

    assert set(actual) == {
        "list_agent_configs", "search_agents", "create_agent_config",
        "get_agent_config", "update_agent_config", "delete_agent_config",
        "open_accent_color", "open_quick_links", "open_starter_prompts",
        "view_agent_icon", "read_file", "run_command",
    }
    assert any(tool.name == "report_client_events" for tool in shipped_tools)
    for tool in shipped_tools:
        if "model" in (tool.meta or {}).get("ui", {}).get("visibility", ["model"]):
            assert actual[tool.name] == harness.ToolContract(
                tool.name, tool.description, tool.inputSchema,
            )
        else:
            assert tool.name not in actual
    assert actual["read_file"].parameters == {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
        "additionalProperties": False,
    }
    client.assert_not_called()


@pytest.mark.parametrize(
    ("section", "replacement"),
    [
        ("quickLinksConfig", {"quickLinks": [harness.quick_link("replacement")]}),
        ("branding", {"theming": [{"name": "light", "accentColor": "#123456"}]}),
        ("pivots", []),
        ("insightCardsConfig", {"isStayUpToDateEnabled": False, "isQuickAccessEnabled": True}),
    ],
)
def test_updates_replace_complete_sections_verbatim(backend, section, replacement) -> None:
    backend.configs[harness.TITLE_ID]["branding"]["theming"] = [
        {"name": "light", "accentColor": "#ABCDEF"},
        {"name": "dark", "accentColor": "#FEDCBA"},
    ]
    backend.configs[harness.TITLE_ID]["pivots"] = [
        {
            "displayName": "HR",
            "conversationStarterPrompts": [{"title": "Benefits", "displayText": "Show my benefits"}],
        }
    ]
    before = deepcopy(backend.configs)
    arguments = {"titleId": harness.TITLE_ID, "config": {section: deepcopy(replacement)}}

    call = backend.invoke("update_agent_config", arguments)

    expected = deepcopy(before)
    expected[harness.TITLE_ID][section] = replacement
    assert not call.failed
    assert call.arguments == arguments
    assert call.result == expected[harness.TITLE_ID]
    assert backend.configs == expected
    assert backend.updates() == [call]
    arguments["config"].clear()
    call.result[section] = None
    assert backend.configs == expected
    assert call.arguments["config"] == {section: replacement}


def test_fake_update_does_not_repair_widget_only_fields_or_restore_omitted_links(backend) -> None:
    submitted = {
        "quickLinksConfig": {
            "quickLinks": [{**harness.quick_link("replacement"), "key": "widget-row-only"}],
        },
        "name": "Renamed evaluation agent",
    }
    before = deepcopy(backend.configs)

    call = backend.invoke("update_agent_config", {"titleId": harness.TITLE_ID, "config": submitted})

    assert not call.failed
    assert backend.configs[harness.TITLE_ID] == {**before[harness.TITLE_ID], **submitted}
    assert backend.configs[harness.OTHER_TITLE_ID] == before[harness.OTHER_TITLE_ID]
    assert call.arguments["config"] == submitted


def test_recorded_reads_are_snapshots_of_arguments_and_server_state(backend) -> None:
    arguments = {"titleId": harness.TITLE_ID}
    expected = deepcopy(backend.configs[harness.TITLE_ID])
    call = backend.invoke("get_agent_config", arguments)

    arguments["titleId"] = harness.OTHER_TITLE_ID
    backend.configs[harness.TITLE_ID]["quickLinksConfig"]["quickLinks"].clear()

    assert call.arguments == {"titleId": harness.TITLE_ID}
    assert call.result == expected
    assert call.turn == 1
    assert not call.failed


@pytest.mark.parametrize(
    ("name", "section", "draft"),
    [
        ("open_accent_color", "branding", {"branding": {"theming": []}}),
        ("open_quick_links", "quickLinksConfig", {"quickLinksConfig": {"quickLinks": []}}),
        ("open_starter_prompts", "pivots", {"pivots": []}),
    ],
)
def test_openers_expose_baseline_and_draft_without_applying_it(backend, name, section, draft) -> None:
    before = deepcopy(backend.configs)

    call = backend.invoke(name, {"titleId": harness.TITLE_ID, "draft": draft})

    assert not call.failed
    assert call.result["titleId"] == harness.TITLE_ID
    assert call.result[section] == before[harness.TITLE_ID][section]
    assert call.result["draft"] == draft
    assert backend.configs == before
    assert backend.updates() == []


def test_externalized_get_exposes_only_a_reference_until_the_artifact_is_read(backend) -> None:
    backend.read_mode = "externalized"
    expected = deepcopy(backend.configs[harness.TITLE_ID])
    call = backend.invoke("get_agent_config", {"titleId": harness.TITLE_ID})

    assert not call.failed
    assert call.result == (
        "Tool response stored in file: .local/results/config-1.json. "
        "Read the file to inspect the configuration."
    )
    backend.configs[harness.TITLE_ID]["quickLinksConfig"]["quickLinks"].clear()
    consumed = backend.invoke("read_file", {"path": r".local\results\config-1.json"})
    assert not consumed.failed
    assert json.loads(consumed.result) == expected

    latest = backend.invoke("get_agent_config", {"titleId": harness.TITLE_ID})
    assert "config-2.json" in latest.result
    assert json.loads(backend.artifacts[".local/results/config-2.json"]) == backend.configs[harness.TITLE_ID]
    assert json.loads(backend.artifacts[".local/results/config-1.json"]) == expected


@pytest.mark.parametrize("read_mode", ["failed", "unreadable", "truncated"])
def test_unavailable_reads_preserve_state_and_report_the_fixture_failure(backend, read_mode) -> None:
    backend.read_mode = read_mode
    before = deepcopy(backend.configs)
    call = backend.invoke("get_agent_config", {"titleId": harness.TITLE_ID})

    if read_mode == "failed":
        assert call.failed
        assert call.result == {"error": "Server read failed.", "httpStatus": 503}
        assert backend.artifacts == {}
    else:
        assert not call.failed
        assert "config-1.json" in call.result
        consumed = backend.invoke("read_file", {"path": r".local\results\config-1.json"})
        if read_mode == "unreadable":
            assert json.loads(backend.artifacts[".local/results/config-1.json"]) == before[harness.TITLE_ID]
            assert consumed.failed
            assert consumed.result == {"error": "File cannot be read."}
        else:
            assert not consumed.failed
            assert consumed.result == backend.artifacts[".local/results/config-1.json"]
            with pytest.raises(json.JSONDecodeError):
                json.loads(consumed.result)
    assert backend.configs == before
    assert backend.updates() == []


def test_fake_handlers_never_access_real_files_network_or_processes(backend, monkeypatch) -> None:
    forbidden = Mock(side_effect=AssertionError("Fake tools must remain in memory."))
    with monkeypatch.context() as guard:
        for owner, attribute in (
            (builtins, "open"), (io, "open"), (Path, "read_text"), (Path, "read_bytes"),
            (httpx.Client, "send"), (httpx.AsyncClient, "send"),
            (socket.socket, "connect"), (subprocess, "run"),
        ):
            guard.setattr(owner, attribute, forbidden)
        backend.read_mode = "externalized"
        for name, arguments in (
            ("list_agent_configs", {}),
            ("search_agents", {"searchString": "Evaluation"}),
            ("get_agent_config", {"titleId": harness.TITLE_ID}),
            ("read_file", {"path": r".local\results\config-1.json"}),
            ("open_accent_color", {"titleId": harness.TITLE_ID}),
            ("open_quick_links", {"titleId": harness.TITLE_ID}),
            ("open_starter_prompts", {"titleId": harness.TITLE_ID}),
            ("view_agent_icon", {"titleId": harness.TITLE_ID}),
            ("update_agent_config", {"titleId": harness.TITLE_ID, "config": {"pivots": []}}),
            ("create_agent_config", {"titleId": "eval-created"}),
            ("delete_agent_config", {"titleId": "eval-created"}),
        ):
            assert not backend.invoke(name, arguments).failed
        local_config = backend.invoke("read_file", {"path": r".local\config.json"})
        assert json.loads(local_config.result)["agent"]["titleId"] == harness.TITLE_ID
        real_file = backend.invoke("read_file", {"path": str(harness.SKILL_PATH)})
        assert real_file.failed
        assert real_file.result == {"error": "File cannot be read."}
    forbidden.assert_not_called()


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("get_agent_config", {}),
        ("get_agent_config", {"titleId": 123}),
        ("update_agent_config", {"titleId": harness.TITLE_ID, "config": "not an object"}),
        ("open_quick_links", {"titleId": harness.TITLE_ID, "draft": {"quickLinksConfig": {}}}),
        ("read_file", {"path": ".local/config.json", "unexpected": True}),
        ("report_client_events", {}),
        ("powershell", {"command": "Get-Content .local/config.json"}),
    ],
)
def test_invalid_or_unavailable_tools_fail_without_mutating_state(backend, name, arguments) -> None:
    before = deepcopy(backend.configs)

    call = backend.invoke(name, arguments)

    assert call.failed
    assert call.name == name
    assert call.arguments == arguments
    assert call.result == {"error": "Invalid tool invocation."}
    assert backend.configs == before
    assert backend.read_count == 0
    assert backend.artifacts == {}


_GET = harness.RecordedCall(
    1, "get_agent_config", {"titleId": harness.TITLE_ID}, harness.configuration("existing"),
)
_UPDATE = harness.RecordedCall(
    1, "update_agent_config",
    {"titleId": harness.TITLE_ID, "config": {"quickLinksConfig": {"quickLinks": [harness.quick_link("new")]}}},
    harness.configuration("new"),
)
_EXTERNAL_GET = replace(
    _GET,
    result="Tool response stored in file: .local/results/config-1.json. Read the file to inspect the configuration.",
)
_READ_FILE = harness.RecordedCall(
    1, "read_file", {"path": r".local\results\config-1.json"}, json.dumps(_GET.result),
)
_FRESH_ERROR = "own fresh get for the same target/turn"
_CONSUMPTION_ERROR = "externalized authoritative response was not consumed"


@pytest.mark.parametrize(
    ("calls", "error", "message"),
    [
        pytest.param([_UPDATE], AssertionError, _FRESH_ERROR, id="missing-get"),
        pytest.param([replace(_GET, turn=0), _UPDATE], AssertionError, _FRESH_ERROR, id="old-turn"),
        pytest.param([_GET, _UPDATE, _UPDATE], AssertionError, _FRESH_ERROR, id="reused-get"),
        pytest.param(
            [
                replace(
                    _GET,
                    arguments={"titleId": harness.OTHER_TITLE_ID},
                    result=harness.configuration("other", title_id=harness.OTHER_TITLE_ID),
                ),
                _UPDATE,
            ],
            AssertionError, _FRESH_ERROR, id="wrong-target",
        ),
        pytest.param(
            [_GET, replace(_GET, failed=True, result={"error": "Server read failed.", "httpStatus": 503}), _UPDATE],
            AssertionError, "failed read", id="latest-get-failed",
        ),
        pytest.param(
            [_GET, harness.RecordedCall(1, "list_agent_configs", {}, {"value": []}), _UPDATE],
            AssertionError, "Unrelated tools intervened", id="unrelated-tool",
        ),
        pytest.param(
            [_EXTERNAL_GET, _UPDATE], AssertionError, _CONSUMPTION_ERROR, id="unread-artifact",
        ),
        pytest.param(
            [_EXTERNAL_GET, replace(_READ_FILE, failed=True, result={"error": "File cannot be read."}), _UPDATE],
            AssertionError, _CONSUMPTION_ERROR, id="unreadable-artifact",
        ),
        pytest.param(
            [_EXTERNAL_GET, replace(_READ_FILE, arguments={"path": ".local/results/config-2.json"}), _UPDATE],
            AssertionError, _CONSUMPTION_ERROR, id="wrong-artifact",
        ),
        pytest.param(
            [_EXTERNAL_GET, replace(_READ_FILE, result='{"quickLinksConfig":'), _UPDATE],
            json.JSONDecodeError, "Expecting value", id="malformed-artifact",
        ),
    ],
)
def test_freshness_grader_rejects_invalid_observed_traces(backend, calls, error, message) -> None:
    backend.calls = deepcopy(calls)
    with pytest.raises(error, match=message):
        harness.assert_fresh_updates(backend)


@pytest.mark.parametrize("read_mode", ["inline", "externalized"])
def test_freshness_grader_rejects_an_unrelated_workspace_file_read(backend, read_mode) -> None:
    backend.read_mode = read_mode
    assert not backend.invoke("get_agent_config", {"titleId": harness.TITLE_ID}).failed
    if read_mode == "externalized":
        backend.invoke("read_file", {"path": ".local/results/config-1.json"})
    assert not backend.invoke("read_file", {"path": r".local\config.json"}).failed
    assert not backend.invoke(
        "update_agent_config", {"titleId": harness.TITLE_ID, "config": {"pivots": []}},
    ).failed

    with pytest.raises(AssertionError, match="Unrelated files were read"):
        harness.assert_fresh_updates(backend)


@pytest.mark.parametrize(
    "baseline",
    [None, [], {}, harness.configuration(title_id=harness.OTHER_TITLE_ID)],
)
def test_freshness_grader_rejects_a_misidentified_consumed_baseline(backend, baseline) -> None:
    backend.calls = [
        deepcopy(_EXTERNAL_GET),
        replace(_READ_FILE, result=json.dumps(baseline)),
        deepcopy(_UPDATE),
    ]
    with pytest.raises(AssertionError, match="consumed baseline must identify"):
        harness.assert_fresh_updates(backend)


@pytest.mark.parametrize("read_mode", ["inline", "externalized"])
@pytest.mark.parametrize("second_turn", [1, 2], ids=["same-turn", "next-turn"])
@pytest.mark.parametrize(
    "second_title_id", [harness.TITLE_ID, harness.OTHER_TITLE_ID], ids=["same-target", "other-target"],
)
def test_each_update_accepts_its_own_get_and_artifact_consumption(
    backend, read_mode, second_turn, second_title_id,
) -> None:
    backend.read_mode = read_mode
    for turn, title_id in ((1, harness.TITLE_ID), (second_turn, second_title_id)):
        backend.turn = turn
        assert not backend.invoke("get_agent_config", {"titleId": title_id}).failed
        if read_mode == "externalized":
            assert not backend.invoke(
                "read_file", {"path": rf".local\results\config-{backend.read_count}.json"},
            ).failed
        assert not backend.invoke(
            "update_agent_config", {"titleId": title_id, "config": {"pivots": []}},
        ).failed

    assert len(backend.updates()) == 2
    harness.assert_fresh_updates(backend)


def test_call_budget_counts_failures_and_blocks_the_next_write(backend, monkeypatch) -> None:
    monkeypatch.setattr(harness, "MAX_CALLS", 2)
    before = deepcopy(backend.configs)
    backend.invoke("get_agent_config", {"titleId": harness.TITLE_ID})
    assert backend.invoke("unknown_tool", {}).failed

    with pytest.raises(RuntimeError, match="2-tool-call limit"):
        backend.invoke("update_agent_config", {"titleId": harness.TITLE_ID, "config": {"pivots": []}})

    assert len(backend.calls) == 2
    assert backend.limit_exceeded
    assert backend.configs == before
    assert backend.updates() == []


def test_session_options_and_harness_import_do_not_require_the_optional_sdk(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "copilot", None)
    monkeypatch.setitem(sys.modules, "copilot.tools", None)
    spec = importlib.util.spec_from_file_location("offline_skill_eval_import", harness.__file__)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    tools = [object()]
    allowlist = object()
    directory = Path(".local") / "offline-eval"

    options = module.session_options("evaluation-model", tools, allowlist, directory)

    assert options["model"] == "evaluation-model"
    assert options["tools"] is tools
    assert options["available_tools"] is allowlist
    assert options["working_directory"] == str(directory)
    assert options["skip_custom_instructions"] is True
    for key in (
        "enable_config_discovery", "enable_skills", "enable_file_hooks",
        "enable_host_git_operations", "enable_session_store",
    ):
        assert options[key] is False
    assert options["memory"] == {"enabled": False}
    assert options["mcp_servers"] == {}
    assert options["custom_agents"] == []
    assert options["plugin_directories"] == []
    assert options["infinite_sessions"] == {"enabled": False}
    assert set(options["session_limits"]) == {"max_ai_credits"}
    assert isinstance(options["session_limits"]["max_ai_credits"], int)
    assert options["session_limits"]["max_ai_credits"] > 0
    assert options["system_message"]["mode"] == "replace"
    assert options["system_message"]["content"].endswith(harness.SKILL_PATH.read_text(encoding="utf-8"))


def test_missing_sdk_fails_before_auth_or_live_execution(backend, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "copilot", None)
    auth = Mock(side_effect=AssertionError("Offline tests must not authenticate."))
    monkeypatch.setattr(harness, "_github_token", auth)

    with pytest.raises(RuntimeError, match="Install the skill-eval extra"):
        asyncio.run(harness.run_eval(backend, [], Path(".local") / "offline-eval"))

    auth.assert_not_called()
    assert backend.calls == []


@pytest.mark.parametrize(
    ("returncode", "stdout"), [(1, "SYNTHETIC_TOKEN_MUST_STAY_PRIVATE"), (0, ""), (0, " \n")],
)
def test_auth_failure_does_not_include_subprocess_output(monkeypatch, returncode, stdout) -> None:
    run = Mock(return_value=subprocess.CompletedProcess(
        ["gh", "auth", "token"], returncode, stdout, "SYNTHETIC_AUTH_DIAGNOSTIC",
    ))
    monkeypatch.setattr(harness.subprocess, "run", run)

    with pytest.raises(RuntimeError) as error:
        harness._github_token()

    assert str(error.value) == "Skill evals require an authenticated gh CLI with Copilot access."
    assert "SYNTHETIC" not in str(error.value)
    run.assert_called_once_with(
        ["gh", "auth", "token"], capture_output=True, text=True, timeout=15, check=False,
    )


def test_auth_success_strips_whitespace_from_the_captured_token(monkeypatch) -> None:
    run = Mock(return_value=subprocess.CompletedProcess(
        ["gh", "auth", "token"], 0, " SYNTHETIC_EVAL_TOKEN\n", "",
    ))
    monkeypatch.setattr(harness.subprocess, "run", run)

    assert harness._github_token() == "SYNTHETIC_EVAL_TOKEN"
    run.assert_called_once_with(
        ["gh", "auth", "token"], capture_output=True, text=True, timeout=15, check=False,
    )


@pytest.mark.parametrize("exit_code", [0, 1])
def test_branding_validation_tool_is_recorded_and_never_executes_commands(backend, monkeypatch, exit_code) -> None:
    backend.validation_exit_code = exit_code
    forbidden = Mock(side_effect=AssertionError("Synthetic validation must not execute a process."))
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    call = backend.invoke(
        "run_command", {"command": 'python scripts/validate_branding.py --light "#0F6CBD"'}
    )
    assert not call.failed
    assert call.result["exitCode"] == exit_code
    assert "WCAG" in call.result["stdout"] if exit_code == 0 else "contrast ratio" in call.result["stdout"]
    forbidden.assert_not_called()


@pytest.mark.parametrize("command", ["python arbitrary.py", "curl https://example.test", "python scripts/validate_branding.py --light bad", 'python "unfinished'])
def test_synthetic_validation_rejects_other_commands(backend, command) -> None:
    assert backend.invoke("run_command", {"command": command}).failed


@pytest.mark.parametrize("fail_start", [False, True], ids=["constructor", "startup"])
def test_runtime_startup_failure_suppresses_credential_bearing_tracebacks(monkeypatch, tmp_path, fail_start) -> None:
    secret = "SYNTHETIC_PRIVATE_RUNTIME_TOKEN"

    class Client:
        def __init__(self, **kwargs):
            if not fail_start:
                raise OSError(secret)

        async def start(self):
            raise OSError(secret)

        async def __aenter__(self):
            await self.start()

        async def __aexit__(self, *_args):
            pass

    monkeypatch.setitem(sys.modules, "copilot", SimpleNamespace(CopilotClient=Client))
    monkeypatch.setattr(harness, "_github_token", lambda: secret)

    async def open_client():
        async with harness.model_client(tmp_path):
            pytest.fail("A failed runtime must not be yielded.")

    with pytest.raises(RuntimeError, match="isolated model runtime") as error:
        asyncio.run(open_client())
    assert error.value.__suppress_context__
    assert secret not in "".join(traceback.format_exception(error.value))


def test_managed_runtime_closes_owned_pipes_after_sdk_shutdown(monkeypatch, tmp_path) -> None:
    streams = [io.BytesIO(), io.BytesIO(), io.BytesIO()]

    class Client:
        def __init__(self, **kwargs):
            self._cli_process = SimpleNamespace(
                stdin=streams[0], stdout=streams[1], stderr=streams[2]
            )
            assert kwargs["mode"] == "empty"
            assert kwargs["base_directory"] == str(tmp_path / "host")

        async def start(self):
            pass

        async def stop(self):
            assert not any(stream.closed for stream in streams)
            self._cli_process = None

        async def __aenter__(self):
            await self.start()
            return self

        async def __aexit__(self, *_args):
            await self.stop()

    monkeypatch.setitem(sys.modules, "copilot", SimpleNamespace(CopilotClient=Client))
    monkeypatch.setattr(harness, "_github_token", lambda: "SYNTHETIC_TOKEN")

    async def open_client():
        async with harness.model_client(tmp_path):
            assert not any(stream.closed for stream in streams)

    asyncio.run(open_client())
    assert all(stream.closed for stream in streams)


def _event(kind, **data):
    return SimpleNamespace(type=kind, data=SimpleNamespace(**data))


class _EventSession:
    def __init__(self, events):
        self.events = events
        self.handler = None
        self.aborted = False
        self.unsubscribed = False

    def on(self, handler):
        self.handler = handler

        def unsubscribe():
            self.unsubscribed = True

        return unsubscribe

    async def send(self, prompt, *, agent_mode):
        assert agent_mode == "interactive"

        def notify():
            for event in self.events:
                self.handler(event)

        thread = threading.Thread(target=notify)
        thread.start()
        thread.join(timeout=1)
        assert not thread.is_alive()
        return "maker-message"

    async def abort(self):
        self.aborted = True


def test_model_reply_completion_handles_reader_threads_without_idle_notifications() -> None:
    session = _EventSession([
        _event("assistant.message", originating_message_id="unrelated", content="Wrong reply", tool_requests=None),
        _event("assistant.turn_end"),
        _event("assistant.message", originating_message_id="maker-message", content="Working", tool_requests=[{}]),
        _event("assistant.turn_end"),
        _event("session.idle"),
        _event("assistant.message", originating_message_id="maker-message", content="Done", tool_requests=None),
        _event("assistant.turn_end"),
    ])
    events = []
    assert asyncio.run(harness.send_turn(session, "Make the edit.", events, timeout=1)) == "Done"
    assert session.unsubscribed
    assert not session.aborted
    assert events[-1] == "assistant.turn_end"


def test_model_session_errors_fail_and_unsubscribe() -> None:
    session = _EventSession([_event("session.error", message="Synthetic service failure")])
    with pytest.raises(RuntimeError, match="Synthetic service failure"):
        asyncio.run(harness.send_turn(session, "Make the edit.", [], timeout=1))
    assert session.unsubscribed


def test_incomplete_model_turn_times_out_aborts_and_unsubscribes() -> None:
    session = _EventSession([])
    with pytest.raises(TimeoutError):
        asyncio.run(harness.send_turn(session, "Make the edit.", [], timeout=0.01))
    assert session.aborted
    assert session.unsubscribed


def test_overview_grader_rejects_reversed_toggle_states() -> None:
    expected = {"stay up to date": "enabled", "quick access": "disabled"}
    correct = "| Stay up to date | Enabled | Ticket updates |\n| Quick Access | Disabled | Personal information |"
    harness.assert_overview_states(correct, expected)
    reversed_states = "| Stay up to date | Disabled | Ticket updates |\n| Quick Access | Enabled | Personal information |"
    with pytest.raises(AssertionError, match="correct setting"):
        harness.assert_overview_states(reversed_states, expected)


@pytest.mark.parametrize("description", ["The default prompts have been published.", "Default prompts are ready. Select Publish."])
def test_default_prompt_grader_rejects_missing_unpublished_state(description) -> None:
    with pytest.raises(AssertionError, match="explicitly identified as unpublished"):
        harness.assert_unpublished_defaults(description)


@pytest.mark.parametrize("description", [
    "These default prompts haven't been published yet.",
    "The default draft suggestions are unpublished.",
    "The widget opened with default draft suggestions because no starter prompts are saved yet.",
])
def test_default_prompt_grader_accepts_explicit_unpublished_state(description) -> None:
    harness.assert_unpublished_defaults(description)


@pytest.mark.parametrize("reply", [
    "I can't safely add that link because the file couldn't be read.",
    "I can\u2019t safely add that link because the file couldn\u2019t be read.",
    "The authoritative configuration is incomplete.",
])
def test_read_failure_grader_accepts_equivalent_punctuation(reply) -> None:
    harness.assert_read_failure_explained(reply)


def test_read_failure_grader_rejects_a_success_only_reply() -> None:
    with pytest.raises(AssertionError, match="why the required read"):
        harness.assert_read_failure_explained("Added the quick link successfully.")
