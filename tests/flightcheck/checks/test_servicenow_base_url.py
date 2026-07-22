# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""End-to-end integration tests for the ServiceNow portal base URL
FlightCheck checks (SN-URL-001 HRSD, SN-URL-002 ITSM).

Mocks the Dataverse environmentvariabledefinitions and
environmentvariablevalues queries with `responses`, then runs the
ACTUAL production check function from
solutions/ess-maker-skills/scripts/flightcheck/checks/servicenow.py
against the mocked state.

Background: each ServiceNow extension pack (HRSD, ITSM) carries its own
update-safe Dataverse environment variable
(msdyn_ServiceNow{HRSD,ITSM}PortalBaseURI) that supersedes the
template-config base URI (which ships empty and is reset on every package
update — root cause of ICM 820635151). The check asserts each value is
present and a well-formed absolute URL.
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
# Minimal runner stand-in — the check only needs .env_url and .dv_token.
# ───────────────────────────────────────────────────────────────────────


@dataclass
class _MinimalRunner:
    env_url: str
    dv_token: str


@pytest.fixture
def runner(fake_dataverse_url: str, fake_token: str) -> _MinimalRunner:
    return _MinimalRunner(env_url=fake_dataverse_url, dv_token=fake_token)


# ───────────────────────────────────────────────────────────────────────
# Mock state helpers
# ───────────────────────────────────────────────────────────────────────

_DEF_HRSD = "00000000-0000-0000-0000-0000000060a1"
_DEF_ITSM = "00000000-0000-0000-0000-0000000060a2"

_SCHEMA_HRSD = "msdyn_ServiceNowHRSDPortalBaseURI"
_SCHEMA_ITSM = "msdyn_ServiceNowITSMPortalBaseURI"

_BOTH_DEFINITIONS = [
    dv.env_var_def(
        definition_id=_DEF_HRSD,
        schema_name=_SCHEMA_HRSD,
        display_name="ServiceNow HRSD Portal Base URI",
    ),
    dv.env_var_def(
        definition_id=_DEF_ITSM,
        schema_name=_SCHEMA_ITSM,
        display_name="ServiceNow ITSM Portal Base URI",
    ),
]


def _register_dataverse_state(
    *,
    base_url: str,
    definitions: list[dict[str, Any]],
    values: list[dict[str, Any]],
) -> None:
    """Register the two paginated Dataverse queries the check makes.

    No match_querystring, so the mocks match regardless of the exact
    $select/$filter the production code builds.
    """
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
    """Both base URL env vars set to well-formed URLs — both PASS."""

    @responses.activate
    def test_both_base_urls_set_returns_two_passes(
        self, runner: _MinimalRunner, fake_dataverse_url: str
    ) -> None:
        from flightcheck.checks.servicenow import _check_base_url

        _register_dataverse_state(
            base_url=fake_dataverse_url,
            definitions=_BOTH_DEFINITIONS,
            values=[
                dv.env_var_value(
                    definition_id=_DEF_HRSD,
                    schema_name=_SCHEMA_HRSD,
                    value="https://contoso.service-now.com/sp",
                ),
                dv.env_var_value(
                    definition_id=_DEF_ITSM,
                    schema_name=_SCHEMA_ITSM,
                    value="https://contoso.service-now.com/esc",
                ),
            ],
        )

        results = _check_base_url(runner)

        hrsd = _result_by_id(results, "SN-URL-001")
        itsm = _result_by_id(results, "SN-URL-002")

        assert hrsd.status == "Passed"
        assert "https://contoso.service-now.com/sp" in hrsd.result
        assert not hrsd.remediation

        assert itsm.status == "Passed"
        assert "https://contoso.service-now.com/esc" in itsm.result


class TestMissingValue:
    """Definitions exist but values are empty — the ICM 820635151 case."""

    @responses.activate
    def test_missing_values_fail_with_remediation(
        self, runner: _MinimalRunner, fake_dataverse_url: str
    ) -> None:
        from flightcheck.checks.servicenow import _check_base_url

        _register_dataverse_state(
            base_url=fake_dataverse_url,
            definitions=_BOTH_DEFINITIONS,
            values=[],
        )

        results = _check_base_url(runner)

        for cid in ("SN-URL-001", "SN-URL-002"):
            res = _result_by_id(results, cid)
            assert res.status == "Failed"
            assert "no value set" in res.result
            assert "hyperlinks will not render" in res.remediation.lower()
            assert "Power Platform admin center" in res.remediation

    @responses.activate
    def test_one_pack_set_other_missing_is_independent(
        self, runner: _MinimalRunner, fake_dataverse_url: str
    ) -> None:
        from flightcheck.checks.servicenow import _check_base_url

        _register_dataverse_state(
            base_url=fake_dataverse_url,
            definitions=_BOTH_DEFINITIONS,
            values=[
                dv.env_var_value(
                    definition_id=_DEF_HRSD,
                    schema_name=_SCHEMA_HRSD,
                    value="https://contoso.service-now.com/sp",
                ),
            ],
        )

        results = _check_base_url(runner)

        assert _result_by_id(results, "SN-URL-001").status == "Passed"
        assert _result_by_id(results, "SN-URL-002").status == "Failed"


class TestMalformedValue:
    """A value that is not an absolute URL — WARNING, not silent pass."""

    @responses.activate
    def test_malformed_url_warns(
        self, runner: _MinimalRunner, fake_dataverse_url: str
    ) -> None:
        from flightcheck.checks.servicenow import _check_base_url

        _register_dataverse_state(
            base_url=fake_dataverse_url,
            definitions=_BOTH_DEFINITIONS,
            values=[
                dv.env_var_value(
                    definition_id=_DEF_HRSD,
                    schema_name=_SCHEMA_HRSD,
                    value="contoso.service-now.com",  # no scheme
                ),
                dv.env_var_value(
                    definition_id=_DEF_ITSM,
                    schema_name=_SCHEMA_ITSM,
                    value="https://contoso.service-now.com/esc",
                ),
            ],
        )

        results = _check_base_url(runner)

        hrsd = _result_by_id(results, "SN-URL-001")
        assert hrsd.status == "Warning"
        assert "contoso.service-now.com" in hrsd.result
        assert "valid absolute URL" in hrsd.remediation

        assert _result_by_id(results, "SN-URL-002").status == "Passed"


class TestDefinitionAbsent:
    """No matching env var definitions — pack not installed."""

    @responses.activate
    def test_no_definitions_not_configured(
        self, runner: _MinimalRunner, fake_dataverse_url: str
    ) -> None:
        from flightcheck.checks.servicenow import _check_base_url

        _register_dataverse_state(
            base_url=fake_dataverse_url,
            definitions=[],
            values=[],
        )

        results = _check_base_url(runner)

        for cid in ("SN-URL-001", "SN-URL-002"):
            res = _result_by_id(results, cid)
            assert res.status == "NotConfigured"
            assert "not found" in res.result.lower()
            assert "extension pack" in res.remediation


class TestSkip:
    """No Dataverse token — both checks skip rather than error."""

    def test_no_token_skips(self) -> None:
        from flightcheck.checks.servicenow import _check_base_url

        runner = _MinimalRunner(env_url="", dv_token="")
        results = _check_base_url(runner)

        assert len(results) == 2
        for res in results:
            assert res.status == "Skipped"
            assert "token not available" in res.result.lower()
