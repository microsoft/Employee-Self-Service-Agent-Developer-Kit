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
from typing import Any


@dataclass
class _MinimalRunner:
    """Minimal stand-in for FlightCheckRunner. `_check_workflows` only
    needs runner attributes that the credential / metadata resolvers
    look at (none of which we exercise here because the gate fires
    first). `config` is referenced by the resolver paths, so we
    default it to an empty dict."""

    config: dict[str, Any] = field(default_factory=dict)


class TestSimplifiedInstallGate:
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
