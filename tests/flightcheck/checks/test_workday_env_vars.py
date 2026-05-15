# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""End-to-end integration tests for the Workday environment variable
FlightCheck checks (WD-ENV-001, WD-ENV-002, WD-ENV-003).

Mocks the Dataverse environmentvariabledefinitions and
environmentvariablevalues queries with `responses`, then runs the
ACTUAL production check function from
solutions/ess-maker-skills/scripts/flightcheck/checks/workday.py
against the mocked state. Asserts that:

* When the Dataverse mock returns a "good" config (all three env vars
  present, ISU account set), FlightCheck reports PASSED.

* When the Dataverse mock returns a "bad" config (critical ISU
  account missing), FlightCheck reports FAILED with the expected
  remediation pointing the operator at /connect workday.

* When the Dataverse mock returns a partial config (ISU account set
  but the optional report-name vars missing), FlightCheck reports
  PASSED with the documented defaults.

This is the test pattern the rest of the FlightCheck suite should
follow: assemble a runner with whatever inputs the check needs,
register Dataverse / Graph / PP Admin / Workday SOAP / ServiceNow
mocks for the desired tenant state, invoke the real production
check, and assert on the CheckResult list it produces.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
import responses

from tests.conftest import require_validated_mock
from tests.mocks import dataverse as dv

require_validated_mock(dv)


# ───────────────────────────────────────────────────────────────────────
# Test runner — minimal stand-in for FlightCheckRunner that the workday
# check needs. We don't import the real FlightCheckRunner because it
# does too much (registers checks, manages output formatters, etc.) for
# what these tests need; we just need an object with .env_url and
# .dv_token fields.
# ───────────────────────────────────────────────────────────────────────


@dataclass
class _MinimalRunner:
    env_url: str
    dv_token: str


@pytest.fixture
def runner(fake_dataverse_url: str, fake_token: str) -> _MinimalRunner:
    return _MinimalRunner(env_url=fake_dataverse_url, dv_token=fake_token)


# ───────────────────────────────────────────────────────────────────────
# Helpers to register Dataverse mock responses for various tenant states
# ───────────────────────────────────────────────────────────────────────


def _ess_env_var_def(schema_name: str, definition_id: str) -> dict[str, Any]:
    """Build an environmentvariabledefinitions record matching the
    select fields the check requests."""
    return {
        "@odata.etag": 'W/"1"',
        "displayname": schema_name.replace("EmployeeContext", ""),
        "schemaname": f"new_{schema_name}",
        "environmentvariabledefinitionid": definition_id,
    }


def _ess_env_var_value(definition_id: str, schema_name: str, value: str) -> dict[str, Any]:
    """Build an environmentvariablevalues record matching the
    select fields the check requests."""
    return {
        "@odata.etag": 'W/"1"',
        "value": value,
        "schemaname": f"new_{schema_name}_value",
        "_environmentvariabledefinitionid_value": definition_id,
    }


# Stable definition IDs so values can refer to them by FK.
_DEF_ISU = "00000000-0000-0000-0000-000000006001"
_DEF_REPORT_NAME = "00000000-0000-0000-0000-000000006002"
_DEF_REPORT_INSTANCE = "00000000-0000-0000-0000-000000006003"

_ALL_THREE_DEFINITIONS = [
    _ess_env_var_def("EmployeeContextRequestAccountName", _DEF_ISU),
    _ess_env_var_def("EmployeeContextRequestReportName", _DEF_REPORT_NAME),
    _ess_env_var_def("EmployeeContextRequestReportInstanceName", _DEF_REPORT_INSTANCE),
]


def _register_dataverse_state(
    *,
    base_url: str,
    definitions: list[dict[str, Any]],
    values: list[dict[str, Any]],
) -> None:
    """Register the two paginated Dataverse queries the check makes."""
    # The check calls query_all with a $filter for definitions and no
    # filter for values. We don't use match_querystring so the responses
    # match regardless of the exact query string the production code builds.
    responses.add(
        method="GET",
        url=f"{base_url}/api/data/v9.2/environmentvariabledefinitions",
        json=dv.collection(definitions),
        status=200,
    )
    responses.add(
        method="GET",
        url=f"{base_url}/api/data/v9.2/environmentvariablevalues",
        json=dv.collection(values),
        status=200,
    )


def _result_by_id(results: list, checkpoint_id: str):
    """Lookup helper: find the CheckResult with a given checkpoint_id."""
    matches = [r for r in results if r.checkpoint_id == checkpoint_id]
    assert len(matches) == 1, (
        f"Expected exactly one result for {checkpoint_id}, got {len(matches)}: "
        f"{[r.checkpoint_id for r in results]}"
    )
    return matches[0]


# ───────────────────────────────────────────────────────────────────────
# Tests
# ───────────────────────────────────────────────────────────────────────


class TestGoodConfig:
    """All three env vars set — every checkpoint should PASS."""

    @responses.activate
    def test_all_three_env_vars_set_returns_three_passes(
        self, runner: _MinimalRunner, fake_dataverse_url: str
    ) -> None:
        from flightcheck.checks.workday import _check_env_vars

        _register_dataverse_state(
            base_url=fake_dataverse_url,
            definitions=_ALL_THREE_DEFINITIONS,
            values=[
                _ess_env_var_value(_DEF_ISU, "EmployeeContextRequestAccountName", "ISU_MOCK"),
                _ess_env_var_value(_DEF_REPORT_NAME, "EmployeeContextRequestReportName", "WD User Context"),
                _ess_env_var_value(_DEF_REPORT_INSTANCE, "EmployeeContextRequestReportInstanceName", "Report2"),
            ],
        )

        results = _check_env_vars(runner)

        wd_001 = _result_by_id(results, "WD-ENV-001")
        wd_002 = _result_by_id(results, "WD-ENV-002")
        wd_003 = _result_by_id(results, "WD-ENV-003")

        assert wd_001.status == "Passed"
        assert wd_001.priority == "Critical"
        assert "ISU_MOCK" in wd_001.result

        assert wd_002.status == "Passed"
        assert "WD User Context" in wd_002.result

        assert wd_003.status == "Passed"
        assert "Report2" in wd_003.result

    @responses.activate
    def test_critical_var_set_optional_vars_missing_passes_with_defaults(
        self, runner: _MinimalRunner, fake_dataverse_url: str
    ) -> None:
        """Customer set the critical ISU account but didn't override the
        report name defaults. The optional checkpoints should PASS with
        the documented defaults rather than warn."""
        from flightcheck.checks.workday import _check_env_vars

        _register_dataverse_state(
            base_url=fake_dataverse_url,
            definitions=_ALL_THREE_DEFINITIONS,
            values=[
                _ess_env_var_value(_DEF_ISU, "EmployeeContextRequestAccountName", "ISU_MOCK"),
                # Report name and instance NOT in val_map (no value records).
            ],
        )

        results = _check_env_vars(runner)

        wd_001 = _result_by_id(results, "WD-ENV-001")
        wd_002 = _result_by_id(results, "WD-ENV-002")
        wd_003 = _result_by_id(results, "WD-ENV-003")

        assert wd_001.status == "Passed"
        assert "ISU_MOCK" in wd_001.result

        assert wd_002.status == "Passed"
        assert "Using default" in wd_002.result
        assert "WD User Context" in wd_002.result  # documented default

        assert wd_003.status == "Passed"
        assert "Using default" in wd_003.result
        assert "Report2" in wd_003.result


class TestBadConfig:
    """Critical ISU account missing — WD-ENV-001 must FAIL with remediation."""

    @responses.activate
    def test_isu_account_missing_returns_critical_failure(
        self, runner: _MinimalRunner, fake_dataverse_url: str
    ) -> None:
        from flightcheck.checks.workday import _check_env_vars

        # Definitions exist (extension pack is installed) but the
        # customer hasn't set any values yet.
        _register_dataverse_state(
            base_url=fake_dataverse_url,
            definitions=_ALL_THREE_DEFINITIONS,
            values=[],
        )

        results = _check_env_vars(runner)
        wd_001 = _result_by_id(results, "WD-ENV-001")

        assert wd_001.status == "Failed", (
            f"Expected WD-ENV-001 to FAIL when ISU account is unset, got "
            f"status={wd_001.status} result={wd_001.result!r}"
        )
        assert wd_001.priority == "Critical"
        assert "must be set manually" in wd_001.result
        assert "/connect workday" in wd_001.remediation
        assert wd_001.doc_link.startswith(
            "https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service"
        )

    @responses.activate
    def test_isu_account_missing_does_not_block_optional_checkpoint_passes(
        self, runner: _MinimalRunner, fake_dataverse_url: str
    ) -> None:
        """Even when the critical checkpoint fails, the two optional
        checkpoints should still PASS with their defaults — the failure
        is per-checkpoint, not all-or-nothing."""
        from flightcheck.checks.workday import _check_env_vars

        _register_dataverse_state(
            base_url=fake_dataverse_url,
            definitions=_ALL_THREE_DEFINITIONS,
            values=[],
        )

        results = _check_env_vars(runner)

        assert _result_by_id(results, "WD-ENV-001").status == "Failed"
        assert _result_by_id(results, "WD-ENV-002").status == "Passed"
        assert _result_by_id(results, "WD-ENV-003").status == "Passed"


class TestEdgeCases:
    @responses.activate
    def test_definitions_table_empty_treats_critical_as_failed(
        self, runner: _MinimalRunner, fake_dataverse_url: str
    ) -> None:
        """Extension pack not installed → no definitions → critical FAILS,
        optional checkpoints still PASS with defaults.

        This pins current behavior. Whether that's the right outcome is
        a product question (a missing extension pack is different from
        a configured-but-unset env var); update this test if the check
        is ever reworked to differentiate.
        """
        from flightcheck.checks.workday import _check_env_vars

        _register_dataverse_state(
            base_url=fake_dataverse_url,
            definitions=[],
            values=[],
        )

        results = _check_env_vars(runner)

        assert _result_by_id(results, "WD-ENV-001").status == "Failed"
        assert _result_by_id(results, "WD-ENV-002").status == "Passed"
        assert _result_by_id(results, "WD-ENV-003").status == "Passed"

    def test_skips_when_no_dataverse_token(self) -> None:
        """No token (e.g. user opted out of auth) — check returns a single
        SKIPPED result, doesn't crash, doesn't try to make an HTTP call."""
        from flightcheck.checks.workday import _check_env_vars

        runner_no_token = _MinimalRunner(env_url="", dv_token="")

        results = _check_env_vars(runner_no_token)
        assert len(results) == 1
        assert results[0].checkpoint_id == "WD-ENV-001"
        assert results[0].status == "Skipped"
        assert "token not available" in results[0].result.lower()

    @responses.activate
    def test_partial_match_on_schema_name_works(
        self, runner: _MinimalRunner, fake_dataverse_url: str
    ) -> None:
        """The check's schema-name match is case-insensitive substring,
        so 'new_EmployeeContextRequestAccountName_value' matches
        'EmployeeContextRequestAccountName' from ENV_VARS. Pin this
        behavior — if anyone tightens the match to exact-equality,
        this test catches the regression.
        """
        from flightcheck.checks.workday import _check_env_vars

        # The publisher prefixes Dataverse adds usually look like
        # "new_" or "msdyn_"; the check's `var_name.lower() in k.lower()`
        # match is what survives that.
        _register_dataverse_state(
            base_url=fake_dataverse_url,
            definitions=_ALL_THREE_DEFINITIONS,
            values=[
                _ess_env_var_value(_DEF_ISU, "EmployeeContextRequestAccountName", "ISU_MOCK"),
            ],
        )

        results = _check_env_vars(runner)
        assert _result_by_id(results, "WD-ENV-001").status == "Passed"
        assert "ISU_MOCK" in _result_by_id(results, "WD-ENV-001").result
