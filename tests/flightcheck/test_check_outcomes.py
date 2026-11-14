# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Every status a FlightCheck check can return is counted and rendered.

Offline: no live Power Platform, Graph or agent calls. Live validation lives
elsewhere and is kept separate on purpose.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _scripts_on_path():
    scripts_dir = (
        Path(__file__).resolve().parents[2]
        / "solutions" / "ess-maker-skills" / "scripts"
    )
    sys.path.insert(0, str(scripts_dir))
    try:
        yield
    finally:
        sys.path.remove(str(scripts_dir))


# Status value -> RunResult counter that must increase by exactly one.
COUNTER_BY_STATUS = {
    "Passed": "passed",
    "Failed": "failed",
    "Blocked": "blocked",
    "Warning": "warnings",
    "NotConfigured": "not_configured",
    "Skipped": "skipped",
    "Error": "errors",
    "Manual": "manual",
}


def test_counter_table_covers_every_status():
    from flightcheck.runner import Status

    assert {status.value for status in Status} == set(COUNTER_BY_STATUS)


@pytest.mark.parametrize("status,counter", COUNTER_BY_STATUS.items())
def test_each_status_is_counted_once_and_rendered(tmp_path, status, counter):
    from flightcheck.runner import CheckResult, FlightCheckRunner, save_results

    row = CheckResult(
        checkpoint_id="TEST-001", category="Test", priority="High", status=status,
        description="Probe purpose", result="Probe result",
        remediation="" if status == "Passed" else "Probe next step",
    )
    runner = FlightCheckRunner()
    runner.register("Test", lambda _r: [row])
    result = runner.run()

    assert result.total == 1
    assert getattr(result, counter) == 1
    other_counts = sum(
        getattr(result, name) for name in COUNTER_BY_STATUS.values() if name != counter
    )
    assert other_counts == 0

    save_results(result, str(tmp_path))
    payload = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert payload["results"][0]["status"] == status
    assert payload[counter] == 1
    html = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "TEST-001" in html and "Probe purpose" in html
