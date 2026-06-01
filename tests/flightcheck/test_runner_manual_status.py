# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Unit tests for the FlightCheck runner — specifically the MANUAL
status added for issue #84 (SAML NameID alignment).

Pins three contracts that downstream tooling (HTML report, JSON
results, dashboards) depends on:

1. MANUAL is a valid Status enum value with string value "Manual".
2. MANUAL results are counted in `CategorySummary.manual` and
   `RunResult.manual` — NOT lumped into warnings, not_configured,
   or any existing bucket.
3. MANUAL does NOT fail readiness — a run with only MANUAL items
   is still "READY".
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _scripts_on_path():
    """Ensure scripts/ is on sys.path so `from flightcheck...` resolves."""
    scripts_dir = (
        Path(__file__).resolve().parents[1]
        / "solutions" / "ess-maker-skills" / "scripts"
    )
    sys.path.insert(0, str(scripts_dir))
    try:
        yield
    finally:
        try:
            sys.path.remove(str(scripts_dir))
        except ValueError:
            pass


def test_manual_status_value_is_stable() -> None:
    """The enum string value 'Manual' is what gets serialized to JSON
    and rendered in HTML reports — downstream tools may key on it."""
    from flightcheck.runner import Status

    assert Status.MANUAL.value == "Manual"


def test_manual_results_tallied_in_dedicated_bucket() -> None:
    from flightcheck.runner import (
        FlightCheckRunner,
        CheckResult,
        Status,
        Priority,
    )

    runner = FlightCheckRunner(scope="test")
    runner.register("Authentication", lambda _r: [
        CheckResult(
            checkpoint_id="AUTH-006",
            category="Authentication",
            priority=Priority.HIGH.value,
            status=Status.MANUAL.value,
            description="SAML NameID alignment",
            result="Found Workday SAML app; Entra NameID = default UPN",
            remediation="Verify the Workday tenant NameID expectation.",
        ),
        CheckResult(
            checkpoint_id="AUTH-001",
            category="Authentication",
            priority=Priority.CRITICAL.value,
            status=Status.PASSED.value,
            description="Entra ID configured",
            result="Tenant: Contoso",
        ),
    ])
    result = runner.run()

    # MANUAL doesn't go into any pre-existing bucket.
    assert result.manual == 1
    assert result.warnings == 0
    assert result.not_configured == 0
    assert result.failed == 0
    assert result.passed == 1

    cat = result.categories[0]
    assert cat.category == "Authentication"
    assert cat.manual == 1
    assert cat.passed == 1


def test_manual_only_run_is_ready_not_failed() -> None:
    """The whole point of MANUAL — informational, not a gate."""
    from flightcheck.runner import (
        FlightCheckRunner,
        CheckResult,
        Status,
        Priority,
    )

    runner = FlightCheckRunner(scope="test")
    runner.register("Authentication", lambda _r: [
        CheckResult(
            checkpoint_id="AUTH-006",
            category="Authentication",
            priority=Priority.HIGH.value,
            status=Status.MANUAL.value,
            description="SAML NameID alignment",
            result="Found Workday SAML app",
            remediation="Verify in Workday.",
        ),
    ])
    result = runner.run()

    assert result.overall == "READY", (
        f"Expected READY (MANUAL is informational), got {result.overall}"
    )


def test_manual_count_serialized_to_json(tmp_path) -> None:
    """Downstream report.html and results.json consumers need the
    `manual` count at the top level."""
    from flightcheck.runner import (
        FlightCheckRunner,
        CheckResult,
        Status,
        Priority,
        save_results,
    )

    runner = FlightCheckRunner(scope="test")
    runner.register("Authentication", lambda _r: [
        CheckResult(
            checkpoint_id="AUTH-006",
            category="Authentication",
            priority=Priority.HIGH.value,
            status=Status.MANUAL.value,
            description="SAML NameID alignment",
            result="Manual finding line 1\nline 2 — indented",
            remediation="Step 1:\n  a. First sub-step\n  b. Second sub-step",
        ),
    ])
    result = runner.run()
    save_results(result, output_dir=str(tmp_path))

    data = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert data["manual"] == 1
    html = (tmp_path / "report.html").read_text(encoding="utf-8")
    # The HTML summary card and the row status both need to be visible.
    assert "Manual" in html
    assert "status-manual" in html
    # And the cell-text class must be applied to the result +
    # remediation cells so multi-line strings preserve their
    # formatting (issue: wall-of-text rendering in early AUTH-006
    # iterations). Pin both the class application and the CSS rule.
    assert 'class="cell-text"' in html
    assert "white-space: pre-wrap" in html
    assert "line-height: 1.5" in html
