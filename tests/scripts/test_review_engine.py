# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Regression tests for the /review conformance engine's correctness gates.

These pin three defects surfaced by an external review of the /review skill:

  * F-1 -- ``merge_findings._hashes_match`` must judge evidence staleness
    independently of the current working directory. It regressed when the
    security pass anchored ``evidence_hashes`` on the skill root but left the
    match side re-hashing a cwd-relative path, so a finding read as "fresh"
    from the repo root and "stale" from ``scripts/``.
  * F-2 -- the ``scan_*`` detectors must not print a clean all-clear when a
    topic could not be read: an unreadable topic is skipped, so the result
    does not cover it. They must warn and say coverage is incomplete.
  * F-4 -- ``validate_current_findings`` / ``validate_resolutions`` must reject
    out-of-enum ``reachability`` / ``verification`` / ``resolution`` values
    rather than silently coercing them (the ledger is append-only, so a
    coerced dismissal would be misrecorded permanently).

It also pins two defects from a second review of the same skill:

  * AB-1 -- a dismissed finding (``not-a-bug`` / ``wont-fix`` /
    ``false-positive``) must stay ``suppressed`` when a deterministic detector
    re-emits it, until its evidence changes -- it must not resurface as
    ``active`` every run. Re-passing the same dismissal must be idempotent
    (no append-only ledger bloat). A ``fixed`` finding still reopens on
    re-detection (a regression).
  * AB-2 -- ``scan_config`` must resolve a ServiceNow scenario passed inline,
    via a Switch fan-out, or through a transitive delegation hop (so the
    response-field check runs) and return no scenario for an unresolvable
    runtime variable (so it is disclosed, never silently skipped as clean).

The detector tests spawn each script as a subprocess against a throwaway agent
created under the gitignored ``workspace/agents/`` tree, mirroring how the
skill invokes them.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import merge_findings
import scan_config

# scripts/ live directly under the maker-skills root; workspace/agents/ is a
# sibling of scripts/ and is gitignored, so throwaway agents leave no git trace.
_SKILL_ROOT = Path(merge_findings.__file__).resolve().parent.parent
_SCRIPTS_DIR = _SKILL_ROOT / "scripts"
_AGENTS_DIR = _SKILL_ROOT / "workspace" / "agents"

# A real in-tree file, used as stable evidence for the staleness tests.
_EVIDENCE_REL = "scripts/merge_findings.py"


def _finding(**overrides) -> dict:
    """A minimal finding that passes validate_current_findings, with overrides."""
    finding = {
        "id": "sample-finding",
        "title": "Sample finding",
        "severity": "MEDIUM",
        "reachability": "REACHABLE_NORMAL_UI",
        "root_cause": "Something is wrong.",
        "concrete_fix": "Fix the thing.",
        "files": [{"path": _EVIDENCE_REL}],
    }
    finding.update(overrides)
    return finding


# --------------------------------------------------------------------------- #
# F-1 -- staleness is cwd-independent
# --------------------------------------------------------------------------- #

def test_hashes_match_is_cwd_independent(monkeypatch, tmp_path):
    stored = merge_findings.evidence_hashes(_finding())
    assert stored and stored[0]["sha256"], "evidence hash should be populated"

    monkeypatch.chdir(_SKILL_ROOT)
    assert merge_findings._hashes_match(stored) is True

    # From an unrelated directory the verdict must not flip.
    monkeypatch.chdir(tmp_path)
    assert merge_findings._hashes_match(stored) is True

    monkeypatch.chdir(_SCRIPTS_DIR)
    assert merge_findings._hashes_match(stored) is True


def test_hashes_match_rejects_null_and_escaping():
    # A stored hash of None (file was unreadable at store time) is a mismatch,
    # never "unchanged".
    assert merge_findings._hashes_match([{"file": _EVIDENCE_REL, "sha256": None}]) is False
    # An empty ledger of hashes is a mismatch, not a vacuous match.
    assert merge_findings._hashes_match([]) is False
    # A path that escapes the skill tree cannot be silently treated as fresh.
    assert merge_findings._hashes_match([{"file": "../../etc/hosts", "sha256": "deadbeef"}]) is False


# --------------------------------------------------------------------------- #
# F-4 -- enum validation rejects, never coerces
# --------------------------------------------------------------------------- #

def test_valid_finding_passes():
    assert merge_findings.validate_current_findings([_finding()]) == []


@pytest.mark.parametrize(
    "override",
    [
        {"reachability": "confirmed"},          # not an enum value (the F-4 example bug)
        {"verification": "runtime"},            # not static / needs-runtime-test
        {"severity": "CRITICAL"},               # not HIGH / MEDIUM / LOW
        {"files": [{"path": "../../secret"}]},  # escapes the workspace
        {"files": []},                          # no path -> evidence_hashes empty
    ],
)
def test_invalid_finding_is_rejected(override):
    errors = merge_findings.validate_current_findings([_finding(**override)])
    assert errors, f"expected a validation error for {override}"


def test_resolution_validation():
    assert merge_findings.validate_resolutions([{"id": "x", "resolution": "fixed"}]) == []
    # An absent resolution is legitimate (defaults to "fixed"); a wrong one is not.
    assert merge_findings.validate_resolutions([{"id": "x"}]) == []
    assert merge_findings.validate_resolutions([{"id": "x", "resolution": "resolved"}])


# --------------------------------------------------------------------------- #
# F-2 -- an unreadable topic never yields a clean all-clear
# --------------------------------------------------------------------------- #

@pytest.fixture
def temp_agent():
    """Create a throwaway agent with one readable and one undecodable topic.

    Lives under the gitignored workspace/agents/ tree so it never pollutes git
    status; removed on teardown.
    """
    name = f"_pytest_{uuid.uuid4().hex}"
    agent_dir = _AGENTS_DIR / name
    topics = agent_dir / "topics"
    topics.mkdir(parents=True)
    (agent_dir / "variables").mkdir()

    good = (
        "kind: AdaptiveDialog\n"
        "beginDialog:\n"
        "  kind: OnRecognizedIntent\n"
        "  actions: []\n"
    )
    (topics / "good.mcs.yml").write_text(good, encoding="utf-8", newline="\r\n")
    # Bytes that decode cleanly as neither UTF-8 nor UTF-16 -> read is skipped.
    (topics / "bad.mcs.yml").write_bytes(b"\xff\xfe\x00\x80\x81\xff")

    try:
        yield name
    finally:
        shutil.rmtree(agent_dir, ignore_errors=True)


@pytest.mark.parametrize("script", ["scan_globals.py", "scan_bindings.py", "scan_config.py"])
def test_detector_flags_incomplete_coverage_on_unreadable_topic(temp_agent, script):
    proc = subprocess.run(
        [sys.executable, str(_SCRIPTS_DIR / script), "--agent", temp_agent],
        capture_output=True,
        text=True,
    )
    combined = proc.stdout + proc.stderr
    # The skill reads detector output; a non-zero exit could abort the flow, so
    # the detector must stay exit 0 while disclosing the gap.
    assert proc.returncode == 0, combined
    assert "NOT analyzed" in combined, combined
    assert "coverage is incomplete" in proc.stdout, combined


# --------------------------------------------------------------------------- #
# AB-1 -- a dismissed finding stays suppressed on re-detect (no resurfacing)
# --------------------------------------------------------------------------- #

def _evidence_sha() -> str:
    return merge_findings.evidence_hashes(_finding())[0]["sha256"]


def _ledger_line(resolution: str, evidence_hash, solution: str = "demo") -> dict:
    return {
        "id": "sample-finding:r1",
        "solution": solution,
        "issue_id": "sample-finding",
        "resolution": resolution,
        "evidence_hash": evidence_hash,
    }


def test_dismissed_finding_suppressed_on_same_run_redetect():
    resolutions = {"sample-finding": {"ref": "sample-finding:r1", "resolution": "not-a-bug"}}
    merged = merge_findings.merge(
        [], [_finding()], resolutions, "2026-07-13", ledger=[], solution="demo"
    )
    assert merged[0]["status"] == "suppressed"
    assert merged[0]["resolution"] == "not-a-bug"


def test_prior_dismissal_suppresses_only_while_evidence_unchanged():
    same = [_ledger_line("not-a-bug", _evidence_sha())]
    merged = merge_findings.merge([], [_finding()], {}, "d", ledger=same, solution="demo")
    assert merged[0]["status"] == "suppressed"

    changed = [_ledger_line("not-a-bug", "deadbeef")]
    merged = merge_findings.merge([], [_finding()], {}, "d", ledger=changed, solution="demo")
    assert merged[0]["status"] == "active"


def test_fixed_finding_reopens_on_redetect():
    fixed = [_ledger_line("fixed", _evidence_sha())]
    merged = merge_findings.merge([], [_finding()], {}, "d", ledger=fixed, solution="demo")
    assert merged[0]["status"] == "active"


def test_dismissal_is_scoped_by_solution():
    other = [_ledger_line("not-a-bug", _evidence_sha(), solution="OTHER")]
    merged = merge_findings.merge([], [_finding()], {}, "d", ledger=other, solution="demo")
    assert merged[0]["status"] == "active"


def test_append_resolutions_is_idempotent(monkeypatch, tmp_path):
    # ledger_path() is cwd-relative (.local/review-findings/), so chdir isolates it.
    monkeypatch.chdir(tmp_path)
    resolved = [{"id": "sample-finding", "resolution": "not-a-bug"}]
    for _ in range(3):
        ledger = merge_findings._read_jsonl(merge_findings.ledger_path())
        merge_findings.append_resolutions(
            resolved, [[_finding()]], "demo", "2026-07-13", ledger
        )
    final = merge_findings._read_jsonl(merge_findings.ledger_path())
    matches = [e for e in final if e.get("issue_id") == "sample-finding"]
    assert len(matches) == 1, final


# --------------------------------------------------------------------------- #
# AB-2 / AB-2b -- ServiceNow scenario resolution (inline, Switch, transitive)
# --------------------------------------------------------------------------- #

def test_resolve_scenarios_reads_inline_literal():
    node = {"input": {"binding": {"ScenarioName": '="msdyn_ServiceNowHRSDGetCaseDetails"'}}}
    assert scan_config._resolve_scenarios(node, None, {}, {}) == ["msdyn_ServiceNowHRSDGetCaseDetails"]


def test_resolve_scenarios_empty_for_unresolvable_runtime_variable():
    # A runtime variable with no backing Switch cannot be resolved statically, so
    # it returns [] (the caller discloses it, never silently reports clean).
    node = {"input": {"binding": {"ScenarioName": "=Topic.MappedScenario"}}}
    assert scan_config._resolve_scenarios(node, None, {}, {}) == []
    assert scan_config._resolve_scenarios({"input": {"binding": {}}}, None, {}, {}) == []


def test_switch_scenarios_extracts_every_branch_literal():
    topic = {
        "actions": [
            {
                "kind": "SetVariable",
                "variable": "Topic.MappedScenario",
                "value": (
                    '=Switch(Topic.user_selected_coe, '
                    '"sn_hr_core_case_payroll", "msdyn_ServiceNowHRSDCreateCasePayroll", '
                    '"msdyn_ServiceNowHRSDCreateCaseCore")'
                ),
            }
        ]
    }
    lits = scan_config._switch_scenarios(topic, "MappedScenario")
    assert "msdyn_ServiceNowHRSDCreateCasePayroll" in lits
    assert "msdyn_ServiceNowHRSDCreateCaseCore" in lits


def test_resolve_scenarios_expands_inline_switch_fanout():
    topic = {
        "actions": [
            {
                "kind": "SetVariable",
                "variable": "Topic.MappedScenario",
                "value": (
                    '=Switch(x, "a", "msdyn_ServiceNowHRSDCreateCasePayroll", '
                    '"msdyn_ServiceNowHRSDCreateCaseCore")'
                ),
            }
        ]
    }
    node = {"input": {"binding": {"ScenarioName": "=Topic.MappedScenario"}}}
    result = scan_config._resolve_scenarios(node, None, topic, {})
    assert set(result) == {
        "msdyn_ServiceNowHRSDCreateCasePayroll",
        "msdyn_ServiceNowHRSDCreateCaseCore",
    }


def test_resolve_scenarios_follows_transitive_delegation(tmp_path):
    # A component topic with no literal/inline scenario delegates to a system topic
    # that declares one; resolution must follow that hop.
    system = tmp_path / "system.mcs.yml"
    system.write_text(
        'kind: AdaptiveDialog\nScenarioName: "=\\"msdyn_ServiceNowHRSDGetUserCases\\""\n',
        encoding="utf-8",
        newline="\r\n",
    )
    component = tmp_path / "component.mcs.yml"
    component.write_text(
        "beginDialog:\n"
        "  actions:\n"
        "    - kind: BeginDialog\n"
        "      dialog: ns.topic.ServiceNowHRSDSystemGetCasesList\n",
        encoding="utf-8",
        newline="\r\n",
    )
    component_map = {
        "ServiceNowHRSDSystemGetCasesList": system,
        "ServiceNowHRSDGetUserCases": component,
    }
    node = {"input": {"binding": {}}, "dialog": "ns.topic.ServiceNowHRSDGetUserCases"}
    result = scan_config._resolve_scenarios(node, component, {}, component_map)
    assert result == ["msdyn_ServiceNowHRSDGetUserCases"]


def test_resolve_scenarios_depth_guard_terminates(tmp_path):
    # A cyclic delegation must not recurse without end — the depth guard returns [].
    a = tmp_path / "a.mcs.yml"
    b = tmp_path / "b.mcs.yml"
    a.write_text(
        "actions:\n  - kind: BeginDialog\n    dialog: ns.topic.B\n",
        encoding="utf-8", newline="\r\n",
    )
    b.write_text(
        "actions:\n  - kind: BeginDialog\n    dialog: ns.topic.A\n",
        encoding="utf-8", newline="\r\n",
    )
    component_map = {"A": a, "B": b}
    node = {"input": {"binding": {}}, "dialog": "ns.topic.A"}
    assert scan_config._resolve_scenarios(node, a, {}, component_map) == []


# --------------------------------------------------------------------------- #
# Tier-A critique fixes -- config-unloadable disclosure + producer union
# --------------------------------------------------------------------------- #

def _sn_topic(dialog_suffix: str, scenario_literal: str, out_var: str) -> dict:
    """A topic that begins one ServiceNow dialog (inline scenario) binding out_var."""
    return {
        "actions": [
            {
                "kind": "BeginDialog",
                "dialog": f"ns.topic.{dialog_suffix}",
                "input": {"binding": {"ScenarioName": f'="{scenario_literal}"'}},
                "output": {"binding": {"result": f"Topic.{out_var}"}},
            }
        ]
    }


def test_resolved_scenario_with_unloadable_config_is_disclosed(tmp_path):
    # Scenario resolves, but its template config file does not exist -> the fields
    # went unchecked, so the variable must be disclosed, never reported clean.
    topic = _sn_topic("ServiceNowHRSDSystemGetCasesList", "msdyn_ServiceNowHRSDNoSuchScenario", "Data")
    component_map = {"ServiceNowHRSDSystemGetCasesList": tmp_path / "unused.mcs.yml"}
    v2p, unresolved = scan_config.resolve_response_vars(topic, component_map, tmp_path, set())
    assert "Data" not in v2p
    assert unresolved.get("Data") == "ServiceNowHRSDSystemGetCasesList"


def test_producer_fields_union_across_multiple_dialogs(tmp_path):
    # Two dialogs bind the same response var; the var's produced set is the UNION,
    # so a field produced by either path is not spuriously flagged.
    configs = tmp_path
    (configs / "msdyn-servicenowhrsdscenarioa.json").write_text(
        '{"OutputFieldMapping": [{"OutputName": "FieldA"}]}', encoding="utf-8", newline="\r\n"
    )
    (configs / "msdyn-servicenowhrsdscenariob.json").write_text(
        '{"OutputFieldMapping": [{"OutputName": "FieldB"}]}', encoding="utf-8", newline="\r\n"
    )
    topic = {
        "actions": [
            {
                "kind": "BeginDialog",
                "dialog": "ns.topic.ServiceNowHRSDSystemA",
                "input": {"binding": {"ScenarioName": '="msdyn_ServiceNowHRSDScenarioA"'}},
                "output": {"binding": {"result": "Topic.Shared"}},
            },
            {
                "kind": "BeginDialog",
                "dialog": "ns.topic.ServiceNowHRSDSystemB",
                "input": {"binding": {"ScenarioName": '="msdyn_ServiceNowHRSDScenarioB"'}},
                "output": {"binding": {"result": "Topic.Shared"}},
            },
        ]
    }
    component_map = {
        "ServiceNowHRSDSystemA": configs / "a.mcs.yml",
        "ServiceNowHRSDSystemB": configs / "b.mcs.yml",
    }
    v2p, _ = scan_config.resolve_response_vars(topic, component_map, configs, set())
    assert {"FieldA", "FieldB"} <= v2p["Shared"]
