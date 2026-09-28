# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""End-to-end tests for WD-DA-PKG-001 (DA Workday extension package
installed) in
``solutions/ess-maker-skills/scripts/flightcheck/checks/workday_da.py``.

Mocks the single Dataverse Web API endpoint the check calls (the
``solutions`` table query) with the ``responses`` library, then invokes the
real production helper ``_check_workday_da_package_installed`` and asserts
on the resulting ``CheckResult``. Mirrors the pattern in
``tests/flightcheck/checks/test_solution.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
import responses

from tests.conftest import FAKE_DATAVERSE_URL, require_validated_mock
from tests.mocks import dataverse as dv

require_validated_mock(dv)


# Production module — flightcheck is importable because pyproject.toml puts
# solutions/ess-maker-skills/scripts on pythonpath.
from flightcheck.checks.workday_da import (  # noqa: E402
    _check_workday_da_package_installed,
)


BASE_URL = FAKE_DATAVERSE_URL

# Verbatim from the production check; if these drift, mock-builder URLs will
# stop matching and tests fail loudly with an unregistered-URL error.
SOLN_SELECT = "solutionid,uniquename,friendlyname,ismanaged,version"
SOLN_FILTER = (
    "uniquename eq 'msdyn_copilotforemployeeselfservicedahr' or "
    "uniquename eq 'msdyn_copilotforemployeeselfservicedait' or "
    "uniquename eq 'msdyn_EssDAHRWorkday' or "
    "uniquename eq 'msdyn_EssWorkdayRuntime'"
)

SOLUTION_ID = "22222222-2222-2222-2222-222222222222"


# ───────────────────────────────────────────────────────────────────────
# Minimal runner — mirrors the pattern in test_solution.py.
# ───────────────────────────────────────────────────────────────────────


@dataclass
class _MinimalRunner:
    env_url: str | None
    dv_token: str | None
    config: dict[str, Any] = field(default_factory=dict)
    agent_slug: str | None = None


@pytest.fixture
def runner(fake_dataverse_url: str, fake_token: str) -> _MinimalRunner:
    return _MinimalRunner(env_url=fake_dataverse_url, dv_token=fake_token)


def _select_classic_hr(runner: _MinimalRunner) -> None:
    runner.config = {
        "activeAgent": "ess-hr",
        "agents": [{
            "slug": "ess-hr",
            "schemaName": "msdyn_copilotforemployeeselfservicedahr",
        }],
    }


# ───────────────────────────────────────────────────────────────────────
# Mock payload builders + registration helpers
# ───────────────────────────────────────────────────────────────────────


def _solution_record(
    uniquename: str,
    *,
    version: str = "1.0.0.0",
    ismanaged: bool = True,
) -> dict[str, Any]:
    return {
        "@odata.etag": 'W/"1"',
        "solutionid": SOLUTION_ID,
        "uniquename": uniquename,
        "friendlyname": uniquename,
        "ismanaged": ismanaged,
        "version": version,
    }


def _register_solutions(solutions: list[dict[str, Any]]) -> None:
    responses.add(**dv.query(
        base_url=BASE_URL,
        entity_set="solutions",
        records=solutions,
        select=SOLN_SELECT,
        filter_expr=SOLN_FILTER,
    ))


# ───────────────────────────────────────────────────────────────────────
# Tests — one per verdict path.
# ───────────────────────────────────────────────────────────────────────


def test_skipped_when_env_url_missing() -> None:
    results = _check_workday_da_package_installed(
        _MinimalRunner(env_url=None, dv_token="tok")
    )
    assert len(results) == 1
    r = results[0]
    assert r.checkpoint_id == "WD-DA-PKG-001"
    assert r.category == "Workday DA"
    assert r.status == "Skipped"
    assert "Dataverse URL or access token not available" in r.result


def test_skipped_when_token_missing() -> None:
    results = _check_workday_da_package_installed(
        _MinimalRunner(env_url=BASE_URL, dv_token=None)
    )
    assert results[0].status == "Skipped"


@responses.activate
def test_failed_when_selected_agent_is_unresolved(
    runner: _MinimalRunner,
) -> None:
    _register_solutions(solutions=[])

    results = _check_workday_da_package_installed(runner)
    assert len(results) == 1
    r = results[0]
    assert r.checkpoint_id == "WD-DA-PKG-001"
    assert r.status == "Failed"
    assert "selected agent identity could not be resolved" in r.result
    assert "--agent-slug" in r.remediation


@responses.activate
def test_failed_when_hr_base_agent_present_but_workday_child_missing(
    runner: _MinimalRunner,
) -> None:
    runner.config = {
        "activeAgent": "ess-hr",
        "agents": [{
            "slug": "ess-hr",
            "schemaName": "msdyn_copilotforemployeeselfservicedahr",
        }],
    }
    _register_solutions(solutions=[
        _solution_record("msdyn_copilotforemployeeselfservicedahr"),
    ])

    r = _check_workday_da_package_installed(runner)[0]
    assert r.status == "Failed"
    assert "required by the ESS HR agent" in r.result
    assert "/connect workday" in r.remediation


@responses.activate
def test_native_hr_agent_only_requires_child_in_sidecar(
    runner: _MinimalRunner,
) -> None:
    runner.config = {
        "releaseLine": "da",
        "activeAgent": "ess-hr",
        "agents": [
            {
                "slug": "ess-hr",
                "schemaName": "gptagent_copilotforemployeeselfservicehr",
            }
        ],
    }
    _register_solutions(
        solutions=[
            _solution_record("msdyn_EssWorkdayRuntime", version="2.1.0.0"),
        ]
    )

    result = _check_workday_da_package_installed(runner)[0]
    assert result.status == "Passed"
    assert "msdyn_EssWorkdayRuntime" in result.result


@responses.activate
def test_native_it_active_agent_is_rejected(
    runner: _MinimalRunner,
) -> None:
    runner.config = {
        "releaseLine": "da",
        "activeAgent": "ess-it",
        "agents": [
            {
                "slug": "ess-it",
                "schemaName": "gptagent_copilotforemployeeselfserviceit",
            }
        ],
    }
    _register_solutions(
        solutions=[
            _solution_record("msdyn_copilotforemployeeselfservicedahr"),
            _solution_record("msdyn_EssWorkdayRuntime"),
        ]
    )

    result = _check_workday_da_package_installed(runner)[0]
    assert result.status == "Failed"
    assert "selected agent 'ess-it' is the ESS DA IT agent" in result.result


@responses.activate
def test_failed_when_only_it_base_agent_is_present(
    runner: _MinimalRunner,
) -> None:
    runner.config = {
        "activeAgent": "ess-it",
        "agents": [{
            "slug": "ess-it",
            "schemaName": "msdyn_copilotforemployeeselfservicedait",
        }],
    }
    _register_solutions(solutions=[
        _solution_record("msdyn_copilotforemployeeselfservicedait"),
    ])

    r = _check_workday_da_package_installed(runner)[0]
    assert r.status == "Failed"
    assert "selected agent 'ess-it' is the ESS DA IT agent" in r.result
    assert "not supported" in r.remediation


@responses.activate
def test_passed_when_hr_workday_child_present(runner: _MinimalRunner) -> None:
    runner.config = {
        "activeAgent": "ess-hr",
        "agents": [{
            "slug": "ess-hr",
            "schemaName": "msdyn_copilotforemployeeselfservicedahr",
        }],
    }
    _register_solutions(solutions=[
        _solution_record("msdyn_copilotforemployeeselfservicedahr"),
        _solution_record("msdyn_EssDAHRWorkday", version="2.0.0.1"),
    ])

    r = _check_workday_da_package_installed(runner)[0]
    assert r.status == "Passed"
    assert "msdyn_EssDAHRWorkday" in r.result
    assert "2.0.0.1" in r.result
    # Principle: PASSED carries no remediation.
    assert r.remediation == ""


@responses.activate
def test_it_agent_does_not_block_supported_hr_package(
    runner: _MinimalRunner,
) -> None:
    """An IT agent in the environment is outside the active HR lifecycle."""
    runner.config = {
        "activeAgent": "ess-hr",
        "agents": [{
            "slug": "ess-hr",
            "schemaName": "msdyn_copilotforemployeeselfservicedahr",
        }],
    }
    _register_solutions(solutions=[
        _solution_record("msdyn_copilotforemployeeselfservicedahr"),
        _solution_record("msdyn_copilotforemployeeselfservicedait"),
        _solution_record("msdyn_EssDAHRWorkday"),
    ])

    r = _check_workday_da_package_installed(runner)[0]
    assert r.status == "Passed"
    assert "Selected ESS HR agent 'ess-hr' detected" in r.result
    assert "msdyn_EssDAHRWorkday" in r.result


@responses.activate
def test_explicit_slug_wins_over_different_active_agent(
    runner: _MinimalRunner,
) -> None:
    runner.agent_slug = "selected-hr"
    runner.config = {
        "activeAgent": "active-it",
        "agents": [
            {
                "slug": "active-it",
                "schemaName": "msdyn_copilotforemployeeselfservicedait",
            },
            {
                "slug": "selected-hr",
                "schemaName": "msdyn_copilotforemployeeselfservicedahr",
            },
        ],
    }
    _register_solutions([
        _solution_record("msdyn_EssDAHRWorkday"),
    ])

    result = _check_workday_da_package_installed(runner)[0]

    assert result.status == "Passed"
    assert "selected-hr" in result.result


@pytest.mark.parametrize(
    "agent_slug",
    ("missing", "..", "../ess-hr", r"..\ess-hr", "C:ess-hr"),
)
def test_explicit_slug_must_resolve_to_canonical_agent(
    runner: _MinimalRunner,
    agent_slug: str,
) -> None:
    runner.agent_slug = agent_slug
    runner.config = {
        "activeAgent": "ess-hr",
        "agents": [{
            "slug": "ess-hr",
            "schemaName": "msdyn_copilotforemployeeselfservicedahr",
        }],
    }

    result = _check_workday_da_package_installed(runner)[0]

    assert result.status == "Failed"
    assert "selected agent identity could not be resolved" in result.result


@responses.activate
def test_environment_packages_do_not_substitute_for_selected_identity(
    runner: _MinimalRunner,
) -> None:
    runner.config = {
        "activeAgent": "unrelated",
        "agents": [{
            "slug": "unrelated",
            "schemaName": "contoso_unrelated_agent",
        }],
    }
    _register_solutions([
        _solution_record("msdyn_copilotforemployeeselfservicedahr"),
        _solution_record("msdyn_EssDAHRWorkday"),
    ])

    result = _check_workday_da_package_installed(runner)[0]

    assert result.status == "Failed"
    assert "not a supported ESS DA HR agent" in result.result


@responses.activate
def test_warning_when_dataverse_returns_500(runner: _MinimalRunner) -> None:
    """A transient platform error must surface as WARNING, not silently PASS."""
    _select_classic_hr(runner)
    responses.add(
        "GET",
        dv.build_query_url(
            BASE_URL,
            "solutions",
            select=SOLN_SELECT,
            filter_expr=SOLN_FILTER,
        ),
        json={"error": {"code": "0x80040220", "message": "boom"}},
        status=500,
    )

    r = _check_workday_da_package_installed(runner)[0]
    assert r.status == "Warning"
    assert "Unable to verify the DA Workday package" in r.result


@responses.activate
def test_warning_when_dataverse_returns_401(runner: _MinimalRunner) -> None:
    """A 401 must surface as WARNING with an auth-expired hint.

    Exercises the AuthExpiredError catch block in
    _check_workday_da_package_installed.
    """
    _select_classic_hr(runner)
    responses.add(
        "GET",
        dv.build_query_url(
            BASE_URL,
            "solutions",
            select=SOLN_SELECT,
            filter_expr=SOLN_FILTER,
        ),
        json={"error": {"code": "0x80048306", "message": "token expired"}},
        status=401,
    )

    r = _check_workday_da_package_installed(runner)[0]
    assert r.status == "Warning"
    assert "401" in r.result
    assert "Re-run FlightCheck" in r.remediation
