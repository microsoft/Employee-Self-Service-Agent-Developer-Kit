# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""End-to-end integration tests for the Workday install-flavor detection
FlightCheck checks (WD-PKG-001 and WD-CONN-012).

Mocks the Dataverse `connectionreferences` query with `responses`, then
runs the ACTUAL production check functions from
`solutions/ess-maker-skills/scripts/flightcheck/checks/workday.py`
against the mocked state. Asserts the verdict (`PASSED`/`FAILED`/
`WARNING`/`NOT_CONFIGURED`/`SKIPPED`) and the `runner._workday_package_flavor`
attribute that downstream checks branch on.

These tests follow the pattern documented in
`tests/flightcheck/checks/test_workday_env_vars.py`: stand up a
minimal runner, register the Dataverse mock, invoke the real check
function, and assert on the produced CheckResult list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
import responses

from tests.conftest import require_validated_mock
from tests.mocks import dataverse as dv

require_validated_mock(dv)


# ─────────────────────────────────────────────────────────────────────────
# Minimal runner — WD-PKG-001 and WD-CONN-012 only read env_url, dv_token,
# and the cached _workday_* attributes.
# ─────────────────────────────────────────────────────────────────────────


@dataclass
class _MinimalRunner:
    env_url: str
    dv_token: str
    _workday_flows: list = field(default_factory=list)


@pytest.fixture
def runner(fake_dataverse_url: str, fake_token: str) -> _MinimalRunner:
    return _MinimalRunner(env_url=fake_dataverse_url, dv_token=fake_token)


def _register_connection_refs(*, base_url: str, refs: list[dict[str, Any]]) -> None:
    """Register the Dataverse connectionreferences query the check makes."""
    responses.add(
        method="GET",
        url=f"{base_url}/api/data/v9.2/connectionreferences",
        json=dv.collection(refs),
        status=200,
    )


def _result_by_id(results: list, checkpoint_id: str):
    matches = [r for r in results if r.checkpoint_id == checkpoint_id]
    assert len(matches) == 1, (
        f"Expected exactly one result for {checkpoint_id}, got {len(matches)}: "
        f"{[r.checkpoint_id for r in results]}"
    )
    return matches[0]


def _non_workday_ref() -> dict[str, Any]:
    """Common noise-row used in tests — must be filtered out by the
    connector-id matcher."""
    return dv.connection_ref(
        ref_id="00000000-0000-0000-0000-000000009001",
        logical_name="msdyn_sharedcommondataserviceforapps_92b66",
        display_name="Microsoft Dataverse",
        connector_id="/providers/Microsoft.PowerApps/apis/shared_commondataserviceforapps",
        connection_id="shared-cds-1",
    )


# ─────────────────────────────────────────────────────────────────────────
# WD-PKG-001 — package flavor detection
# ─────────────────────────────────────────────────────────────────────────


class TestPackageFlavorDetection:
    @responses.activate
    def test_simplified_install_passes_with_flavor_simplified(
        self, runner: _MinimalRunner, fake_dataverse_url: str
    ) -> None:
        from flightcheck.checks.workday import _check_package_flavor

        _register_connection_refs(
            base_url=fake_dataverse_url,
            refs=[_non_workday_ref(), *dv.workday_connection_refs_simplified()],
        )

        # Simulate flows being deployed so the result text doesn't add
        # the "no flows" note here — that's its own dedicated test.
        runner._workday_flows = [{"name": "Workday-WhateverFlow"}]
        results = _check_package_flavor(runner, wd_flows=runner._workday_flows)

        r = _result_by_id(results, "WD-PKG-001")
        assert r.status == "Passed"
        assert runner._workday_package_flavor == "simplified"
        assert "simplified-install shape" in r.result
        # Cached refs are the Workday-only subset (1 row).
        assert len(runner._workday_connection_refs) == 1

    @responses.activate
    def test_full_install_passes_with_flavor_full(
        self, runner: _MinimalRunner, fake_dataverse_url: str
    ) -> None:
        from flightcheck.checks.workday import _check_package_flavor

        _register_connection_refs(
            base_url=fake_dataverse_url,
            refs=[_non_workday_ref(), *dv.workday_connection_refs_full()],
        )

        runner._workday_flows = [{"name": "Workday-WhateverFlow"}]
        results = _check_package_flavor(runner, wd_flows=runner._workday_flows)

        r = _result_by_id(results, "WD-PKG-001")
        assert r.status == "Passed"
        assert runner._workday_package_flavor == "full"
        assert "full / legacy" in r.result
        assert len(runner._workday_connection_refs) == 3

    @responses.activate
    def test_no_workday_refs_returns_not_configured_with_flavor_none(
        self, runner: _MinimalRunner, fake_dataverse_url: str
    ) -> None:
        from flightcheck.checks.workday import _check_package_flavor

        _register_connection_refs(base_url=fake_dataverse_url, refs=[_non_workday_ref()])

        results = _check_package_flavor(runner, wd_flows=[])

        r = _result_by_id(results, "WD-PKG-001")
        assert r.status == "NotConfigured"
        assert runner._workday_package_flavor == "none"
        assert runner._workday_connection_refs == []

    @responses.activate
    def test_partial_install_missing_one_isu_returns_failed(
        self, runner: _MinimalRunner, fake_dataverse_url: str
    ) -> None:
        """OBO + one of two ISU refs. Strict subset of LEGACY -> FAIL."""
        from flightcheck.checks.workday import _check_package_flavor

        _register_connection_refs(
            base_url=fake_dataverse_url,
            refs=[
                dv.workday_connection_ref(suffix="ff0df", display_name="OAuthUser"),
                dv.workday_connection_ref(suffix="0786a", display_name="Generic User"),
                # missing _d6081 / Context Generic User
            ],
        )

        results = _check_package_flavor(runner, wd_flows=[])

        r = _result_by_id(results, "WD-PKG-001")
        assert r.status == "Failed"
        assert runner._workday_package_flavor == "partial"
        assert "Context Generic User" in r.result

    @responses.activate
    def test_partial_install_isu_only_no_obo_returns_failed(
        self, runner: _MinimalRunner, fake_dataverse_url: str
    ) -> None:
        """Both ISUs but no OBO. Still a strict subset of LEGACY -> FAIL."""
        from flightcheck.checks.workday import _check_package_flavor

        _register_connection_refs(
            base_url=fake_dataverse_url,
            refs=[
                dv.workday_connection_ref(suffix="0786a", display_name="Generic User"),
                dv.workday_connection_ref(suffix="d6081", display_name="Context Generic User"),
            ],
        )

        results = _check_package_flavor(runner, wd_flows=[])

        r = _result_by_id(results, "WD-PKG-001")
        assert r.status == "Failed"
        assert runner._workday_package_flavor == "partial"
        assert "OAuthUser" in r.result

    @responses.activate
    def test_unknown_suffix_returns_warning(
        self, runner: _MinimalRunner, fake_dataverse_url: str
    ) -> None:
        from flightcheck.checks.workday import _check_package_flavor

        _register_connection_refs(
            base_url=fake_dataverse_url,
            refs=[
                dv.workday_connection_ref(suffix="ff0df", display_name="OAuthUser"),
                dv.workday_connection_ref(suffix="abcde", display_name="Custom Role"),
            ],
        )

        results = _check_package_flavor(runner, wd_flows=[])

        r = _result_by_id(results, "WD-PKG-001")
        assert r.status == "Warning"
        assert runner._workday_package_flavor == "unknown"
        assert "abcde" in r.result

    @responses.activate
    def test_publisher_prefix_change_still_detected(
        self, runner: _MinimalRunner, fake_dataverse_url: str
    ) -> None:
        """A customer-cloned solution under a different publisher prefix
        keeps the same Microsoft-shipped suffix. The check matches on
        suffix only, so it should still classify correctly."""
        from flightcheck.checks.workday import _check_package_flavor

        _register_connection_refs(
            base_url=fake_dataverse_url,
            refs=[
                dv.workday_connection_ref(
                    suffix="ff0df", display_name="OAuthUser", publisher_prefix="acme",
                ),
            ],
        )

        results = _check_package_flavor(runner, wd_flows=[])

        r = _result_by_id(results, "WD-PKG-001")
        assert r.status == "Passed"
        assert runner._workday_package_flavor == "simplified"

    @responses.activate
    def test_connectorid_with_trailing_slash_and_casing_still_matches(
        self, runner: _MinimalRunner, fake_dataverse_url: str
    ) -> None:
        """The connector matcher is case- and trailing-slash-tolerant."""
        from flightcheck.checks.workday import _check_package_flavor

        _register_connection_refs(
            base_url=fake_dataverse_url,
            refs=[
                dv.connection_ref(
                    logical_name="new_sharedworkdaysoap_ff0df",
                    display_name="OAuthUser",
                    connector_id="/PROVIDERS/Microsoft.PowerApps/apis/Shared_WorkdaySOAP/",
                    connection_id="shared-workday-foo",
                ),
            ],
        )

        results = _check_package_flavor(runner, wd_flows=[])

        r = _result_by_id(results, "WD-PKG-001")
        assert r.status == "Passed"
        assert runner._workday_package_flavor == "simplified"

    def test_no_dv_token_returns_skipped(self, fake_dataverse_url: str) -> None:
        from flightcheck.checks.workday import _check_package_flavor

        runner = _MinimalRunner(env_url=fake_dataverse_url, dv_token="")
        results = _check_package_flavor(runner, wd_flows=[])

        r = _result_by_id(results, "WD-PKG-001")
        assert r.status == "Skipped"
        assert runner._workday_package_flavor == "skipped"

    @responses.activate
    def test_simplified_with_no_flows_adds_flow_contradiction_note(
        self, runner: _MinimalRunner, fake_dataverse_url: str
    ) -> None:
        """Refs present but no Workday flows deployed: still PASSED, but
        the operator gets a note that the package is partially deployed."""
        from flightcheck.checks.workday import _check_package_flavor

        _register_connection_refs(
            base_url=fake_dataverse_url,
            refs=dv.workday_connection_refs_simplified(),
        )

        results = _check_package_flavor(runner, wd_flows=[])

        r = _result_by_id(results, "WD-PKG-001")
        assert r.status == "Passed"
        assert runner._workday_package_flavor == "simplified"
        assert "No Workday flows are deployed" in r.result


# ─────────────────────────────────────────────────────────────────────────
# WD-CONN-012 — package connection-reference binding completeness
# ─────────────────────────────────────────────────────────────────────────


class TestPackageConnectionCompleteness:
    def test_simplified_all_bound_passes(self, runner: _MinimalRunner) -> None:
        from flightcheck.checks.workday import _check_package_connection_completeness

        runner._workday_package_flavor = "simplified"
        runner._workday_connection_refs = dv.workday_connection_refs_simplified()

        results = _check_package_connection_completeness(runner)
        r = _result_by_id(results, "WD-CONN-012")

        assert r.status == "Passed"
        assert "OAuthUser" in r.result

    def test_full_all_bound_passes(self, runner: _MinimalRunner) -> None:
        from flightcheck.checks.workday import _check_package_connection_completeness

        runner._workday_package_flavor = "full"
        runner._workday_connection_refs = dv.workday_connection_refs_full()

        results = _check_package_connection_completeness(runner)
        r = _result_by_id(results, "WD-CONN-012")

        assert r.status == "Passed"

    def test_full_with_one_unbound_fails_with_role_in_diagnostic(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.workday import _check_package_connection_completeness

        runner._workday_package_flavor = "full"
        runner._workday_connection_refs = [
            dv.workday_connection_ref(suffix="ff0df", display_name="OAuthUser"),
            # ISU read role has no connection bound.
            dv.workday_connection_ref(
                suffix="0786a", display_name="Generic User", connection_id=None,
            ),
            dv.workday_connection_ref(suffix="d6081", display_name="Context Generic User"),
        ]

        results = _check_package_connection_completeness(runner)
        r = _result_by_id(results, "WD-CONN-012")

        assert r.status == "Failed"
        assert "Generic User (ISU)" in r.result
        assert "unbound" in r.result

    def test_inactive_statuscode_fails_with_statuscode_in_diagnostic(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.workday import _check_package_connection_completeness

        runner._workday_package_flavor = "simplified"
        runner._workday_connection_refs = [
            dv.workday_connection_ref(
                suffix="ff0df", display_name="OAuthUser", statuscode=2,
            ),
        ]

        results = _check_package_connection_completeness(runner)
        r = _result_by_id(results, "WD-CONN-012")

        assert r.status == "Failed"
        assert "statuscode=2" in r.result

    def test_unknown_flavor_skips(self, runner: _MinimalRunner) -> None:
        from flightcheck.checks.workday import _check_package_connection_completeness

        runner._workday_package_flavor = "unknown"
        runner._workday_connection_refs = []

        results = _check_package_connection_completeness(runner)
        r = _result_by_id(results, "WD-CONN-012")

        assert r.status == "Skipped"

    def test_none_flavor_skips(self, runner: _MinimalRunner) -> None:
        from flightcheck.checks.workday import _check_package_connection_completeness

        runner._workday_package_flavor = "none"
        runner._workday_connection_refs = []

        results = _check_package_connection_completeness(runner)
        r = _result_by_id(results, "WD-CONN-012")

        assert r.status == "Skipped"
