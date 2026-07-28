# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""End-to-end tests for ESS-SOLN-001 (ESS base agent solution installed) in
``solutions/ess-maker-skills/scripts/flightcheck/checks/solution.py``.

Mocks the single Dataverse Web API endpoint the check calls (the ``solutions``
table query) with the ``responses`` library, then invokes the real production
helper ``_check_ess_solution_installed`` and asserts on the resulting
``CheckResult``.

Mock backing: Dataverse Web API v9.2 is the ``documented`` tier per
``tests/fixtures/cassettes/INDEX.md`` — no cassette required. The ``solutions``
response shape comes from the MS Learn entity reference:
https://learn.microsoft.com/power-apps/developer/data-platform/reference/entities/solution
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
import responses

from tests.conftest import FAKE_DATAVERSE_URL, require_validated_mock
from tests.mocks import dataverse as dv

require_validated_mock(dv)


# Production module — flightcheck is importable because pyproject.toml puts
# solutions/ess-maker-skills/scripts on pythonpath.
from flightcheck.checks.solution import _check_ess_solution_installed  # noqa: E402


BASE_URL = FAKE_DATAVERSE_URL

# Verbatim from the production check; if these drift, mock-builder URLs will
# stop matching and tests fail loudly with an unregistered-URL error.
ESS_SOLN_SELECT = "solutionid,uniquename,friendlyname,ismanaged,version"
ESS_SOLN_FILTER = "startswith(uniquename,'msdyn_copilotforemployeeselfservice')"

SOLUTION_ID = "11111111-1111-1111-1111-111111111111"


# ───────────────────────────────────────────────────────────────────────
# Minimal runner — mirrors the pattern in test_preferred_solution.py.
# ───────────────────────────────────────────────────────────────────────


@dataclass
class _MinimalRunner:
    env_url: str | None
    dv_token: str | None


@pytest.fixture
def runner(fake_dataverse_url: str, fake_token: str) -> _MinimalRunner:
    return _MinimalRunner(env_url=fake_dataverse_url, dv_token=fake_token)


# ───────────────────────────────────────────────────────────────────────
# Mock payload builders + registration helpers
# ───────────────────────────────────────────────────────────────────────


def _solution_record(
    uniquename: str,
    *,
    version: str = "1.0.0.0",
    ismanaged: bool = True,
) -> dict[str, Any]:
    """One ``solutions`` row matching the production $select.

    Field naming per
    https://learn.microsoft.com/power-apps/developer/data-platform/reference/entities/solution
    """
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
        select=ESS_SOLN_SELECT,
        filter_expr=ESS_SOLN_FILTER,
    ))


# ───────────────────────────────────────────────────────────────────────
# Tests — one per verdict path.
# ───────────────────────────────────────────────────────────────────────


def test_skipped_when_env_url_missing() -> None:
    results = _check_ess_solution_installed(
        _MinimalRunner(env_url=None, dv_token="tok")
    )
    assert len(results) == 1
    r = results[0]
    assert r.checkpoint_id == "ESS-SOLN-001"
    assert r.category == "Solution"
    assert r.status == "Skipped"
    assert "Dataverse URL or access token not available" in r.result


def test_skipped_when_token_missing() -> None:
    results = _check_ess_solution_installed(
        _MinimalRunner(env_url=BASE_URL, dv_token=None)
    )
    assert results[0].status == "Skipped"


@responses.activate
def test_failed_when_no_ess_solution(runner: _MinimalRunner) -> None:
    _register_solutions(solutions=[])

    results = _check_ess_solution_installed(runner)
    assert len(results) == 1
    r = results[0]
    assert r.checkpoint_id == "ESS-SOLN-001"
    assert r.status == "Failed"
    assert "not present" in r.result
    assert "AppSource" in r.remediation


@responses.activate
def test_passed_when_base_solution_present(runner: _MinimalRunner) -> None:
    _register_solutions(solutions=[
        _solution_record("msdyn_copilotforemployeeselfservice", version="1.2.3.4"),
    ])

    results = _check_ess_solution_installed(runner)
    assert len(results) == 1
    r = results[0]
    assert r.checkpoint_id == "ESS-SOLN-001"
    assert r.status == "Passed"
    assert "msdyn_copilotforemployeeselfservice" in r.result
    assert "1.2.3.4" in r.result
    # Principle 8: PASSED carries no remediation.
    assert r.remediation == ""


@responses.activate
def test_passed_when_it_variant_present(runner: _MinimalRunner) -> None:
    _register_solutions(solutions=[
        _solution_record("msdyn_copilotforemployeeselfserviceit"),
    ])

    r = _check_ess_solution_installed(runner)[0]
    assert r.status == "Passed"
    assert "msdyn_copilotforemployeeselfserviceit" in r.result


@responses.activate
def test_passed_when_hr_variant_present(runner: _MinimalRunner) -> None:
    _register_solutions(solutions=[
        _solution_record("msdyn_copilotforemployeeselfservicehr"),
    ])

    r = _check_ess_solution_installed(runner)[0]
    assert r.status == "Passed"
    assert "msdyn_copilotforemployeeselfservicehr" in r.result


@responses.activate
def test_passed_lists_multiple_editions(runner: _MinimalRunner) -> None:
    _register_solutions(solutions=[
        _solution_record("msdyn_copilotforemployeeselfservice"),
        _solution_record("msdyn_copilotforemployeeselfserviceit"),
    ])

    r = _check_ess_solution_installed(runner)[0]
    assert r.status == "Passed"
    assert "msdyn_copilotforemployeeselfservice " in r.result
    assert "msdyn_copilotforemployeeselfserviceit" in r.result


@responses.activate
def test_warning_when_dataverse_returns_500(runner: _MinimalRunner) -> None:
    """A transient platform error must surface as WARNING, not silently PASS."""
    responses.add(
        "GET",
        dv.build_query_url(
            BASE_URL,
            "solutions",
            select=ESS_SOLN_SELECT,
            filter_expr=ESS_SOLN_FILTER,
        ),
        json={"error": {"code": "0x80040220", "message": "boom"}},
        status=500,
    )

    r = _check_ess_solution_installed(runner)[0]
    assert r.status == "Warning"
    assert "Unable to verify the ESS solution" in r.result


@responses.activate
def test_warning_when_dataverse_returns_401(runner: _MinimalRunner) -> None:
    """A 401 must surface as WARNING with an auth-expired hint.

    Exercises the AuthExpiredError catch block in _check_ess_solution_installed.
    """
    responses.add(
        "GET",
        dv.build_query_url(
            BASE_URL,
            "solutions",
            select=ESS_SOLN_SELECT,
            filter_expr=ESS_SOLN_FILTER,
        ),
        json={"error": {"code": "0x80048306", "message": "token expired"}},
        status=401,
    )

    r = _check_ess_solution_installed(runner)[0]
    assert r.status == "Warning"
    assert "401" in r.result
    assert "Re-run FlightCheck" in r.remediation
