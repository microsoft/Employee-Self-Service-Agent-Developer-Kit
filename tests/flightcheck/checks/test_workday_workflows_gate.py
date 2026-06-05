# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Pins the install-flavor gating contract for `_check_workflows`
(see AGENTS.md design principle #11).

Scope: this test ONLY exercises the simplified-install gate at the
top of `_check_workflows`. The 17-workflow SOAP body is covered by
the live `/connect workday` + `/flightcheck` integration path and is
not unit-tested here (it requires real Workday ISU credentials and
a real tenant URL — neither is appropriate for CI).

Why a gate is necessary: without it, `_check_workflows` on a
simplified-install tenant falls through to the credential-resolution
path and emits ``"Workday ISU credentials not provided"`` along with a
remediation telling the operator to provide ISU creds. That's actively
misleading on a tenant that intentionally has no ISU (OBO uses the
signed-in user's identity instead).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest


@dataclass
class _MinimalRunner:
    """Minimal stand-in for FlightCheckRunner. `_check_workflows` only
    needs runner attributes that the credential / metadata resolvers
    look at (none of which we exercise here because the gate fires
    first). `config` is referenced by the resolver paths, so we
    default it to an empty dict."""

    config: dict[str, Any] = field(default_factory=dict)


class TestSimplifiedInstallGate:
    @pytest.fixture(autouse=True)
    def _isolate_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Isolate every test in this class from the developer's ambient
        environment. When the gate does NOT fire, `_check_workflows` ->
        `_resolve_workday_metadata` reads `WORKDAY_BASE_URL` /
        `WORKDAY_TENANT` / `WORKDAY_TEST_EMPLOYEE_ID` from `os.environ`,
        then `_read_mcp_workday_env()` parses `.vscode/mcp.json` from
        CWD, and if all are empty + `sys.stdin.isatty()` is True it
        calls `input("  Test Employee ID …")`.

        A developer with any of those env vars set, or running pytest
        from a workspace containing a `.vscode/mcp.json` with
        `WORKDAY_BASE_URL`/`WORKDAY_TENANT`, would otherwise see a
        different SKIP message (e.g. ``"No test employee ID provided"``
        / ``"Workday ISU credentials not provided"``) and the
        ``"not configured" in r.result.lower()`` assertions would fail.
        Worse, `pytest -s` would activate the interactive prompt and
        hang the test.

        Applied `autouse` so every test in this class — including
        future additions — gets the isolation consistently.
        """
        monkeypatch.delenv("WORKDAY_BASE_URL", raising=False)
        monkeypatch.delenv("WORKDAY_TENANT", raising=False)
        monkeypatch.delenv("WORKDAY_TEST_EMPLOYEE_ID", raising=False)
        monkeypatch.chdir(tmp_path)

    def test_simplified_skips_with_correct_message(self) -> None:
        """`flavor == "simplified"` → single SKIPPED `WD-WF-000` row in
        the `Workday Workflows` category, zero metadata resolution
        (no `.vscode/mcp.json` read, no `.local/config.json` read, no
        interactive prompt). The gate fires before any credential
        resolution work.
        """
        from flightcheck.checks.workday import _check_workflows

        runner = _MinimalRunner()
        runner._workday_package_flavor = "simplified"

        results = _check_workflows(runner)

        assert len(results) == 1
        r = results[0]
        assert r.checkpoint_id == "WD-WF-000"
        assert r.category == "Workday Workflows"
        assert r.status == "Skipped"
        assert r.priority == "High"
        assert "WD-PKG-001" in r.result
        assert "simplified" in r.result.lower()
        # Remediation must surface the `{ff0df}`-only ambiguity so
        # operators who intended the full install don't dismiss it.
        assert "Generic User" in r.remediation
        assert "Context Generic User" in r.remediation
        assert "workday-simplified-setup" in r.doc_link

    def test_attribute_absent_falls_through_to_existing_logic(self) -> None:
        """Backwards-compat: when `_workday_package_flavor` isn't set
        (e.g. a test minimal-runner or a runner where WD-PKG-001
        couldn't run), the gate must NOT fire. The existing
        credential-missing path then emits the "Workday not
        configured" SKIP for `WD-WF-000` (because our minimal runner
        has no MCP / config-resolved Workday URL).

        Pin both that the gate didn't suppress the result AND that
        the result is the credential-missing one, not the gate's
        flavor-not-applicable one.
        """
        from flightcheck.checks.workday import _check_workflows

        runner = _MinimalRunner()
        assert not hasattr(runner, "_workday_package_flavor")

        results = _check_workflows(runner)

        assert len(results) == 1
        r = results[0]
        assert r.checkpoint_id == "WD-WF-000"
        assert r.status == "Skipped"
        # The pre-existing credential-missing message (NOT the gate's
        # flavor message). Catches a regression where the gate text
        # leaks into the no-attribute branch.
        assert "WD-PKG-001" not in r.result
        assert "not configured" in r.result.lower()

    @pytest.mark.parametrize(
        "flavor", ["full", "partial", "unknown", "none", "skipped"]
    )
    def test_non_simplified_verdicts_fall_through(self, flavor: str) -> None:
        """Safety rule (AGENTS.md design principle #11.b): the gate
        skips ONLY on a positive ``"simplified"`` match. Any other
        verdict — including ``"full"`` (where ISU checks are clearly
        applicable) AND the ambiguous values ``"partial"`` /
        ``"unknown"`` / ``"none"`` / ``"skipped"`` (where the
        fingerprint couldn't reach a confident answer) — must fall
        through to the existing logic.

        Without this pin, a future careless rewrite like
        ``if flavor != "full": skip`` or
        ``if flavor in {"simplified", "partial", "unknown"}: skip``
        would silently suppress workflow diagnostics on intermediate
        states — exactly the failure mode the safety rule exists to
        prevent. Mirrors the same parametrized test in
        `test_workday_env_vars.py` (`TestSimplifiedInstallGate
        .test_ambiguous_verdicts_still_run_existing_logic`) and
        `test_workday_isu_username_format.py`.

        Note: the no-attribute branch is covered separately by
        `test_attribute_absent_falls_through_to_existing_logic`
        (explicit `not hasattr` precondition); this parametrize
        intentionally pins only the attribute-SET-to-non-simplified
        cases so each test has a single, focused failure mode.
        """
        from flightcheck.checks.workday import _check_workflows

        runner = _MinimalRunner()
        runner._workday_package_flavor = flavor

        results = _check_workflows(runner)

        assert len(results) == 1
        r = results[0]
        assert r.checkpoint_id == "WD-WF-000"
        assert r.status == "Skipped"
        # Gate text must NOT leak into the fall-through branch.
        assert "WD-PKG-001" not in r.result, (
            f"flavor={flavor!r} leaked gate text into result"
        )
        # The existing credential-missing SKIP message.
        assert "not configured" in r.result.lower()
