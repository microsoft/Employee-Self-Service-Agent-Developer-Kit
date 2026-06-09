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
import responses

from tests.conftest import (
    FAKE_DATAVERSE_URL,
    FAKE_TOKEN,
    require_validated_mock,
)
from tests.mocks import dataverse as dv

require_validated_mock(dv)


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
    # Catalog matching — MANUAL path (the core acceptance criterion)
    # ------------------------------------------------------------------

    @responses.activate
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
            # A clearly-not-shipped name. If a managed row ever has this
            # exact name the test breaks loudly — that's the intended
            # behaviour.
            scenario_name="msdyn_HRCustomNotInCatalogXYZ_TestOnly",
        )
        # Empty managed-row response → every discovered scenario is
        # treated as custom and surfaces as MANUAL.
        _register_template_configs_response(rows=[])

        runner = _RunnerWithDataverse()
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
        # Pin specific actionable phrases the operator needs to act:
        assert "msdyn_employeeselfservicetemplateconfigs" in r.remediation
        assert "/create-eval" in r.remediation
        # AC3 ("found a new pattern? log it here" loop-back) is pinned
        # separately by test_checklist_includes_gap_discovery_loopback
        # below — keep that test in lockstep with the AC3 paragraph in
        # _WD_WF_CAT_CHECKLIST.

    @responses.activate
    def test_checklist_includes_gap_discovery_loopback(
        self, tmp_path: Path
    ) -> None:
        """AC3: the MANUAL remediation MUST include a "found a new
        pattern? log it here" paragraph that closes the loop back to
        the kit's gap-discovery process. Without it, customers who hit
        a detection gap (e.g. a Pattern C wiring the walker doesn't
        catch) or a scenario they believe should ship OOTB have no
        canonical channel to forward that signal, and WD-WF-CAT-001
        can't improve over time.

        The original commit eb02d32 included this loop-back text; the
        Dataverse-API refactor (0fb2383) dropped it on the rationale
        that kit-side PRs aren't the remediation for the catalog
        anymore. But AC3 is broader than the catalog — it covers
        detection-pattern gaps and OOTB-promotion feedback too. Pin
        the restored paragraph here so a future drive-by edit that
        re-strips it fails CI, not silently ships a weaker checklist.
        """
        from flightcheck.checks.workday import _check_custom_workflow_inventory

        agent_dir = tmp_path / "workspace" / "agents" / "ess-hr"
        _write_topic_system_common_execution(
            agent_dir / "topics" / "custom.mcs.yml",
            scenario_name="msdyn_HRCustomAC3Test_Unknown",
        )
        # Empty managed-row response → scenario surfaces as MANUAL so
        # the full _WD_WF_CAT_CHECKLIST renders (the loop-back text
        # is part of the same checklist, not a separate row).
        _register_template_configs_response(rows=[])

        runner = _RunnerWithDataverse()
        results = _check_custom_workflow_inventory(runner)

        r = _result_by_id(results, "WD-WF-CAT-001")
        assert r.status == "Manual"

        # The verbatim AC3 framing phrase from the ticket. If this
        # disappears the next time someone refactors the checklist,
        # CI must catch it.
        assert "Found a new pattern" in r.remediation, (
            "AC3 loop-back framing dropped from checklist — operators "
            "have no canonical channel to log gap-discovery feedback"
        )
        assert "gap-discovery process" in r.remediation, (
            "AC3 must explicitly name the gap-discovery process so "
            "operators understand where the loop closes"
        )
        # The actionable channel: the kit repo's issues page. Pin the
        # exact URL — a typo'd link is worse than no link (operator
        # files an issue against a 404 and the signal is lost).
        assert (
            "https://github.com/microsoft/"
            "Employee-Self-Service-Agent-Developer-Kit/issues/new"
        ) in r.remediation, (
            "AC3 loop-back must link to the kit repo issues page so "
            "feedback reaches the team that owns WD-WF-CAT-001"
        )
        # The three gap categories the loop-back exists to capture —
        # if any are dropped, the loop closes on a narrower set of
        # signals than AC3 requires.
        assert "should ship OOTB" in r.remediation, (
            "AC3 must invite OOTB-promotion feedback (scenarios "
            "customers routinely build custom that Microsoft should "
            "ship in the extension pack)"
        )
        assert "detection walker" in r.remediation, (
            "AC3 must invite detection-pattern feedback (a topic "
            "wiring shape the walker missed)"
        )
        assert "checklist above was insufficient" in r.remediation, (
            "AC3 must invite checklist-completeness feedback (the "
            "4-item checklist itself can grow as new failure modes "
            "are discovered)"
        )

    # ------------------------------------------------------------------
    # Pattern B (InvokeFlowAction → Workday-bound flow)
    # ------------------------------------------------------------------

    @responses.activate
    def test_invoke_flow_action_workday_bound_emits_manual(
        self, tmp_path: Path
    ) -> None:
        """Pattern B: a topic that calls a custom cloud flow bound to
        `shared_workdaysoap` is ALWAYS unknown (Dataverse template
        configs key by scenarioName; customer-built flow GUIDs don't
        appear there) — surface MANUAL with the flow GUID + topic
        location named verbatim."""
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
        # Dataverse returns some managed rows — but flow-bound refs
        # are ALWAYS unknown regardless of catalog contents, so this
        # test still gets MANUAL.
        _register_template_configs_response(rows=[
            _template_config_row(name="msdyn_SomeOtherScenario", ismanaged=True),
        ])

        runner = _RunnerWithDataverse()
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

    @responses.activate
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
        # Empty managed-row response → all 3 surface as unknown.
        _register_template_configs_response(rows=[])

        runner = _RunnerWithDataverse()
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

    @responses.activate
    def test_discovery_results_cached_on_runner(self, tmp_path: Path) -> None:
        """`_check_custom_workflow_inventory` caches discovery on the
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
        # Empty managed-row response so the scenario surfaces as
        # unknown (which is what the cache needs to capture).
        _register_template_configs_response(rows=[])

        runner = _RunnerWithDataverse()
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

    @responses.activate
    def test_trailer_emitted_when_unknowns_exist(self, tmp_path: Path) -> None:
        """AC2: when an unknown Workday workflow name is referenced in
        customer topics, the SOAP-test output MUST emit a cross-link
        row pointing at WD-WF-CAT-001 so an admin reading a clean
        17-row pass doesn't miss the manual row below it.

        Note: the trailer relies on `_get_unknown_workday_scenarios`
        which in turn needs the live Dataverse catalog. Without
        credentials the inventory check SKIPs and the trailer
        self-suppresses (the main SKIPPED row is the single source of
        truth). So this test wires up env_url/dv_token + a mocked
        empty managed-row response so the unknown surfaces."""
        from flightcheck.checks.workday import _check_workflows

        agent_dir = tmp_path / "workspace" / "agents" / "ess-hr"
        _write_topic_system_common_execution(
            agent_dir / "topics" / "custom.mcs.yml",
            scenario_name="msdyn_HRCustomTrailerTest",
        )
        # Empty managed-row response → topic scenario surfaces as
        # unknown → trailer fires.
        _register_template_configs_response(rows=[])

        @dataclass
        class R:
            env_url: str = FAKE_DATAVERSE_URL
            dv_token: str = FAKE_TOKEN
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


# ─────────────────────────────────────────────────────────────────────────
# Catalog source resolution (Dataverse-only)
#
# The OOTB catalog is resolved by `_get_workday_ootb_catalog(runner)`:
# a single Dataverse query against
# `msdyn_employeeselfservicetemplateconfigs` filtered by
# `ismanaged=true`. There is NO fallback — when the catalog cannot be
# resolved, AGENTS.md principle #1 requires SKIPPED (no token) or
# WARNING (query error) instead of a misleading PASSED. These tests
# pin every leg of that decision matrix so a future refactor that
# re-introduces a silent fallback fails CI.
#
# Per tests/AGENTS.md: Dataverse is the `documented` tier — no cassette
# required, mock is built from MS Learn-documented response shape via
# `tests.mocks.dataverse`. `require_validated_mock(dv)` at module top
# enforces this can never silently downgrade to placeholder.
# ─────────────────────────────────────────────────────────────────────────


@dataclass
class _RunnerWithDataverse:
    """Runner that exposes env_url + dv_token so `_get_workday_ootb_catalog`
    follows the Dataverse leg (default-skipped on `_MinimalRunner`)."""
    env_url: str = FAKE_DATAVERSE_URL
    dv_token: str = FAKE_TOKEN
    config: dict[str, Any] = field(default_factory=dict)


def _template_config_row(*, name: str, ismanaged: bool) -> dict[str, Any]:
    """Build one `msdyn_employeeselfservicetemplateconfigs` record matching
    the `msdyn_name,ismanaged` select projection the production helper
    requests. Shape sourced from MS Learn Web API reference (the
    `tests.mocks.dataverse` module is `documented` tier — see its
    `MOCK_STATUS`)."""
    return {
        "@odata.etag": 'W/"1"',
        "msdyn_name": name,
        "ismanaged": ismanaged,
    }


def _register_template_configs_response(
    *,
    base_url: str = FAKE_DATAVERSE_URL,
    rows: list[dict[str, Any]] | None = None,
    status: int = 200,
) -> None:
    """Register a `responses` mock for the template-configs query. URL is
    path-only (no query string) so it matches regardless of the exact
    $select / $filter / paging params the production code builds."""
    payload = dv.collection(rows or []) if status == 200 else {"error": {"message": "mock failure"}}
    responses.add(
        method="GET",
        url=f"{base_url}/api/data/v9.2/msdyn_employeeselfservicetemplateconfigs",
        json=payload,
        status=status,
    )


class TestCatalogSource:
    """Pin Dataverse-only semantics of `_get_workday_ootb_catalog`.
    The four tests below cover every leg of the resolver's decision
    matrix: (a) Dataverse-success with managed rows → catalog used,
    (b) Dataverse-success with NO managed rows → check still runs (no
    implicit PASS) and falls through to MANUAL because the
    topic-referenced scenario is not in the managed set, (c) no
    Dataverse token → SKIPPED (cannot validate without the catalog,
    per AGENTS.md principle #1), (d) Dataverse query errors →
    WARNING with the error message surfaced verbatim (per principle
    #3 — fail loudly on API errors)."""

    @pytest.fixture(autouse=True)
    def _isolate_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.chdir(tmp_path)

    @responses.activate
    def test_dataverse_managed_rows_used_as_catalog(
        self, tmp_path: Path
    ) -> None:
        """When Dataverse is reachable and returns a managed
        (ismanaged=true) row whose `msdyn_name` matches a topic's
        scenarioName, the scenario is treated as OOTB and the check
        PASSES. The result text MUST name Dataverse + ismanaged=true
        as the source so an operator inspecting a green report knows
        the catalog was tenant-accurate."""
        from flightcheck.checks.workday import _check_custom_workflow_inventory

        custom_scenario = "msdyn_HRWorkdayTenantSpecificScenario_XYZ"
        agent_dir = tmp_path / "workspace" / "agents" / "ess-hr"
        _write_topic_system_common_execution(
            agent_dir / "topics" / "tenant-scenario.mcs.yml",
            scenario_name=custom_scenario,
        )

        # Tenant has this scenario installed as a managed template
        # config — i.e. it ships in the customer's Workday extension
        # pack. Without the live-Dataverse leg, this would surface
        # as MANUAL (no JSON seed exists to fall back to).
        _register_template_configs_response(rows=[
            _template_config_row(name=custom_scenario, ismanaged=True),
        ])

        runner = _RunnerWithDataverse()
        results = _check_custom_workflow_inventory(runner)

        r = _result_by_id(results, "WD-WF-CAT-001")
        assert r.status == "Passed", (
            f"Dataverse-managed scenario must surface as PASSED — "
            f"the Dataverse-resolution leg regressed. "
            f"Got {r.status!r}: {r.result!r}"
        )
        # Source attribution pinned per principle #8 (`result` =
        # observed). Operators must know the catalog was tenant-live.
        assert "Dataverse" in r.result
        assert "ismanaged=true" in r.result
        # Cache populated with status "ok" for re-reads by the trailer.
        assert runner._workday_ootb_catalog_cache[1] == "ok"
        assert custom_scenario in runner._workday_ootb_catalog_cache[0]

    @responses.activate
    def test_dataverse_unmanaged_rows_excluded_from_catalog(
        self, tmp_path: Path
    ) -> None:
        """`ismanaged=false` rows are customer-added template configs,
        NOT shipped by the extension pack. They must NOT count as OOTB
        — otherwise a customer who added a custom scenario via /create
        would see it falsely treated as "validated by Microsoft" and
        skip the MANUAL checklist that exists to catch payload /
        auth / test-prompt gaps. Pin the filter explicitly."""
        from flightcheck.checks.workday import _check_custom_workflow_inventory

        custom_scenario = "msdyn_HRWorkdayCustomerAuthored_ABC"
        agent_dir = tmp_path / "workspace" / "agents" / "ess-hr"
        _write_topic_system_common_execution(
            agent_dir / "topics" / "customer-auth.mcs.yml",
            scenario_name=custom_scenario,
        )

        # Same name exists in Dataverse but ismanaged=false → customer-
        # authored, not OOTB. Must NOT short-circuit the MANUAL row.
        _register_template_configs_response(rows=[
            _template_config_row(name=custom_scenario, ismanaged=False),
        ])

        runner = _RunnerWithDataverse()
        results = _check_custom_workflow_inventory(runner)

        r = _result_by_id(results, "WD-WF-CAT-001")
        assert r.status == "Manual", (
            f"ismanaged=false rows must NOT count as OOTB — "
            f"the customer-added scenario should surface as MANUAL "
            f"for review. Got {r.status!r}: result={r.result!r}"
        )
        assert custom_scenario in r.result
        assert "ISU account" in r.remediation  # full checklist still emitted
        # Cache: Dataverse WAS reached (status "ok"), it just returned
        # no managed rows. The empty catalog correctly excludes the
        # unmanaged scenario.
        assert runner._workday_ootb_catalog_cache[1] == "ok"
        assert custom_scenario not in runner._workday_ootb_catalog_cache[0]

    @responses.activate
    def test_dataverse_query_failure_emits_warning(
        self, tmp_path: Path
    ) -> None:
        """When the Dataverse query errors (500, network issue, expired
        token, etc.), the check MUST emit a WARNING that surfaces the
        error rather than silently passing — per AGENTS.md principle
        #3 ("fail loudly on API errors, never silently swallow them
        as PASS"). There is no JSON fallback: a tenant-accurate
        catalog is the only valid source of truth, and a query error
        means we don't have one."""
        from flightcheck.checks.workday import _check_custom_workflow_inventory

        agent_dir = tmp_path / "workspace" / "agents" / "ess-hr"
        _write_topic_system_common_execution(
            agent_dir / "topics" / "some-scenario.mcs.yml",
            scenario_name="msdyn_AnyScenario_DoesntMatter",
        )

        # Dataverse query 500s — must surface as WARNING, not PASSED
        # and not MANUAL (we cannot tell if it's custom).
        _register_template_configs_response(status=500)

        runner = _RunnerWithDataverse()
        results = _check_custom_workflow_inventory(runner)

        r = _result_by_id(results, "WD-WF-CAT-001")
        assert r.status == "Warning", (
            f"Dataverse query failure must emit WARNING per "
            f"AGENTS.md principle #3, got {r.status!r}: {r.result!r}"
        )
        # Result must name the failure mode so the operator can
        # diagnose. Don't pin the exact error string (it comes from
        # auth.query_all and may evolve) but pin the structural cues.
        assert "Dataverse" in r.result
        assert "msdyn_employeeselfservicetemplateconfigs" in r.result
        assert "failed" in r.result.lower() or "error" in r.result.lower()
        # Remediation must direct the operator to fix the underlying
        # Dataverse problem (not work around it).
        assert "Dataverse" in r.remediation
        # Cache populated with the error status so re-reads don't
        # re-query.
        catalog, status_code = runner._workday_ootb_catalog_cache
        assert catalog is None
        assert status_code.startswith("query_error:")
        # Unknown cache emptied so the trailer self-suppresses (the
        # WARNING row is the single source of truth for this state).
        assert runner._workday_unknown_scenarios == []

    def test_no_dataverse_token_skips(self, tmp_path: Path) -> None:
        """The CI / offline / no-auth runner has no env_url + dv_token.
        The resolver MUST short-circuit to SKIPPED without attempting
        any HTTP call (so this test doesn't even need
        @responses.activate — any HTTP attempt would surface as a
        connection error against an unrouted host). Per AGENTS.md
        principle #1: without the catalog we cannot validate, so we
        must not return PASSED."""
        from flightcheck.checks.workday import _check_custom_workflow_inventory

        agent_dir = tmp_path / "workspace" / "agents" / "ess-hr"
        _write_topic_system_common_execution(
            agent_dir / "topics" / "offline.mcs.yml",
            scenario_name="msdyn_AnyScenario_DoesntMatter",
        )

        # `_MinimalRunner` has no env_url / dv_token — Dataverse path
        # must short-circuit before any HTTP call.
        runner = _MinimalRunner()
        results = _check_custom_workflow_inventory(runner)

        r = _result_by_id(results, "WD-WF-CAT-001")
        assert r.status == "Skipped", (
            f"No-Dataverse-token runner must SKIP per AGENTS.md "
            f"principle #1, got {r.status!r}: {r.result!r}"
        )
        # Result must explain WHY this skipped (so the operator
        # doesn't conflate it with the "Workday not wired up" SKIP).
        assert "Dataverse" in r.result
        assert "credentials" in r.result.lower() or "token" in r.result.lower()
        # Remediation directs the operator at /setup so credentials get
        # cached on the runner.
        assert "/setup" in r.remediation or "Dataverse" in r.remediation
        # Cache: catalog None with "no_token" status code.
        catalog, status_code = runner._workday_ootb_catalog_cache
        assert catalog is None
        assert status_code == "no_token"
        # Unknown cache emptied so the trailer self-suppresses.
        assert runner._workday_unknown_scenarios == []
