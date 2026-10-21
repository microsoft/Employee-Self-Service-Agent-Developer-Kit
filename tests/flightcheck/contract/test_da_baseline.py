# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Baseline evidence boundaries and local-only checks; no invented API responses."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from flightcheck import registry
from flightcheck.checks import environment, local_files, publishing
from flightcheck.checks.da_baseline import DA_DEFERRED_ADMIN_CHECKS, run_da_baseline_checks
from flightcheck.da_contract import DAFeature, DAFeatureEvidence
from flightcheck.da_execution import build_da_execution_plan
from flightcheck.runner import CheckResult, Priority, Status
from flightcheck.checks._connection_dependencies import ConnectionAudit, Reference


def _runner(**overrides):
    selected = {
        "slug": "hr", "botId": "00000000-0000-0000-0000-000000003333",
        "schemaName": "gptagent_copilotforemployeeselfservicehr", "releaseLine": "da",
    }
    values = {
        "config": {
            "activeAgent": "hr", "agents": [selected], "agent": selected,
            "environmentId": "00000000-0000-0000-0000-000000002222",
            "setup": "complete", "capacityCheckSkipped": True,
        },
        "agent_slug": "hr", "env_id": "00000000-0000-0000-0000-000000002222",
        "da_full_assessment": True, "validation_context": {"realm": "dev"},
        "results": [], "should_execute": lambda _key: True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_manual_requirements_do_not_accept_setup_or_inventory_as_proof():
    runner = _runner()
    rows = run_da_baseline_checks(runner)
    by_id = {row.checkpoint_id: row for row in rows}
    for key in ("PRE-001", "PRE-002", "PRE-004", "PRE-005", "PRE-006",
                "CONFIG-013", "INFRA-006", "DA-RUNTIME-001", "DA-HANDOFF-001"):
        row = by_id[key]
        assert row.status == Status.MANUAL.value
        assert row.evidence["accepted"] is False
        assert row.evidence["target"]["agentId"] == runner.config["agent"]["botId"]
        assert "configurationRevision" in row.evidence["requiredFields"]
    assert by_id["ENV-001"].status == Status.BLOCKED.value
    runner.results = [CheckResult(
        "DA-AGENT-001", "Native Agent", "High", Status.PASSED.value, "Native access", "Verified",
    )]
    native = next(row for row in run_da_baseline_checks(runner) if row.checkpoint_id == "ENV-001")
    assert native.status == Status.PASSED.value
    assert "not_billing" in native.evidence["evidenceBoundary"]


def test_da_overrides_do_not_repurpose_legacy_environment_or_capacity_checks():
    baseline = registry.profile_requirements(
        registry.ProfileSpec("test", ("ENV-001", "ENV-CAPACITY-001"), ""),
        overrides=registry.DA_CHECKPOINT_OVERRIDES,
    )
    assert baseline.clients == {registry.POWERPLATFORM}
    assert registry.transitive_requirements("ENV-001").clients == {registry.PP_ADMIN}
    assert registry.resolve("ENV-CAPACITY-001").category_fn is environment.run_capacity_check


def test_maker_assessment_skips_admin_checks_without_accepting_them():
    runner = _runner(should_execute=lambda key: key in DA_DEFERRED_ADMIN_CHECKS)
    rows = run_da_baseline_checks(runner)
    assert {row.checkpoint_id for row in rows} == DA_DEFERRED_ADMIN_CHECKS
    for row in rows:
        assert row.status == Status.SKIPPED.value
        assert "maker administrator permissions" in row.result
        assert "has not been verified" in row.result
        assert "do not grant administrator permissions" in row.remediation
        assert row.evidence["administratorCheckDeferred"] is True
        assert row.evidence["accepted"] is False


@pytest.mark.parametrize("body, status", [
    ("displayName: HR\ninstructions: Be helpful.\n", Status.PASSED.value),
    ("displayName: HR\ninstructions: ''\n", Status.FAILED.value),
    ("instructions: Be helpful.\n", Status.FAILED.value),
    ("[malformed", Status.FAILED.value),
])
def test_selected_local_identity_does_not_grade_word_count_or_use_siblings(
    tmp_path, monkeypatch, body, status,
):
    monkeypatch.chdir(tmp_path)
    agents = tmp_path / "workspace" / "agents"
    selected = agents / "hr"
    sibling = agents / "it"
    selected.mkdir(parents=True)
    sibling.mkdir()
    (selected / "agent.mcs.yml").write_text(body, encoding="utf-8")
    (sibling / "agent.mcs.yml").write_text(
        "displayName: IT\ninstructions: " + "A long instruction. " * 80, encoding="utf-8",
    )
    rows = local_files.run_da_local_file_checks(_runner())
    identity = next(row for row in rows if row.checkpoint_id == "CONFIG-007")
    assert identity.status == status
    assert all(row.evidence["agentSlug"] == "hr" for row in rows)
    assert all(not row.evidence["deploymentFreshnessVerified"] for row in rows)
    assert not any(row.checkpoint_id in {"TOPIC-001", "TOPIC-002", "CONFIG-013"} for row in rows)


def test_missing_selected_workspace_is_blocked_even_with_healthy_sibling(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sibling = tmp_path / "workspace" / "agents" / "it"
    sibling.mkdir(parents=True)
    (sibling / "agent.mcs.yml").write_text("displayName: IT\ninstructions: Helpful.\n", encoding="utf-8")
    rows = local_files.run_da_local_file_checks(_runner())
    assert len(rows) == 1 and rows[0].status == Status.BLOCKED.value


@pytest.mark.parametrize("observed_status", [Status.PASSED.value, Status.WARNING.value, Status.MANUAL.value])
def test_capacity_observation_never_certifies_deployment_billing(monkeypatch, observed_status):
    observed = CheckResult(
        "ENV-CAPACITY-001", "Environment", Priority.CRITICAL.value, observed_status,
        "Allocation", "Observed allocation only.", evidence={"outcome": "success", "allocated": 100},
    )
    monkeypatch.setattr(environment, "run_capacity_check", lambda _runner: [observed])
    row = environment.run_da_capacity_check(_runner())[0]
    assert row.status == Status.MANUAL.value
    assert row.evidence["accepted"] is False
    assert row.evidence["allocationObservation"]["allocated"] == 100
    assert "setup skip" in row.remediation
    assert observed.status == observed_status


def test_full_binding_result_is_independent_of_pin_and_retains_partial_coverage(monkeypatch):
    runner = _runner()
    audit = ConnectionAudit(
        references=[Reference(runner.config["agent"]["botId"], "bound", "connector", "connection")],
        warnings=["Topic activation is unknown."],
    )
    monkeypatch.setattr(environment, "audit_connections", lambda _runner: audit)
    pin = Mock(side_effect=AssertionError("ENV-004 must not evaluate a revision policy"))
    monkeypatch.setattr(environment, "_env004_grs_commit_pin_result", pin)
    rows = environment.run_connection_checks(runner)
    summary = next(row for row in rows if row.checkpoint_id == "ENV-004")
    assert summary.status == Status.WARNING.value
    assert summary.evidence["boundReferences"] == 1
    assert summary.evidence["dependencyCoverageComplete"] is False
    pin.assert_not_called()


def test_selected_revision_policy_is_scheduled_separately_and_cannot_be_disabled():
    runner = _runner()
    runner.config["agent"]["expectedGrsCommitSha"] = "a" * 40
    plan = build_da_execution_plan(runner.config)
    assert "ENV-004-GRS" in plan.profile.checkpoint_ids
    with pytest.raises(ValueError, match="Revision-pin"):
        build_da_execution_plan(
            runner.config,
            features={DAFeature.REVISION_PIN: DAFeatureEvidence(False, "conflicting source")},
        )
    runner.config["agent"]["expectedGrsCommitSha"] = ""
    runner.config["expectedGrsCommitSha"] = "b" * 40
    assert "ENV-004-GRS" not in build_da_execution_plan(runner.config).profile.checkpoint_ids


def test_da_publishing_manual_rows_do_not_become_automatic_quality_passes(monkeypatch):
    runner = _runner(should_execute=lambda key: key in {"QA-001", "PUB-002", "PUB-006"})
    import_probe = Mock(side_effect=AssertionError("Full DA must not import"))
    monkeypatch.setattr(publishing, "_check_pub_002_import", import_probe)
    rows = publishing.run_publishing_checks(runner)
    assert {row.checkpoint_id for row in rows} == {"QA-001", "PUB-006"}
    assert all(row.status == Status.MANUAL.value for row in rows)
    assert all(row.evidence["accepted"] is False for row in rows)
    assert "50" not in rows[0].description + rows[0].remediation
    import_probe.assert_not_called()
