# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for non-blocking capability telemetry."""

from __future__ import annotations

import os
from pathlib import Path
import shlex
import sys
from unittest.mock import Mock, create_autospec

import adk_telemetry
import emit_capability
import pytest


def test_capability_emit_starts_detached_worker(monkeypatch) -> None:
    calls = []
    waits = []

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return type("Worker", (), {"wait": lambda self: waits.append(True)})()

    class FakeThread:
        def __init__(self, *, target, name, daemon):
            assert name == "adk-capability-worker-reaper"
            assert daemon is True
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(emit_capability.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(emit_capability.threading, "Thread", FakeThread)
    monkeypatch.setattr(
        "adk_telemetry.telemetry_enabled",
        lambda: True,
    )
    monkeypatch.setattr("adk_telemetry._SYNC", False)

    result = emit_capability.main(["emit_capability.py", "setup"])

    assert result == 0
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command == [
        sys.executable,
        os.path.abspath(emit_capability.__file__),
        "--worker",
        "setup",
    ]
    assert kwargs["stdin"] is emit_capability.subprocess.DEVNULL
    assert kwargs["stdout"] is emit_capability.subprocess.DEVNULL
    assert kwargs["stderr"] is emit_capability.subprocess.DEVNULL
    assert waits == [True]


def test_capability_emit_parent_forwards_connector_argv(monkeypatch) -> None:
    # PARENT-PATH attribution round-trip (ADO 7943641): when the maker
    # invokes ``emit_capability.py connect --connector workday``, the
    # detached worker subprocess MUST be spawned with ``--connector
    # workday`` in its argv so the worker's ``emit_capability_use`` call
    # carries the attribution. Missing this on the parent leg silently
    # dropped attribution before the worker even ran; the
    # ``test_worker_emits_synchronously_with_connector`` test below only
    # covers the worker leg of the same round-trip.
    calls = []

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return type("Worker", (), {"wait": lambda self: None})()

    class FakeThread:
        def __init__(self, *, target, name, daemon):
            assert daemon is True
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(emit_capability.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(emit_capability.threading, "Thread", FakeThread)
    monkeypatch.setattr("adk_telemetry.telemetry_enabled", lambda: True)
    monkeypatch.setattr("adk_telemetry._SYNC", False)

    result = emit_capability.main([
        "emit_capability.py",
        "connect",
        "--connector",
        "workday",
    ])

    assert result == 0
    assert len(calls) == 1
    command, _kwargs = calls[0]
    assert command == [
        sys.executable,
        os.path.abspath(emit_capability.__file__),
        "--worker",
        "connect",
        "--connector",
        "workday",
    ]

    # ``--connector=<value>`` form and connector-before-capability ordering
    # must also propagate — the shim parses both variants but the argv sent
    # to the worker is canonicalized to the "--connector <value>" form.
    calls.clear()
    result = emit_capability.main([
        "emit_capability.py",
        "--connector=servicenow",
        "connect",
    ])
    assert result == 0
    assert len(calls) == 1
    command, _kwargs = calls[0]
    assert command == [
        sys.executable,
        os.path.abspath(emit_capability.__file__),
        "--worker",
        "connect",
        "--connector",
        "servicenow",
    ]


def test_capability_emit_parent_omits_connector_when_not_supplied(
    monkeypatch,
) -> None:
    # Negative half of the parent-path attribution assertion: with no
    # ``--connector`` flag on the parent invocation, the worker argv must
    # contain no ``--connector`` at all so worker parsing falls through to
    # ``connector=""`` (not to an inadvertent ``"unknown"`` normalization
    # from an empty positional).
    calls = []

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return type("Worker", (), {"wait": lambda self: None})()

    class FakeThread:
        def __init__(self, *, target, name, daemon):
            assert daemon is True
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(emit_capability.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(emit_capability.threading, "Thread", FakeThread)
    monkeypatch.setattr("adk_telemetry.telemetry_enabled", lambda: True)
    monkeypatch.setattr("adk_telemetry._SYNC", False)

    result = emit_capability.main(["emit_capability.py", "topic_create"])

    assert result == 0
    assert len(calls) == 1
    command, _kwargs = calls[0]
    assert "--connector" not in command
    assert command[-1] == "topic_create"


@pytest.mark.parametrize("capability", ["setup", "topic_create", "topic_update", "topic_test"])
def test_capability_emit_does_not_spawn_when_disabled(monkeypatch, capability) -> None:
    monkeypatch.setattr(
        "adk_telemetry.telemetry_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        emit_capability.subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("worker should not start"),
    )

    assert emit_capability.main(["emit_capability.py", capability]) == 0


def test_worker_emits_synchronously(monkeypatch) -> None:
    emitted = []

    monkeypatch.setattr(
        "adk_telemetry.emit_capability_use",
        lambda adk_capability, connector, block: emitted.append(
            (adk_capability, connector, block)
        ),
    )

    result = emit_capability.main([
        "emit_capability.py",
        "--worker",
        "setup",
    ])

    assert result == 0
    assert emitted == [("setup", "", True)]


def test_worker_emits_synchronously_with_connector(monkeypatch) -> None:
    # Attribution round-trip: parent shim -> detached worker subprocess ->
    # emit_capability_use must carry the ``--connector`` value through the
    # subprocess argv (ADO 7943641). Missing the flag was silently emitting
    # the Connect capability with no attribution.
    emitted = []

    monkeypatch.setattr(
        "adk_telemetry.emit_capability_use",
        lambda adk_capability, connector, block: emitted.append(
            (adk_capability, connector, block)
        ),
    )

    result = emit_capability.main([
        "emit_capability.py",
        "--worker",
        "connect",
        "--connector",
        "workday",
    ])

    assert result == 0
    assert emitted == [("connect", "workday", True)]


@pytest.fixture
def delivery(monkeypatch):
    emitters = {}
    for name in ("emit_capability_use", "emit_build_start", "emit_build_complete", "emit_agent_deploy"):
        emitters[name] = create_autospec(getattr(adk_telemetry, name), return_value={})
        monkeypatch.setattr(adk_telemetry, name, emitters[name])
    popen = Mock()
    monkeypatch.setattr(emit_capability.subprocess, "Popen", popen)
    monkeypatch.setattr(emit_capability.threading, "Thread", Mock())
    monkeypatch.setattr(adk_telemetry, "telemetry_enabled", lambda: True)
    monkeypatch.setattr(adk_telemetry, "_SYNC", False)
    return emitters, popen


@pytest.fixture(params=[
    ("build-start", [], {}),
    ("build-complete", [
        "--outcome", "failure", "--duration-ms", "1250",
        "--error-code", "BUILD_FAILED", "--error-category", "runtime",
    ], {
        "outcome": "failure", "duration_ms": 1250,
        "error_code": "BUILD_FAILED", "error_category": "runtime",
    }),
    ("agent-deploy", [
        "--outcome", "success", "--duration-ms", "0", "--deploy-target", "production",
    ], {
        "outcome": "success", "duration_ms": 0, "deploy_target": "production",
        "error_code": "", "error_category": "",
    }),
], ids=["build-start", "build-complete", "agent-deploy"])
def lifecycle_emission(request):
    event, extra, fields = request.param
    return (
        ["push", f"--event={event}", "--agent-id", "test-agent", *extra],
        "emit_" + event.replace("-", "_"),
        {"agent_id": "test-agent", "adk_capability": "push", "block": True, **fields},
    )


def test_lifecycle_parent_worker_round_trip_invokes_only_selected_emitter(delivery, lifecycle_emission):
    emitters, popen = delivery
    args, selected, fields = lifecycle_emission

    assert emit_capability.main(["emit_capability.py", *args]) == 0
    popen.assert_called_once()
    command = popen.call_args.args[0]
    assert command == [sys.executable, os.path.abspath(emit_capability.__file__), "--worker", *args]
    assert all(not emitter.called for emitter in emitters.values())

    assert emit_capability.main(command[1:]) == 0
    emitters[selected].assert_called_once_with(**fields)
    assert all(not emitter.called for name, emitter in emitters.items() if name != selected)
    popen.assert_called_once()


def test_lifecycle_sync_uses_sdk_without_worker(delivery, lifecycle_emission, monkeypatch):
    emitters, popen = delivery
    args, selected, fields = lifecycle_emission
    monkeypatch.setattr(adk_telemetry, "_SYNC", True)

    assert emit_capability.main(["emit_capability.py", *args]) == 0
    emitters[selected].assert_called_once_with(**fields)
    assert all(not emitter.called for name, emitter in emitters.items() if name != selected)
    popen.assert_not_called()


@pytest.mark.parametrize("result", ["success", "component-error", "already-current"])
def test_documented_push_commands_compose_one_lifecycle(delivery, monkeypatch, result):
    emitters, popen = delivery
    monkeypatch.setattr(adk_telemetry, "_SYNC", True)
    failed = result == "component-error"
    emit_deploy = result != "already-current"
    contract = (
        Path(__file__).resolve().parents[2] / "solutions" / "ess-maker-skills"
        / "src" / "skills" / "topics" / "push-experience.md"
    ).read_text(encoding="utf-8")
    telemetry = contract.split("## Push telemetry\n", 1)[1]
    substitutions = {
        "AgentId": "test-agent",
        "BuildOutcome": "failure" if failed else "success",
        "DeployOutcome": "server_error" if failed else "success",
        "BuildErrorCode": "PUSH_PARTIAL_FAILURE" if failed else "",
        "DeployErrorCode": "DEPLOY_PARTIAL_FAILURE" if failed else "",
        "ErrorCategory": "runtime" if failed else "",
        "DurationMs": "1250",
        "DeployTarget": "sandbox",
    }
    commands = [
        shlex.split(line.split(" ", 2)[2].format(**substitutions))
        for line in telemetry.splitlines()
        if line.startswith("python scripts\\emit_capability.py ")
    ]
    assert len(commands) == 4
    if not emit_deploy:
        assert "For verified already-current execution, omit the `agent-deploy` command" in telemetry
        commands = [args for args in commands if "agent-deploy" not in args]
    calls = Mock()
    for name, emitter in emitters.items():
        calls.attach_mock(emitter, name)
    for args in commands:
        assert emit_capability.main(["emit_capability.py", *args]) == 0

    assert [call[0] for call in calls.mock_calls] == [
        "emit_build_start", "emit_build_complete",
        *(["emit_agent_deploy"] if emit_deploy else []),
        "emit_capability_use",
    ]
    shared = {"agent_id": "test-agent", "adk_capability": "push", "block": True}
    emitters["emit_build_start"].assert_called_once_with(**shared)
    emitters["emit_build_complete"].assert_called_once_with(
        **shared, outcome=substitutions["BuildOutcome"], duration_ms=1250,
        error_code=substitutions["BuildErrorCode"],
        error_category=substitutions["ErrorCategory"],
    )
    if emit_deploy:
        emitters["emit_agent_deploy"].assert_called_once_with(
            **shared, outcome=substitutions["DeployOutcome"], duration_ms=1250,
            deploy_target="sandbox", error_code=substitutions["DeployErrorCode"],
            error_category=substitutions["ErrorCategory"],
        )
    else:
        emitters["emit_agent_deploy"].assert_not_called()
    emitters["emit_capability_use"].assert_called_once_with(
        adk_capability="push", connector="", block=True,
    )
    popen.assert_not_called()


@pytest.mark.parametrize("sync", [False, True])
def test_lifecycle_opt_out_has_no_emission_or_worker(delivery, lifecycle_emission, monkeypatch, sync):
    emitters, popen = delivery
    args, _selected, _fields = lifecycle_emission
    monkeypatch.setattr(adk_telemetry, "telemetry_enabled", lambda: False)
    monkeypatch.setattr(adk_telemetry, "_SYNC", sync)

    assert emit_capability.main(["emit_capability.py", *args]) == 0
    assert all(not emitter.called for emitter in emitters.values())
    popen.assert_not_called()


@pytest.mark.parametrize("stage", ["consent", "spawn", "sync-emit", "worker-emit"])
def test_lifecycle_failures_do_not_escape_or_retry(delivery, lifecycle_emission, monkeypatch, capsys, stage):
    emitters, popen = delivery
    args, selected, fields = lifecycle_emission
    failure = RuntimeError("private diagnostic payload")
    if stage == "consent":
        monkeypatch.setattr(adk_telemetry, "telemetry_enabled", Mock(side_effect=failure))
    elif stage == "spawn":
        popen.side_effect = failure
    else:
        emitters[selected].side_effect = failure
        if stage == "sync-emit":
            monkeypatch.setattr(adk_telemetry, "_SYNC", True)
        else:
            args = ["--worker", *args]

    assert emit_capability.main(["emit_capability.py", *args]) == 0
    assert popen.call_count == (1 if stage == "spawn" else 0)
    if stage in {"sync-emit", "worker-emit"}:
        emitters[selected].assert_called_once_with(**fields)
    else:
        emitters[selected].assert_not_called()
    assert all(not emitter.called for name, emitter in emitters.items() if name != selected)
    output = capsys.readouterr()
    assert output.out == ""
    assert "private diagnostic payload" not in output.err
    assert "RuntimeError" in output.err
    if stage != "consent":
        assert "delivery is unconfirmed" in output.err


@pytest.mark.parametrize("args", [
    ["--event", "build-start"],
    ["--event", "build-start", "--agent-id", " "],
    ["--event", "build-complete", "--agent-id", "a", "--duration-ms", "1"],
    ["--event", "build-complete", "--agent-id", "a", "--outcome", "success"],
    ["--event", "build-complete", "--agent-id", "a", "--outcome", "success", "--duration-ms", "-1"],
    ["--event", "build-complete", "--agent-id", "a", "--outcome", "success", "--duration-ms", "bad"],
    ["--event", "agent-deploy", "--agent-id", "a", "--outcome", "success", "--duration-ms", "1"],
    ["--event", "build-start", "--agent-id", "a", "--outcome", "success"],
    ["--event", "build-start", "--agent-id", "a", "--connector", "workday"],
    ["--agent-id", "a"],
    ["--evnt", "build-start", "--agent-id", "a"],
])
def test_invalid_lifecycle_input_is_diagnosed_without_defaulting_to_usage(delivery, capsys, args):
    emitters, popen = delivery
    assert emit_capability.main(["emit_capability.py", "push", *args]) == 0
    assert "error:" in capsys.readouterr().err
    assert all(not emitter.called for emitter in emitters.values())
    popen.assert_not_called()
