# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Pure policy tests; domain snapshots/attestations do not simulate an API."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import json
from types import SimpleNamespace

import pytest

from flightcheck import cli, telemetry
from flightcheck.checks.da_baseline import run_da_baseline_checks
from flightcheck.da_contract import DAApplicability, DADisposition, DAFeature, DAFeatureEvidence
from flightcheck.da_execution import build_da_execution_plan
from flightcheck.da_readiness import build_da_assessment, load_da_evidence, DA_EVIDENCE_SCHEMA
from flightcheck.runner import (
    BUCKET_MANUAL, BUCKET_PASSED, CheckResult, FlightCheckRunner, Status,
    bucket_results, save_results,
)


NOW = datetime(2026, 10, 21, 2, 0, tzinfo=timezone.utc)
CORE = {"DA-AGENT-001", "DA-CONTENT-001", "ENV-004", "PRE-005"}


def _case(*extra):
    agent = {
        "slug": "hr", "schemaName": "gptagent_hr", "releaseLine": "da",
        "botId": "00000000-0000-0000-0000-000000003333",
    }
    context = {
        "tenantId": "00000000-0000-0000-0000-000000001111",
        "environmentId": "00000000-0000-0000-0000-000000002222",
        "agentId": agent["botId"], "agentSlug": "hr", "agentSchemaName": "gptagent_hr",
        "realm": "dev",
    }
    config = {
        "activeAgent": "hr", "agents": [agent], "agent": agent,
        "tenantId": context["tenantId"], "environmentId": context["environmentId"], "realm": "dev",
    }
    full = build_da_execution_plan(config, features={
        DAFeature.WORKDAY: DAFeatureEvidence(True, "domain applicability evidence"),
    })
    keys = CORE | set(extra)
    plan = replace(
        full, coverage=tuple(entry for entry in full.coverage if entry.checkpoint.key in keys),
        profile=replace(full.profile, checkpoint_ids=tuple(
            key for key in full.profile.checkpoint_ids if key in keys
        )), pending=(),
    )
    runner = FlightCheckRunner(scope="full", target_matcher=lambda key: key in keys)
    runner.config, runner.agent_slug, runner.ring = config, "hr", "prod"
    runner.env_id, runner.validation_context = context["environmentId"], context
    runner._da_native_snapshot = {
        "agentId": agent["botId"], "environmentId": context["environmentId"],
        "changeset": {"domain_revision": "one"},
    }
    rows = [CheckResult(key, "Policy domain", "High", "Passed", key, "Domain assertion.")
            for key in plan.profile.checkpoint_ids if key not in {"PRE-005", "WD-DA-MAKER-001", "DA-RUNTIME-001"}]
    wanted = {"PRE-005", "WD-DA-MAKER-001", "DA-RUNTIME-001", "WD-ENTRA-SCOPE-001"} & keys
    # Use actual requirement metadata, not a fabricated external API response.
    manual = run_da_baseline_checks(runner)
    rows = [row for row in rows if row.checkpoint_id not in wanted] + manual
    runner.register("Policy domain", lambda _runner: rows)
    result = runner.run()
    result.validation_context, result.profile = context, "da:full"
    return SimpleNamespace(plan=plan, result=result, runner=runner)


def _assessment(case, records=None):
    return build_da_assessment(case.plan, case.result, case.runner, records, now=NOW)


def _record(case, key="PRE-005", *, outcome="satisfied"):
    assessment = _assessment(case)
    row = next(row for row in case.result.results if row.checkpoint_id == key)
    return {
        "checkpointId": key, "target": assessment["target"],
        "configurationRevision": assessment["configurationRevision"],
        "reviewed": True, "reviewerRole": row.roles[0], "source": "approved-review-reference",
        "observedAt": "2026-10-21T00:00:00Z", "reviewedAt": "2026-10-21T01:00:00Z",
        "validUntil": "2026-10-22T00:00:00Z", "outcome": outcome,
        "evidenceKind": "manual_attestation",
        "details": {
            field: "explicitly reviewed"
            for field in row.evidence["requiredFields"]
            if field not in {"observedAt", "source", "reviewerRole", "configurationRevision"}
        },
    }


def test_manual_check_does_not_make_green_diagnostics_deployment_ready():
    case = _case()
    assert case.result.overall == "READY"
    actual = _assessment(case)
    assert actual["deploymentReadiness"] == "INCOMPLETE"
    assert actual["counts"]["incomplete"] == 1
    assert actual["counts"]["satisfied"] == 3
    assert next(entry for entry in actual["coverage"] if entry["checkpointId"] == "PRE-005")[
        "reasonCodes"
    ] == ["required_evidence_unverified"]
    assert case.result.overall == "READY"


@pytest.mark.parametrize("status,expected", [
    ("Failed", "NOT_READY"), ("Error", "INCOMPLETE"), ("Blocked", "INCOMPLETE"),
    ("Warning", "INCOMPLETE"), ("Skipped", "INCOMPLETE"), ("NotConfigured", "INCOMPLETE"),
])
def test_confirmed_failure_is_distinct_from_missing_evidence(status, expected):
    case = _case()
    next(row for row in case.result.results if row.checkpoint_id == "ENV-004").status = status
    assert _assessment(case, [_record(case)])["deploymentReadiness"] == expected


@pytest.mark.parametrize("outcome,expected", [("satisfied", "READY"), ("defect", "NOT_READY")])
def test_reviewed_attestation_changes_only_the_independent_decision(outcome, expected):
    case = _case()
    before = deepcopy(case.result.results)
    actual = _assessment(case, [_record(case, outcome=outcome)])
    assert actual["deploymentReadiness"] == expected
    assert actual["evidenceReviews"][0]["accepted"] is True
    assert next(entry for entry in actual["coverage"] if entry["checkpointId"] == "PRE-005")[
        "evidenceBasis"
    ] == "reviewed_attestation"
    assert case.result.results == before
    assert case.result.overall == "READY"


@pytest.mark.parametrize("mutation,reason", [
    ("target", "evidence_target_mismatch"), ("realm", "evidence_target_mismatch"),
    ("ring", "evidence_target_mismatch"), ("revision", "evidence_revision_mismatch"),
    ("expired", "evidence_expired_or_future"), ("future", "evidence_expired_or_future"),
    ("naive", "evidence_validity_window_invalid"), ("unreviewed", "evidence_review_missing_or_wrong_role"),
    ("role", "evidence_review_missing_or_wrong_role"), ("details", "evidence_required_details_missing"),
    ("source", "evidence_source_missing"), ("outcome", "evidence_outcome_invalid"),
])
def test_unqualified_evidence_cannot_satisfy_a_requirement(mutation, reason):
    case = _case()
    record = deepcopy(_record(case))
    if mutation in {"target", "realm", "ring"}:
        record["target"][{"target": "agentId", "realm": "realm", "ring": "serviceRing"}[mutation]] = "different"
    else:
        key, value = {
            "revision": ("configurationRevision", "old"),
            "expired": ("validUntil", NOW.isoformat()),
            "future": ("reviewedAt", "2027-01-01T00:00:00Z"),
            "naive": ("observedAt", "2026-10-21T00:00:00"),
            "unreviewed": ("reviewed", False), "role": ("reviewerRole", "unverified role"),
            "details": ("details", {}), "source": ("source", " "), "outcome": ("outcome", []),
        }[mutation]
        record[key] = value
    actual = _assessment(case, [record])
    assert actual["deploymentReadiness"] == "INCOMPLETE"
    assert reason in actual["evidenceReviews"][0]["reasonCodes"]


def test_snapshot_change_invalidates_review_and_unverified_target_cannot_certify_defect():
    case = _case()
    record = _record(case)
    case.runner._da_native_snapshot["changeset"]["changeToken"] = "read-cursor"
    assert _assessment(case, [record])["deploymentReadiness"] == "READY"
    case.runner._da_native_snapshot["changeset"]["domain_revision"] = "two"
    assert "evidence_revision_mismatch" in _assessment(case, [record])["evidenceReviews"][0]["reasonCodes"]
    next(row for row in case.result.results if row.checkpoint_id == "DA-AGENT-001").status = "Failed"
    actual = _assessment(case)
    assert actual["deploymentReadiness"] == "INCOMPLETE"
    assert "verified_configuration_snapshot_unavailable" in actual["issues"]


def test_missing_results_duplicate_buckets_and_dynamic_details_are_not_extra_requirements():
    case = _case("ENV-004-UR-*")
    record = _record(case)
    case.result.results.append(CheckResult("ENV-004-UR-001", "Domain", "High", "Failed", "Detail", "Unbound."))
    actual = _assessment(case, [record])
    assert actual["counts"]["requiredDefinitions"] == 4
    assert actual["deploymentReadiness"] == "READY"
    assert next(entry for entry in actual["coverage"] if entry["checkpointId"] == "ENV-004-UR-*")[
        "observed"
    ] == [{"checkpointId": "ENV-004-UR-001", "status": "Failed"}]
    env = next(row for row in case.result.results if row.checkpoint_id == "ENV-004")
    case.result.results.append(deepcopy(env))
    assert _assessment(case, [record])["counts"]["incomplete"] == 1
    case.result.results = [row for row in case.result.results if row.checkpoint_id != "ENV-004"]
    assert _assessment(case, [record])["counts"]["missingResults"] == 1


def test_alm_package_revision_change_invalidates_attestation():
    case = _case()
    alm = CheckResult("ESS-SOLN-001", "Domain", "High", "Passed", "Origin", "Package commit one.")
    case.result.results.append(alm)
    record = _record(case)
    alm.result = "Package commit two."
    assert "evidence_revision_mismatch" in _assessment(case, [record])["evidenceReviews"][0]["reasonCodes"]


def test_same_checkpoint_can_have_distinct_resource_status_buckets():
    case = _case()
    case.result.results.append(CheckResult("ENV-004", "Domain", "High", "Failed", "Other reference", "Unbound."))
    actual = _assessment(case, [_record(case)])
    env = next(entry for entry in actual["coverage"] if entry["checkpointId"] == "ENV-004")
    assert env["coverageState"] == "observed"
    assert env["evidenceState"] == "defect"


def test_dynamic_family_members_are_not_duplicate_status_buckets():
    case = _case("ENV-004-UR-*")
    # Exercise family reconciliation independently of this historical family's exclusion.
    case.plan = replace(
        case.plan,
        coverage=tuple(
            replace(entry, applicability=DAApplicability.APPLICABLE,
                    checkpoint=replace(entry.checkpoint, disposition=DADisposition.EVALUATOR, required=True))
            if entry.checkpoint.key == "ENV-004-UR-*" else entry
            for entry in case.plan.coverage
        ),
        profile=replace(case.plan.profile, checkpoint_ids=(*case.plan.profile.checkpoint_ids, "ENV-004-UR-*")),
    )
    case.result.results.extend([
        CheckResult(f"ENV-004-UR-{number:03}", "Domain", "High", "Passed", "Detail", "Bound.")
        for number in (1, 2)
    ])
    actual = _assessment(case)
    family = next(entry for entry in actual["coverage"] if entry["checkpointId"] == "ENV-004-UR-*")
    assert family["coverageState"] == "observed"
    assert family["evidenceState"] == "satisfied"
    assert len(family["observed"]) == 2


def test_partial_binding_coverage_and_accepted_flags_do_not_prove_readiness():
    case = _case()
    env = next(row for row in case.result.results if row.checkpoint_id == "ENV-004")
    env.evidence["dependencyCoverageComplete"] = False
    manual = next(row for row in case.result.results if row.checkpoint_id == "PRE-005")
    manual.evidence["accepted"] = True
    actual = _assessment(case)
    assert actual["deploymentReadiness"] == "INCOMPLETE"
    assert actual["counts"]["incomplete"] == 2


def test_attestation_cannot_override_a_failed_automated_assertion():
    case = _case()
    env = next(row for row in case.result.results if row.checkpoint_id == "ENV-004")
    env.status = "Failed"
    record = _record(case)
    record["checkpointId"] = "ENV-004"
    actual = _assessment(case, [_record(case), record])
    assert actual["deploymentReadiness"] == "NOT_READY"
    assert actual["evidenceReviews"][-1]["accepted"] is False
    assert "evidence_cannot_replace_automated_verification" in actual["evidenceReviews"][-1]["reasonCodes"]


def test_permission_deferred_admin_is_visible_without_becoming_a_pass():
    case = _case("WD-ENTRA-SCOPE-001")
    admin = next(row for row in case.result.results if row.checkpoint_id == "WD-ENTRA-SCOPE-001")
    assert admin.status == Status.SKIPPED.value
    actual = _assessment(case, [_record(case)])
    assert actual["deploymentReadiness"] == "INCOMPLETE"
    assert admin in bucket_results(case.result.results)[BUCKET_PASSED]
    assert admin in bucket_results(case.result.results, deferred_as_manual=True)[BUCKET_MANUAL]
    reviewed = _assessment(case, [_record(case), _record(case, "WD-ENTRA-SCOPE-001")])
    assert reviewed["deploymentReadiness"] == "READY"
    assert admin.status == Status.SKIPPED.value


def test_maker_smoke_does_not_replace_published_employee_correlation():
    case = _case("WD-DA-MAKER-001", "DA-RUNTIME-001")
    maker = _record(case, "WD-DA-MAKER-001")
    maker.update(evidenceKind="maker_test_pane")
    maker["details"].update(
        makerTestCategory="copilot_studio_test_pane",
        testTimestamp="2026-10-21T00:00:00Z", outcome="passed",
    )
    records = [_record(case), maker]
    assert _assessment(case, records)["deploymentReadiness"] == "INCOMPLETE"
    runtime = _record(case, "DA-RUNTIME-001")
    runtime.update(evidenceKind="published_employee_runtime")
    runtime["details"].update(
        publishedChannel="teams", publishedRelease="reviewed-published-release",
        employeeTestRunIds=["run-1"], outcomes={"run-1": "passed"},
    )
    assert _assessment(case, [*records, runtime])["deploymentReadiness"] == "READY"
    runtime["details"]["outcomes"] = {"run-1": "failed"}
    invalid = _assessment(case, [*records, runtime])
    assert invalid["deploymentReadiness"] == "INCOMPLETE"
    assert "employee_runtime_outcome_conflict" in invalid["evidenceReviews"][-1]["reasonCodes"]


def test_full_report_uses_one_versioned_decision_and_escapes_review_sources(tmp_path, capsys):
    case = _case("WD-ENTRA-SCOPE-001")
    record = _record(case)
    record["source"] = "<script>not executable</script>"
    case.result.da_assessment = _assessment(case, [record])
    save_results(case.result, str(tmp_path))
    saved = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assessment = saved["da_assessment"]
    assert saved["contract"]["daAssessment"] == assessment
    assert saved["overall"] == saved["contract"]["overall"] == "READY"
    assert assessment["deploymentReadiness"] == "INCOMPLETE"
    html = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "Diagnostics: READY" in html and "DA deployment readiness" in html
    assert "INCOMPLETE" in html and "Coverage reconciliation" in html
    assert "<script>not executable</script>" not in html
    assert "&lt;script&gt;not executable&lt;/script&gt;" in html
    cli._print_prioritized_summary(case.result)
    terminal = capsys.readouterr().out
    assert "Deployment readiness [dev]: INCOMPLETE" in terminal
    assert "Ready for deployment" not in terminal
    assert cli._run_exit_code(case.result) == 1
    case.result.da_assessment = {}
    assert cli._run_exit_code(case.result) == 0


def test_unknown_applicability_and_execution_error_cannot_be_hidden_by_attestation():
    case = _case()
    unknown = next(entry for entry in build_da_execution_plan(case.runner.config).coverage
                   if entry.checkpoint.key == "DA-HANDOFF-001")
    case.plan = replace(case.plan, coverage=(*case.plan.coverage, unknown))
    case.result.results.append(CheckResult(
        "EXEC-001-ERR", "Domain", "High", "Error", "Producer", "Unavailable.",
        evidence={"executionError": True},
    ))
    actual = _assessment(case, [_record(case)])
    assert actual["deploymentReadiness"] == "INCOMPLETE"
    assert actual["counts"]["unknownApplicability"] == 1
    assert "producer_execution_error" in actual["issues"]


@pytest.mark.parametrize("payload", [{}, {"schemaVersion": DA_EVIDENCE_SCHEMA, "records": [None]},
                                     {"schemaVersion": DA_EVIDENCE_SCHEMA, "records": [
                                         {"checkpointId": "PRE-005"}, {"checkpointId": "PRE-005"},
                                     ]}])
def test_malformed_evidence_is_explicitly_rejected(tmp_path, payload):
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        load_da_evidence(str(path))


def test_telemetry_emits_only_bounded_state_and_coverage_counts():
    case = _case()
    assessment = _assessment(case, [_record(case)])
    assessment["sensitive-review-details"] = "must-not-be-emitted"
    data = telemetry._da_assessment_data(SimpleNamespace(da_assessment=assessment))
    assert data["deploymentReadiness"] == "READY"
    assert data["daRequiredDefinitions"] == 4
    assert all(type(value) is int for key, value in data.items() if key != "deploymentReadiness")
    assert "must-not-be-emitted" not in json.dumps(data)
    assert "target" not in data and "configurationRevision" not in data
    case.result.da_assessment = assessment
    events = telemetry.build_events(
        case.result, env="dev", instance_id="instance", tenant_id="tenant",
        agent_id="agent", agent_count=1, scope="full", invocation_source="cli",
        ikey_envelope="o:offline-policy-test",
    )
    assert events[0]["data"]["deploymentReadiness"] == "READY"
    assert events[0]["data"]["daRequiredDefinitions"] == 4
    encoded = json.dumps(events)
    assert "must-not-be-emitted" not in encoded
    assert "approved-review-reference" not in encoded
    assert assessment["configurationRevision"] not in encoded
