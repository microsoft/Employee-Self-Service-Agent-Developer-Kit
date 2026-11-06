# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for non-blocking capability telemetry."""

from __future__ import annotations

import os
import sys

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


def test_capability_emit_does_not_spawn_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(
        "adk_telemetry.telemetry_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        emit_capability.subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("worker should not start"),
    )

    assert emit_capability.main(["emit_capability.py", "setup"]) == 0


def test_worker_emits_synchronously(monkeypatch) -> None:
    emitted = []

    monkeypatch.setattr(
        "adk_telemetry.emit_capability_use",
        lambda capability, connector, block: emitted.append(
            (capability, connector, block)
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
        lambda capability, connector, block: emitted.append(
            (capability, connector, block)
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
