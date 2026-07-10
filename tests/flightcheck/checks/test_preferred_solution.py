# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""End-to-end tests for ENV-009 (preferred customization solution check) in
``solutions/ess-maker-skills/scripts/flightcheck/checks/environment.py``.

Mocks the Dataverse Web API endpoints the check calls
(``solutions``, ``GetPreferredSolution()``, ``publishers({id})``) with the
``responses`` library, then invokes the real production helper
``_check_preferred_solution`` and asserts on the resulting ``CheckResult``.

Mock backing: Dataverse Web API v9.2 is the ``documented`` tier per
``tests/fixtures/cassettes/INDEX.md`` line 49. Response shapes come from MS
Learn entity reference / function reference pages:

* solutions entity:
  https://learn.microsoft.com/power-apps/developer/data-platform/reference/entities/solution
* GetPreferredSolution function:
  https://learn.microsoft.com/power-apps/developer/data-platform/webapi/reference/getpreferredsolution
  (response-body shape uncertainty is documented in
  ``tests/mocks/dataverse.py:get_preferred_solution``)
* publisher entity:
  https://learn.microsoft.com/power-apps/developer/data-platform/reference/entities/publisher
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
from flightcheck.checks.environment import _check_preferred_solution  # noqa: E402


BASE_URL = FAKE_DATAVERSE_URL

# Sentinel GUIDs — kept distinct so a mis-routed mock fails loudly.
SOLUTION_ID_ELIGIBLE = "11111111-1111-1111-1111-111111111111"
SOLUTION_ID_OTHER = "22222222-2222-2222-2222-222222222222"
SOLUTION_ID_NOT_IN_LIST = "33333333-3333-3333-3333-333333333333"

# Stable publisher GUIDs — one custom, one default-publisher.
PUBLISHER_ID_CUSTOM = "aaaaaaaa-1111-1111-1111-111111111111"
PUBLISHER_ID_DEFAULT = "bbbbbbbb-2222-2222-2222-222222222222"

# Verbatim from the production check; if these drift, mock-builder URLs will
# stop matching and tests will fail loudly with an unregistered-URL error.
ELIGIBLE_SOLUTION_FILTER = (
    "ismanaged eq false and isvisible eq true "
    "and uniquename ne 'Default' and uniquename ne 'Active' "
    "and solutiontype eq 0 and _parentsolutionid_value eq null"
)
ELIGIBLE_SOLUTION_SELECT = "solutionid,uniquename,friendlyname,_publisherid_value"


# ───────────────────────────────────────────────────────────────────────
# Minimal runner — mirrors the pattern in test_workday_env_vars.py.
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
    solution_id: str,
    uniquename: str,
    *,
    publisher_id: str | None = PUBLISHER_ID_CUSTOM,
) -> dict[str, Any]:
    """One ``solutions`` row matching the production $select.

    Field naming per
    https://learn.microsoft.com/power-apps/developer/data-platform/reference/entities/solution
    Defaults model the eligible row pointing at a custom publisher; pass
    ``publisher_id=PUBLISHER_ID_DEFAULT`` to model a row bound to the
    env's Default Publisher, or ``publisher_id=None`` to model a row
    with no publisher lookup populated.
    """
    return {
        "@odata.etag": 'W/"1"',
        "solutionid": solution_id,
        "uniquename": uniquename,
        "friendlyname": uniquename,
        "_publisherid_value": publisher_id,
    }


def _register_solutions(solutions: list[dict[str, Any]]) -> None:
    responses.add(**dv.query(
        base_url=BASE_URL,
        entity_set="solutions",
        records=solutions,
        select=ELIGIBLE_SOLUTION_SELECT,
        filter_expr=ELIGIBLE_SOLUTION_FILTER,
    ))


def _register_get_preferred_solution(
    selected_solution_id: str | None,
    *,
    uniquename: str | None = None,
) -> None:
    """Mock GetPreferredSolution() returning the given solution id.

    Pass ``selected_solution_id=None`` to mock the "no preferred solution
    selected" case (the body omits ``solutionid``).
    """
    responses.add(**dv.get_preferred_solution(
        base_url=BASE_URL,
        solution_id=selected_solution_id,
        uniquename=uniquename,
    ))


def _register_publisher(
    publisher_id: str = PUBLISHER_ID_CUSTOM,
    *,
    uniquename: str = "ContosoPublisher",
    customizationprefix: str = "contoso",
    status: int = 200,
) -> None:
    """Mock the ``GET /publishers({id})?$select=...`` round-trip the
    production check makes after a preferred-solution match.

    Defaults model a customer-created publisher (the PASS path). Pass
    ``uniquename="DefaultPublisherorg<suffix>"`` with
    ``customizationprefix="cr<NNN>"`` to model the env's auto-provisioned
    Default Publisher (the new WARNING path). Pass ``status=500`` to
    drive the "publisher fetch failed" branch where the check degrades
    gracefully to PASS without the publisher annotation.
    """
    responses.add(**dv.publisher(
        base_url=BASE_URL,
        publisher_id=publisher_id,
        uniquename=uniquename,
        customizationprefix=customizationprefix,
        status=status,
    ))


# ───────────────────────────────────────────────────────────────────────
# Tests — one per verdict path.
# ───────────────────────────────────────────────────────────────────────


def test_skipped_when_env_url_missing() -> None:
    results = _check_preferred_solution(_MinimalRunner(env_url=None, dv_token="tok"))
    assert len(results) == 1
    assert results[0].checkpoint_id == "ENV-009"
    assert results[0].status == "Skipped"
    assert "Dataverse URL or access token not available" in results[0].result


def test_skipped_when_token_missing() -> None:
    results = _check_preferred_solution(_MinimalRunner(env_url=BASE_URL, dv_token=None))
    assert results[0].status == "Skipped"


@responses.activate
def test_failed_when_no_eligible_solution(runner: _MinimalRunner) -> None:
    _register_solutions(solutions=[])

    results = _check_preferred_solution(runner)
    assert len(results) == 1
    r = results[0]
    assert r.checkpoint_id == "ENV-009"
    assert r.status == "Failed"
    assert "No customer-created unmanaged solutions" in r.result
    assert "Default Solution" in r.result
    assert "Create an unmanaged solution" in r.remediation


@responses.activate
def test_warning_when_selected_solution_not_in_eligible_set(
    runner: _MinimalRunner,
) -> None:
    _register_solutions(solutions=[
        _solution_record(SOLUTION_ID_ELIGIBLE, "ESSCustomization"),
    ])
    _register_get_preferred_solution(selected_solution_id=SOLUTION_ID_NOT_IN_LIST)

    results = _check_preferred_solution(runner)
    assert len(results) == 1
    r = results[0]
    assert r.checkpoint_id == "ENV-009"
    assert r.status == "Warning"
    # Principle 8: result describes observed state only; framing lives in remediation.
    assert "Hardening recommendation" not in r.result
    assert "has not selected" in r.result
    assert "ESSCustomization" in r.result
    # Principle 9: hardening WARNING remediation opens with the framing prefix
    # and includes a concrete reason BEFORE the click-path.
    assert r.remediation.startswith("Hardening recommendation (not a functional blocker)")
    assert "Default Solution" in r.remediation
    assert "Set preferred solution" in r.remediation


@responses.activate
def test_warning_when_no_preferred_solution_selected(runner: _MinimalRunner) -> None:
    _register_solutions(solutions=[
        _solution_record(SOLUTION_ID_ELIGIBLE, "ESSCustomization"),
        _solution_record(SOLUTION_ID_OTHER, "ContosoExtensions"),
    ])
    _register_get_preferred_solution(selected_solution_id=None)

    r = _check_preferred_solution(runner)[0]
    assert r.status == "Warning"
    assert "2 eligible unmanaged solution" in r.result
    # Both candidates listed (alphabetical).
    assert "ContosoExtensions" in r.result
    assert "ESSCustomization" in r.result


@responses.activate
def test_passed_when_selected_solution_matches(runner: _MinimalRunner) -> None:
    _register_solutions(solutions=[
        _solution_record(SOLUTION_ID_ELIGIBLE, "ESSCustomization"),
    ])
    _register_get_preferred_solution(selected_solution_id=SOLUTION_ID_ELIGIBLE)
    _register_publisher()

    results = _check_preferred_solution(runner)
    assert len(results) == 1
    r = results[0]
    assert r.checkpoint_id == "ENV-009"
    assert r.status == "Passed"
    assert "ESSCustomization" in r.result
    assert "selected" in r.result
    # Custom publisher annotation surfaces on the PASS path for parity
    # with the WARNING path (operator can confirm the binding at a glance).
    assert "ContosoPublisher" in r.result
    assert "contoso" in r.result
    # PASSED remediation describes what was validated.
    assert r.remediation.startswith("Validated:")
    assert "preferred" in r.remediation


@responses.activate
def test_passed_when_selected_matches_one_of_many(runner: _MinimalRunner) -> None:
    _register_solutions(solutions=[
        _solution_record(SOLUTION_ID_ELIGIBLE, "ESSCustomization"),
        _solution_record(SOLUTION_ID_OTHER, "ContosoExtensions"),
    ])
    _register_get_preferred_solution(selected_solution_id=SOLUTION_ID_OTHER)
    _register_publisher()

    r = _check_preferred_solution(runner)[0]
    assert r.status == "Passed"
    assert "'ContosoExtensions'" in r.result
    assert "2 eligible unmanaged solution" in r.result
    assert "ContosoPublisher" in r.result


@responses.activate
def test_passed_when_guid_casing_differs_between_endpoints(
    runner: _MinimalRunner,
) -> None:
    """GUID equality must be case-insensitive across the two endpoints.

    Dataverse normally returns lowercase GUIDs in JSON, but the comparison
    in production code must not break if the two endpoints ever serialise
    GUIDs in different cases. The eligible-set query returns the GUID in
    lowercase here; GetPreferredSolution() returns the same logical GUID
    in uppercase. The check must still PASS.
    """
    _register_solutions(solutions=[
        _solution_record(SOLUTION_ID_ELIGIBLE.lower(), "ESSCustomization"),
    ])
    _register_get_preferred_solution(
        selected_solution_id=SOLUTION_ID_ELIGIBLE.upper(),
    )
    _register_publisher()

    r = _check_preferred_solution(runner)[0]
    assert r.status == "Passed"
    assert "'ESSCustomization'" in r.result


@responses.activate
def test_warning_when_dataverse_returns_500(runner: _MinimalRunner) -> None:
    """A transient platform error must surface as WARNING, not silently PASS.

    The status-code surfacing path (PR #128 review) is exercised by the
    403 test below; on 5xx the requests/urllib3 retry layer swallows the
    response object and raises a RetryError with no ``.response``, so
    surfacing the code on 5xx isn't reliably possible from this layer.
    """
    responses.add(
        "GET",
        dv.build_query_url(
            BASE_URL,
            "solutions",
            select=ELIGIBLE_SOLUTION_SELECT,
            filter_expr=ELIGIBLE_SOLUTION_FILTER,
        ),
        json={"error": {"code": "0x80040220", "message": "boom"}},
        status=500,
    )

    r = _check_preferred_solution(runner)[0]
    assert r.status == "Warning"
    assert "Unable to validate preferred solution" in r.result


@responses.activate
def test_warning_when_one_solution_and_no_preference(runner: _MinimalRunner) -> None:
    """Exactly 1 eligible solution exists but maker hasn't selected one.

    Distinct from the many-solutions case (covered by
    test_warning_when_no_preferred_solution_selected) - validates the result
    message handles the singular case correctly.
    """
    _register_solutions(solutions=[
        _solution_record(SOLUTION_ID_ELIGIBLE, "ESSCustomization"),
    ])
    _register_get_preferred_solution(selected_solution_id=None)

    r = _check_preferred_solution(runner)[0]
    assert r.status == "Warning"
    assert "1 eligible unmanaged solution" in r.result
    assert "ESSCustomization" in r.result
    assert "Set preferred solution" in r.remediation


@responses.activate
def test_warning_when_dataverse_returns_401(runner: _MinimalRunner) -> None:
    """A 401 from Dataverse must surface as WARNING with an auth-expired hint.

    Exercises the AuthExpiredError catch block in _check_preferred_solution.
    Without this test, the catch path is unreachable from the test suite.
    """
    responses.add(
        "GET",
        dv.build_query_url(
            BASE_URL,
            "solutions",
            select=ELIGIBLE_SOLUTION_SELECT,
            filter_expr=ELIGIBLE_SOLUTION_FILTER,
        ),
        json={"error": {"code": "0x80048306", "message": "token expired"}},
        status=401,
    )

    r = _check_preferred_solution(runner)[0]
    assert r.status == "Warning"
    # AuthExpiredError message contains "401" and "token expired or invalid".
    assert "401" in r.result
    assert "Re-run FlightCheck" in r.remediation


@responses.activate
def test_warning_when_get_preferred_solution_returns_403(
    runner: _MinimalRunner,
) -> None:
    """A 403 on GetPreferredSolution() must surface the status code.

    Insufficient privilege on the system tables surfaces as HTTP 403. The
    catch-all WARNING must expose the status code so the failure mode is
    distinguishable from a transient 5xx (PR #128 review).
    """
    _register_solutions(solutions=[
        _solution_record(SOLUTION_ID_ELIGIBLE, "ESSCustomization"),
    ])
    responses.add(
        "GET",
        f"{BASE_URL}/api/data/v9.2/GetPreferredSolution()",
        json={"error": {"code": "0x80040220", "message": "Principal user is missing privilege"}},
        status=403,
    )

    r = _check_preferred_solution(runner)[0]
    assert r.status == "Warning"
    assert "Unable to validate preferred solution" in r.result
    assert "[HTTP 403]" in r.result
    assert "privileges" in r.remediation


# ───────────────────────────────────────────────────────────────────────
# Publisher-quality branch (PR #128 follow-up — preferred solution is
# correctly selected but is bound to the env's Default Publisher).
# ───────────────────────────────────────────────────────────────────────


@responses.activate
def test_warning_when_preferred_solution_uses_default_publisher(
    runner: _MinimalRunner,
) -> None:
    """E2E gap: preferred solution is unmanaged + selected, but is bound to
    the env's auto-provisioned Default Publisher (uniquename starts with
    ``DefaultPublisher`` and inherits the env's ``cr<NNN>`` prefix).

    The functional selection is correct, so this is a hardening WARNING
    (not a FAIL). The result must describe the observed state only; the
    remediation must open with the hardening-recommendation prefix and
    give a concrete reason before the click-path (AGENTS.md principle 9).
    """
    _register_solutions(solutions=[
        _solution_record(
            SOLUTION_ID_ELIGIBLE, "ESSCustomization",
            publisher_id=PUBLISHER_ID_DEFAULT,
        ),
    ])
    _register_get_preferred_solution(selected_solution_id=SOLUTION_ID_ELIGIBLE)
    # A real Default Publisher value observed in
    # tests/fixtures/cassettes/island_gateway_botcomponents.yaml.
    _register_publisher(
        publisher_id=PUBLISHER_ID_DEFAULT,
        uniquename="DefaultPublisherorgeeac24d0",
        customizationprefix="cr123",
    )

    r = _check_preferred_solution(runner)[0]
    assert r.checkpoint_id == "ENV-009"
    assert r.status == "Warning"
    # Principle 8: result is observed state, no framing.
    assert "Hardening recommendation" not in r.result
    assert "ESSCustomization" in r.result
    assert "Default Publisher" in r.result
    assert "DefaultPublisherorgeeac24d0" in r.result
    assert "cr123" in r.result
    # Principle 9: framing + concrete reason BEFORE the click-path.
    assert r.remediation.startswith("Hardening recommendation (not a functional blocker)")
    assert "cr123" in r.remediation
    assert "collide across environments" in r.remediation
    assert "+ New publisher" in r.remediation


@responses.activate
def test_passed_when_publisher_fetch_fails_degrades_gracefully(
    runner: _MinimalRunner,
) -> None:
    """If the /publishers({id}) round-trip fails, don't downgrade the verdict.

    The preferred-solution selection itself is correct; a transient
    failure on the publisher lookup should not flip PASS to WARNING. The
    publisher annotation is simply omitted from the result.
    """
    _register_solutions(solutions=[
        _solution_record(SOLUTION_ID_ELIGIBLE, "ESSCustomization"),
    ])
    _register_get_preferred_solution(selected_solution_id=SOLUTION_ID_ELIGIBLE)
    _register_publisher(status=500)

    r = _check_preferred_solution(runner)[0]
    assert r.status == "Passed"
    assert "ESSCustomization" in r.result
    # No publisher annotation when the fetch failed.
    assert "publisher:" not in r.result
    assert r.remediation.startswith("Validated:")


@responses.activate
def test_passed_when_solution_has_no_publisher_lookup(
    runner: _MinimalRunner,
) -> None:
    """Defensive: if ``_publisherid_value`` is null on the matched solution,
    skip the publisher round-trip and PASS without the annotation.

    Real solutions always have a publisher, but the production code
    treats a missing lookup as "skip the secondary check" rather than
    asserting - this test pins that behaviour.
    """
    _register_solutions(solutions=[
        _solution_record(
            SOLUTION_ID_ELIGIBLE, "ESSCustomization", publisher_id=None,
        ),
    ])
    _register_get_preferred_solution(selected_solution_id=SOLUTION_ID_ELIGIBLE)
    # No publisher mock registered — if production tries to fetch, the
    # responses library will raise ConnectionError and the test fails.

    r = _check_preferred_solution(runner)[0]
    assert r.status == "Passed"
    assert "ESSCustomization" in r.result
    assert "publisher:" not in r.result
