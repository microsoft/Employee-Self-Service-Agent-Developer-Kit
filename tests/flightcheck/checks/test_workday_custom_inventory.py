# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for WD-WF-CAT-001 (Workday custom-workflow inventory checklist)
and its WD-WF-CAT-LINK cross-link trailer emitted from inside
`_check_workflows`.

These are PURE-LOGIC tests: the production check makes NO external API
calls — it reads `workspace/agents/*/topics/*.mcs.yml` and
`workspace/agents/*/workflows/*/workflow.json` from the local
filesystem. Per `tests/AGENTS.md` "The cardinal rule does not apply
to: Tests of the kit's pure-logic helpers (no network)." — no
cassettes or mock-tier enforcement needed.

The check covers the WD-001 acceptance criteria (ADO 7392277,
incidents 760098889 / 783902203):

  AC1: Checklist enumerates: which custom Workday workflows are wired
       up, ISU account used, expected payload shape, test prompt.
  AC2: Linked from Test-WorkdayWorkflows output when an unknown
       workflow name is referenced in customer topics.
  AC3: Includes a "found a new pattern? log it here" loop back to
       the gap-discovery process.

Tests below pin each AC explicitly so a future drive-by refactor that
weakens the checklist text fails CI rather than silently ships a
weaker remediation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest


# ─────────────────────────────────────────────────────────────────────────
# Minimal runner — _check_custom_workflow_inventory only reads
# `_workday_package_flavor` and writes the cached `_workday_*` lists.
# ─────────────────────────────────────────────────────────────────────────


@dataclass
class _MinimalRunner:
    config: dict[str, Any] = field(default_factory=dict)


def _result_by_id(results: list, checkpoint_id: str):
    matches = [r for r in results if r.checkpoint_id == checkpoint_id]
    assert len(matches) == 1, (
        f"Expected exactly one result for {checkpoint_id}, got {len(matches)}: "
        f"{[r.checkpoint_id for r in results]}"
    )
    return matches[0]


# ─────────────────────────────────────────────────────────────────────────
# Workspace fixtures — small helpers that lay down realistic
# `workspace/agents/<slug>/topics/` + `workspace/agents/<slug>/workflows/`
# trees under a tmp_path, matching the on-disk shape exactly so the
# production walkers don't need to be parameterized for testing.
# ─────────────────────────────────────────────────────────────────────────


def _write_topic_system_common_execution(
    topic_path: Path, *, scenario_name: str
) -> None:
    """Pattern A: scenarioName + WorkdaySystemGetCommonExecution dialog.

    Layout mirrors `src/examples/ess-samples/Workday/ManagerScenarios/
    WorkdayManagersdirect-CompanyCode/topic.yaml` lines 38-46.
    """
    topic_path.parent.mkdir(parents=True, exist_ok=True)
    topic_path.write_text(
        "kind: AdaptiveDialog\n"
        "beginDialog:\n"
        "  kind: OnRecognizedIntent\n"
        "  id: test-topic\n"
        "  actions:\n"
        "    - kind: BeginDialog\n"
        "      id: Gt044B\n"
        "      displayName: Redirect to Workday Get Common Execution\n"
        "      input:\n"
        "        binding:\n"
        '          parameters: ="{\\"params\\":[]}"\n'
        f"          scenarioName: {scenario_name}\n"
        "\n"
        "      dialog: msdyn_copilotforemployeeselfservicehr.topic.WorkdaySystemGetCommonExecution\n"
        "      output:\n"
        "        binding:\n"
        "          errorResponse: Topic.errorResponse\n",
        encoding="utf-8",
    )


def _write_topic_invoke_flow_action(
    topic_path: Path, *, flow_id: str
) -> None:
    """Pattern B: kind: InvokeFlowAction with a flowId pointing at a
    Workday-bound flow. Layout mirrors the canonical InvokeFlowAction
    shape in `src/examples/ess-samples/Facilities/.../topic.yaml`."""
    topic_path.parent.mkdir(parents=True, exist_ok=True)
    topic_path.write_text(
        "kind: AdaptiveDialog\n"
        "beginDialog:\n"
        "  kind: OnRecognizedIntent\n"
        "  actions:\n"
        "    - kind: InvokeFlowAction\n"
        "      id: invoke-1\n"
        f"      flowId: {flow_id}\n"
        "      input:\n"
        "        binding:\n"
        "          text: =Topic.UserQuery\n"
        "      output:\n"
        "        binding:\n"
        "          response: Topic.Response\n",
        encoding="utf-8",
    )


def _write_workflow(
    agent_dir: Path,
    *,
    workflow_id: str,
    workflow_slug: str,
    api_name: str,
) -> None:
    """Write a minimal workflow folder with `metadata.yml` +
    `workflow.json`. `api_name` controls whether the flow is
    Workday-bound — set to `shared_workdaysoap` to make this a Workday
    flow, anything else (e.g. `shared_servicenow`) makes it
    non-Workday."""
    wf_dir = agent_dir / "workflows" / workflow_slug
    wf_dir.mkdir(parents=True, exist_ok=True)
    (wf_dir / "metadata.yml").write_text(
        f"workflowId: {workflow_id}\n"
        "jsonFileName: workflow.json\n",
        encoding="utf-8",
    )
    (wf_dir / "workflow.json").write_text(
        json.dumps({
            "properties": {
                "connectionReferences": {
                    "primary": {
                        "api": {"name": api_name}
                    }
                }
            }
        }),
        encoding="utf-8",
    )


def _write_catalog_marker_file(tmp_path: Path) -> None:
    """Make sure `Path("workspace/agents")` resolves relative to
    `tmp_path` (the test chdir'd here in the autouse fixture). The
    discovery walker uses `Path("workspace/agents")` directly — a
    relative path resolved against CWD — so no marker file is needed,
    but a `workspace/` dir must exist or the walker returns [] (which
    triggers the "directory not found" SKIP path rather than the
    "no Workday refs" SKIP path)."""
    (tmp_path / "workspace" / "agents").mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────
# Class — keeps the autouse env-isolation fixture from leaking into
# unrelated test files. Mirrors the structure of
# `test_workday_workflows_gate.py::TestSimplifiedInstallGate`.
# ─────────────────────────────────────────────────────────────────────────


class TestCustomWorkflowInventory:
    @pytest.fixture(autouse=True)
    def _isolate_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The production check uses `Path("workspace/agents")` relative
        to CWD. Tests must chdir into tmp_path so each test sees the
        workspace it just built and is isolated from any sibling test
        AND from the developer's repo (which has a real
        `workspace/agents/` for `employee-self-service-it`)."""
        monkeypatch.chdir(tmp_path)

    # ------------------------------------------------------------------
    # Gates
    # ------------------------------------------------------------------

    def test_simplified_install_skips(self) -> None:
        """Principle #11: simplified install (no ISU) has no concept of
        ISU/scenario inventory — the check must short-circuit via the
        canonical `_simplified_install_skip` helper. Pin that the SKIP
        carries WD-PKG-001 reasoning so the operator knows WHY this
        check skipped (vs e.g. a credential-missing skip)."""
        from flightcheck.checks.workday import _check_custom_workflow_inventory

        runner = _MinimalRunner()
        runner._workday_package_flavor = "simplified"

        results = _check_custom_workflow_inventory(runner)

        r = _result_by_id(results, "WD-WF-CAT-001")
        assert r.status == "Skipped"
        assert r.category == "Workday Workflows"
        # `_simplified_install_skip` produces a result that names
        # WD-PKG-001 as the gating check — pin that contract so a
        # future refactor that bypasses the shared helper fails.
        assert "WD-PKG-001" in r.result
        assert "simplified" in r.result.lower()

    def test_no_workspace_directory_skips(self) -> None:
        """If `/setup` hasn't run, there's no `workspace/agents/` and the
        discovery walker has nothing to scan. SKIP with a result that
        names the missing directory verbatim and a remediation that
        directs the operator to `/setup` (so this isn't mistaken for
        a "no Workday in customer's agent" PASS)."""
        from flightcheck.checks.workday import _check_custom_workflow_inventory

        runner = _MinimalRunner()
        # No workspace/agents/ — _isolate_env chdir'd to a clean tmp_path.

        results = _check_custom_workflow_inventory(runner)

        r = _result_by_id(results, "WD-WF-CAT-001")
        assert r.status == "Skipped"
        assert "workspace/agents/" in r.result
        assert "/setup" in r.remediation

    def test_workspace_exists_but_zero_refs_skips(self, tmp_path: Path) -> None:
        """A workspace with topics but ZERO Workday references is not a
        PASS — the customer may simply not use Workday. SKIP with a
        message that names both possibilities (not wired up vs. not
        extracted) so the operator can pick the right next step."""
        from flightcheck.checks.workday import _check_custom_workflow_inventory

        _write_catalog_marker_file(tmp_path)
        agent_dir = tmp_path / "workspace" / "agents" / "test-agent"
        (agent_dir / "topics").mkdir(parents=True, exist_ok=True)
        # Topic that mentions neither WorkdaySystemGetCommonExecution
        # nor an InvokeFlowAction bound to shared_workdaysoap.
        (agent_dir / "topics" / "greeting.mcs.yml").write_text(
            "kind: AdaptiveDialog\n"
            "beginDialog:\n"
            "  kind: OnRecognizedIntent\n"
            "  actions:\n"
            "    - kind: SendActivity\n"
            "      activity: Hello!\n",
            encoding="utf-8",
        )

        runner = _MinimalRunner()
        results = _check_custom_workflow_inventory(runner)

        r = _result_by_id(results, "WD-WF-CAT-001")
        assert r.status == "Skipped"
        # Pin both possibilities so the message stays operator-actionable.
        assert "No Workday scenario references" in r.result
        assert "not wired into" in r.result
        assert "/create" in r.remediation or "/setup" in r.remediation

    # ------------------------------------------------------------------
    # Catalog matching — PASSED path
    # ------------------------------------------------------------------

    def test_all_scenarios_in_catalog_passes(self, tmp_path: Path) -> None:
        """When every discovered Pattern-A scenario is in the OOTB
        catalog JSON, the check returns PASSED with a result that
        states the catalog covers all references. Picks a scenario
        name that is GUARANTEED to be in the catalog seed (verified
        by reading the JSON itself) so this test doesn't drift if a
        future PR renames a scenario."""
        from flightcheck.checks.workday import (
            WORKDAY_SCENARIO_CATALOG_PATH,
            _check_custom_workflow_inventory,
        )

        # Pull a real catalog entry. If the catalog file is somehow
        # empty/missing, this test is meaningless — skip it rather
        # than pass falsely (every Pattern A ref would look "unknown"
        # and the assertion below would fail confusingly).
        catalog_data = json.loads(
            WORKDAY_SCENARIO_CATALOG_PATH.read_text(encoding="utf-8")
        )
        scenarios = catalog_data.get("scenarios", [])
        if not scenarios:
            pytest.skip("Workday scenario catalog is empty — test cannot run")
        known_scenario = scenarios[0]["scenarioName"]

        agent_dir = tmp_path / "workspace" / "agents" / "ess-hr"
        _write_topic_system_common_execution(
            agent_dir / "topics" / "known.mcs.yml",
            scenario_name=known_scenario,
        )

        runner = _MinimalRunner()
        results = _check_custom_workflow_inventory(runner)

        r = _result_by_id(results, "WD-WF-CAT-001")
        assert r.status == "Passed", (
            f"Expected PASSED for catalog-known scenario {known_scenario!r}, "
            f"got {r.status}: result={r.result!r}"
        )
        # Pin that the result mentions the catalog file by path so an
        # operator who wants to inspect / extend the catalog finds it.
        assert "workday_scenario_catalog.json" in r.result
        assert "OOTB" in r.result or "catalog" in r.result.lower()

    # ------------------------------------------------------------------
    # Catalog matching — MANUAL path (the core acceptance criterion)
    # ------------------------------------------------------------------

    def test_unknown_scenario_emits_manual_with_full_checklist(
        self, tmp_path: Path
    ) -> None:
        """The primary acceptance criterion (AC1): an unknown scenario
        surfaces as one MANUAL row with the scenario name in `result`
        and the 4-item checklist (ISU / payload / test prompt / auth)
        in `remediation`. Pins every checklist item literally so a
        drive-by edit that drops one fails CI."""
        from flightcheck.checks.workday import _check_custom_workflow_inventory

        agent_dir = tmp_path / "workspace" / "agents" / "ess-hr"
        _write_topic_system_common_execution(
            agent_dir / "topics" / "custom.mcs.yml",
            # A clearly-not-shipped name. If the catalog ever does
            # include this exact string the test breaks loudly — that's
            # the intended behaviour.
            scenario_name="msdyn_HRCustomNotInCatalogXYZ_TestOnly",
        )

        runner = _MinimalRunner()
        results = _check_custom_workflow_inventory(runner)

        r = _result_by_id(results, "WD-WF-CAT-001")

        # Per AGENTS.md principle #2: MANUAL = "Manual" — must NOT be
        # "Failed" or "Warning". MANUAL does not fail readiness.
        assert r.status == "Manual", (
            f"Custom scenario must surface as MANUAL (per AGENTS.md "
            f"principle #2), got {r.status!r}"
        )
        assert r.priority == "High"

        # `result` (AGENTS.md principle #8: what the kit observed):
        # must name the scenario verbatim + cite the topic file + line.
        assert "msdyn_HRCustomNotInCatalogXYZ_TestOnly" in r.result
        assert "topics/custom.mcs.yml" in r.result
        assert "WorkdaySystemGetCommonExecution" in r.result
        assert "ess-hr" in r.result  # agent slug

        # `remediation` (AGENTS.md principle #8: action only). All four
        # checklist items (AC1 verbatim from the ticket) must appear.
        assert "ISU account" in r.remediation
        assert "Payload shape" in r.remediation
        assert "Test prompt" in r.remediation
        assert "Auth health" in r.remediation
        # AC3: gap-discovery loop must point at the issue tracker + the
        # catalog file path so contributors close the loop.
        assert "github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit" in r.remediation
        assert "workday_scenario_catalog.json" in r.remediation
        # Pin specific actionable phrases the operator needs to act:
        assert "msdyn_employeeselfservicetemplateconfigs" in r.remediation
        assert "/create-eval" in r.remediation

    # ------------------------------------------------------------------
    # Pattern B (InvokeFlowAction → Workday-bound flow)
    # ------------------------------------------------------------------

    def test_invoke_flow_action_workday_bound_emits_manual(
        self, tmp_path: Path
    ) -> None:
        """Pattern B: a topic that calls a custom cloud flow bound to
        `shared_workdaysoap` is ALWAYS unknown (the kit's catalog has
        no concept of customer-built flow GUIDs) — surface MANUAL with
        the flow GUID + topic location named verbatim."""
        from flightcheck.checks.workday import _check_custom_workflow_inventory

        flow_id = "9f1b2c3d-aaaa-bbbb-cccc-111111111111"
        agent_dir = tmp_path / "workspace" / "agents" / "ess-hr"
        _write_topic_invoke_flow_action(
            agent_dir / "topics" / "custom-flow.mcs.yml",
            flow_id=flow_id,
        )
        _write_workflow(
            agent_dir,
            workflow_id=flow_id,
            workflow_slug="ess-hr-workday-9f1b2c3d-xxxx",
            api_name="shared_workdaysoap",
        )

        runner = _MinimalRunner()
        results = _check_custom_workflow_inventory(runner)

        r = _result_by_id(results, "WD-WF-CAT-001")
        assert r.status == "Manual"
        assert "topics/custom-flow.mcs.yml" in r.result
        assert flow_id in r.result
        assert "InvokeFlowAction" in r.result
        assert "shared_workdaysoap" in r.result
        # `flow-bound, no scenarioName` is the literal label
        # _format_unknown_scenarios uses for Pattern B refs — pin it
        # so an operator scanning the output can tell at a glance
        # this is a flow ref, not a scenarioName ref.
        assert "flow-bound" in r.result

    def test_invoke_flow_action_non_workday_is_ignored(
        self, tmp_path: Path
    ) -> None:
        """Conservative qualification (Pattern B): a flow bound to e.g.
        `shared_servicenow` must NOT surface in this check — only
        Workday-connected flows do. Otherwise this check would emit
        false positives for every customer's ServiceNow integration."""
        from flightcheck.checks.workday import _check_custom_workflow_inventory

        flow_id = "abcdef01-2222-3333-4444-555555555555"
        agent_dir = tmp_path / "workspace" / "agents" / "ess-it"
        _write_topic_invoke_flow_action(
            agent_dir / "topics" / "create-ticket.mcs.yml",
            flow_id=flow_id,
        )
        _write_workflow(
            agent_dir,
            workflow_id=flow_id,
            workflow_slug="ess-it-servicenow-aaaa",
            api_name="shared_servicenow",
        )

        runner = _MinimalRunner()
        results = _check_custom_workflow_inventory(runner)

        r = _result_by_id(results, "WD-WF-CAT-001")
        # Zero Workday refs found → SKIPPED with the "not wired in"
        # message, NOT a MANUAL row mentioning the ServiceNow flow.
        assert r.status == "Skipped"
        assert "No Workday scenario references" in r.result
        assert flow_id not in r.result, (
            "ServiceNow-bound flow leaked into Workday inventory output — "
            "_is_workday_bound_workflow_json qualification regressed"
        )

    # ------------------------------------------------------------------
    # Bucketing (AGENTS.md principle #7)
    # ------------------------------------------------------------------

    def test_multiple_unknowns_bucket_into_single_row(
        self, tmp_path: Path
    ) -> None:
        """Principle #7: N unknown scenarios collapse to ONE MANUAL row
        listing all N in `result`, with the de-duplicated 4-item
        checklist as the SINGLE `remediation`. If a future refactor
        emits one row per scenario, the operator sees the checklist
        N times — exactly what bucketing exists to prevent."""
        from flightcheck.checks.workday import _check_custom_workflow_inventory

        agent_dir = tmp_path / "workspace" / "agents" / "ess-hr"
        for n in range(3):
            _write_topic_system_common_execution(
                agent_dir / "topics" / f"custom-{n}.mcs.yml",
                scenario_name=f"msdyn_HRCustomBucketTest_{n}",
            )

        runner = _MinimalRunner()
        results = _check_custom_workflow_inventory(runner)

        # Exactly one row, NOT three.
        cat_rows = [r for r in results if r.checkpoint_id == "WD-WF-CAT-001"]
        assert len(cat_rows) == 1, (
            f"Bucketing regressed: got {len(cat_rows)} WD-WF-CAT-001 rows, "
            f"expected 1 (per AGENTS.md principle #7)"
        )

        r = cat_rows[0]
        assert r.status == "Manual"
        # All three scenario names appear in `result`.
        for n in range(3):
            assert f"msdyn_HRCustomBucketTest_{n}" in r.result, (
                f"Scenario {n} dropped from bucketed result"
            )
        # The checklist appears ONCE in remediation, not three times.
        assert r.remediation.count("ISU account") == 1, (
            "Checklist appears multiple times in remediation — bucketing "
            "should emit a single de-duplicated checklist"
        )

    # ------------------------------------------------------------------
    # Caching contract (the check + the cross-link trailer share state)
    # ------------------------------------------------------------------

    def test_discovery_results_cached_on_runner(self, tmp_path: Path) -> None:
        """`_get_unknown_workday_scenarios` caches discovery on the
        runner so the topic walk runs at most once per flightcheck.
        Without this, `_check_workflows` (trailer) + the main check
        would walk every topic twice. Pin that both caches populate
        on first read."""
        from flightcheck.checks.workday import _check_custom_workflow_inventory

        agent_dir = tmp_path / "workspace" / "agents" / "ess-hr"
        _write_topic_system_common_execution(
            agent_dir / "topics" / "custom.mcs.yml",
            scenario_name="msdyn_HRCustomCacheTest",
        )

        runner = _MinimalRunner()
        # Pre-condition: cache attributes absent.
        assert not hasattr(runner, "_workday_unknown_scenarios")
        assert not hasattr(runner, "_workday_discovered_scenarios")

        _check_custom_workflow_inventory(runner)

        # Post-condition: both caches populated.
        assert hasattr(runner, "_workday_unknown_scenarios")
        assert hasattr(runner, "_workday_discovered_scenarios")
        assert len(runner._workday_unknown_scenarios) == 1
        assert (
            runner._workday_unknown_scenarios[0]["scenarioName"]
            == "msdyn_HRCustomCacheTest"
        )


# ─────────────────────────────────────────────────────────────────────────
# Cross-link trailer (WD-WF-CAT-LINK) — emitted from inside
# `_check_workflows`, satisfies AC2 ("Linked from Test-WorkdayWorkflows
# output"). Lives in its own class because it exercises the
# simplified-install gate of `_check_workflows`, not
# `_check_custom_workflow_inventory`.
# ─────────────────────────────────────────────────────────────────────────


class TestCrossLinkTrailer:
    @pytest.fixture(autouse=True)
    def _isolate_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Mirror the isolation in test_workday_workflows_gate.py — when
        # the simplified gate does NOT fire, `_check_workflows` reaches
        # `_resolve_workday_metadata` which reads env vars + mcp.json.
        # Strip ambient state so tests are deterministic.
        monkeypatch.delenv("WORKDAY_BASE_URL", raising=False)
        monkeypatch.delenv("WORKDAY_TENANT", raising=False)
        monkeypatch.delenv("WORKDAY_TEST_EMPLOYEE_ID", raising=False)
        monkeypatch.chdir(tmp_path)

    def test_trailer_emitted_when_unknowns_exist(self, tmp_path: Path) -> None:
        """AC2: when an unknown Workday workflow name is referenced in
        customer topics, the SOAP-test output MUST emit a cross-link
        row pointing at WD-WF-CAT-001 so an admin reading a clean
        17-row pass doesn't miss the manual row below it."""
        from flightcheck.checks.workday import _check_workflows

        agent_dir = tmp_path / "workspace" / "agents" / "ess-hr"
        _write_topic_system_common_execution(
            agent_dir / "topics" / "custom.mcs.yml",
            scenario_name="msdyn_HRCustomTrailerTest",
        )

        # No Workday credentials configured → _check_workflows exits
        # via the credential-missing SKIP path BEFORE the trailer
        # code. We need the trailer to run regardless, so we exercise
        # the trailer on a runner whose `_workday_package_flavor` is
        # "full" (so the gate doesn't fire) AND where the credential
        # resolver still skips. The trailer code runs AFTER the
        # SOAP-test loop, so it fires unconditionally when there are
        # unknowns. Verify both rows present.
        @dataclass
        class R:
            config: dict = field(default_factory=dict)

        runner = R()
        # Don't set _workday_package_flavor at all → gate doesn't fire
        # (falls through to credential-missing path which emits the
        # WD-WF-000 SKIP row, then the trailer code runs).

        results = _check_workflows(runner)

        # The SKIP row for credentials missing must exist (sanity).
        wd_wf_000 = [r for r in results if r.checkpoint_id == "WD-WF-000"]
        assert len(wd_wf_000) == 1
        assert wd_wf_000[0].status == "Skipped"

        # AC2: the trailer row exists and references the main check.
        trailer = [r for r in results if r.checkpoint_id == "WD-WF-CAT-LINK"]
        assert len(trailer) == 1, (
            f"Trailer WD-WF-CAT-LINK missing — AC2 regression. "
            f"Got rows: {[r.checkpoint_id for r in results]}"
        )
        t = trailer[0]
        assert t.status == "Manual"
        assert t.category == "Workday Workflows"
        assert "WD-WF-CAT-001" in t.remediation, (
            "Trailer must cross-link to WD-WF-CAT-001 — operators read "
            "the trailer text to find the full checklist"
        )
        assert "1 Workday scenario reference" in t.result, (
            f"Trailer must name the count + the bucket — got {t.result!r}"
        )

    def test_trailer_absent_when_clean(self, tmp_path: Path) -> None:
        """When there are zero unknown Workday refs, the trailer MUST
        NOT fire — adding noise to a clean SOAP-test report would
        defeat the purpose. Pin that the absence is intentional, not
        an accident of test setup."""
        from flightcheck.checks.workday import _check_workflows

        # Empty workspace → discovery returns [] → no trailer.
        (tmp_path / "workspace" / "agents").mkdir(parents=True, exist_ok=True)

        @dataclass
        class R:
            config: dict = field(default_factory=dict)

        runner = R()
        results = _check_workflows(runner)

        trailer = [r for r in results if r.checkpoint_id == "WD-WF-CAT-LINK"]
        assert len(trailer) == 0, (
            f"Trailer fired on clean workspace — should only fire when "
            f"unknowns exist. Got: {[(r.checkpoint_id, r.result) for r in trailer]}"
        )
