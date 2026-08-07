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
        lambda capability, block: emitted.append((capability, block)),
    )

    result = emit_capability.main([
        "emit_capability.py",
        "--worker",
        "setup",
    ])

    assert result == 0
    assert emitted == [("setup", True)]
