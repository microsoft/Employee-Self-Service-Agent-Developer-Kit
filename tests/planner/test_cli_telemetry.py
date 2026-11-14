# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""/planner must appear on the ADK "Capability Usage by Type" donut.

``cli.main`` emits the capability in-process, right after argparse succeeds,
rather than through a ``scripts/emit_capability.py planner`` step in SKILL.md.
``emit_capability_use()`` does not dedupe, so wiring both would double-count.

Pure local IO (telemetry is spied or off), so exempt from the FlightCheck
cassette policy.
"""

from __future__ import annotations

import adk_telemetry
import pytest

from planner import cli


@pytest.fixture
def emits(monkeypatch, tmp_path):
    calls = []

    def _record(capability, **kwargs):
        calls.append((capability, kwargs))
        return {"sent": True}

    monkeypatch.setattr(adk_telemetry, "emit_capability_use", _record)
    monkeypatch.chdir(tmp_path)
    return calls


def _init(tmp_path) -> int:
    return cli.main(["--plan", str(tmp_path / "plan.json"), "init"])


def test_planner_is_canonical_so_it_cannot_bucket_to_unknown():
    # The bug this guards is silent: an out-of-taxonomy value still emits,
    # but lands in the "unknown" slice instead of its own.
    assert "planner" in adk_telemetry.ADK_CAPABILITIES
    assert adk_telemetry.normalize_capability("planner") == "planner"


def test_a_run_emits_the_capability_exactly_once(tmp_path, emits):
    assert _init(tmp_path) == 0
    assert [capability for capability, _ in emits] == ["planner"]


def test_the_emit_is_synchronous(tmp_path, emits):
    _init(tmp_path)

    # A short-lived CLI exits and kills a daemon emit thread before the event
    # leaves the process, so the emit must block.
    assert emits[0][1].get("block") is True


def test_bad_arguments_do_not_count_as_usage(emits):
    # argparse exits before the emit, so --help and typos stay off the donut.
    with pytest.raises(SystemExit):
        cli.main(["nonexistent-cmd"])
    assert emits == []


def test_a_telemetry_failure_never_breaks_the_flow(tmp_path, monkeypatch):
    def _boom(*_args, **_kwargs):
        raise RuntimeError("collector unreachable")

    monkeypatch.setattr(adk_telemetry, "emit_capability_use", _boom)
    monkeypatch.chdir(tmp_path)

    assert _init(tmp_path) == 0
