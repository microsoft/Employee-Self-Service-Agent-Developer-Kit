# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""DA ISU gates must run before Dataverse reads or credential prompts."""

from types import SimpleNamespace

import pytest
import responses

from flightcheck import registry
from flightcheck.checks import workday
from flightcheck.runner import FlightCheckRunner
from tests.conftest import require_validated_mock
from tests.mocks import dataverse as dv

require_validated_mock(dv)


@pytest.mark.parametrize("flavor", [None, "none", "skipped", "full", "partial", "unknown", "simplified"])
@pytest.mark.parametrize("check", [
    workday._check_env_vars,
    workday._check_isu_username_format,
    workday._check_workflows,
    workday._check_custom_workflow_inventory,
    workday._check_personal_data_write_permission,
])
def test_explicit_da_never_reads_isu_configuration_or_prompts(check, flavor, monkeypatch):
    runner = SimpleNamespace(
        config={
            "activeAgent": "hr",
            "agents": [{"slug": "hr", "releaseLine": "da"}],
        },
        _workday_package_flavor=flavor,
    )

    def unexpected(*args, **kwargs):
        pytest.fail("DA ISU gate allowed a read, credential request or probe")

    for target in ("auth.query_all", "builtins.input", "getpass.getpass"):
        monkeypatch.setattr(target, unexpected)
    for name in ("_resolve_workday_metadata", "_resolve_workday_credentials", "_soap_call"):
        monkeypatch.setattr(workday, name, unexpected)

    results = check(runner)

    assert results
    assert all(row.status in {"Skipped", "Manual"} for row in results)
    assert all("signed-in employee" in row.result for row in results)
    assert all("provide ISU" not in row.remediation for row in results)
    if check is workday._check_personal_data_write_permission:
        assert results[0].status == "Manual"
        assert "Personal Data" in results[0].result


@responses.activate
@pytest.mark.parametrize("target", ["WD-ENV", "WD-ENV-001", "WD-ENV-101", "WD-WF", "WD-WF-000"])
def test_targeted_legacy_checks_hydrate_package_before_applicability(
    target, fake_dataverse_url, fake_token, monkeypatch
):
    runner = FlightCheckRunner(
        scope=f"checkpoint:{target}",
        target_matcher=lambda cid: registry.matches(target, cid),
    )
    runner.env_url = fake_dataverse_url
    runner.dv_token = fake_token
    runner.config = {}
    runner.execution_targets = (target,)
    runner.register("Workday", workday.run_workday_checks)
    refs = [
        *dv.workday_connection_refs_runtime(),
        *dv.workday_connection_refs_simplified(),
    ]
    responses.get(
        f"{fake_dataverse_url}/api/data/v9.2/connectionreferences",
        json=dv.collection(refs),
    )

    def unexpected(*args, **kwargs):
        pytest.fail("non-ISU package attempted credentials or legacy inventory")

    monkeypatch.setattr(workday, "_resolve_workday_metadata", unexpected)
    monkeypatch.setattr(workday, "_get_unknown_workday_scenarios", unexpected)

    report = runner.run()

    assert runner._workday_package_flavor == "simplified"
    assert len(responses.calls) == 1
    assert report.results
    assert all(row.status == "Skipped" for row in report.results)
    assert all(registry.matches(target, row.checkpoint_id) for row in report.results)
