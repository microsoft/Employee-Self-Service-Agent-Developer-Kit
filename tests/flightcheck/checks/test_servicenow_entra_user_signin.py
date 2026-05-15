# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""End-to-end integration tests for the ServiceNow "Microsoft Entra User
Sign In" FlightCheck check (SN-002).

Mocks the Power Platform Admin (PowerApps) connections endpoint with
`responses`, runs the production check function from
solutions/ess-maker-skills/scripts/flightcheck/checks/external_systems.py
against the mocked state, and asserts on the resulting CheckResult list.

Same pattern as test_workday_connections.py.

The shape of the entraIDUserLogin connection records (Connected and
Errored) is sourced verbatim from
tests/fixtures/cassettes/flightcheck_pp_admin.yaml lines 2640 and 2658
respectively — the mock builders in tests/mocks/pp_admin.py cite those
line numbers in their docstrings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
import responses

from tests.conftest import require_validated_mock
from tests.mocks import pp_admin as pp

require_validated_mock(pp)


@dataclass
class _MinimalRunner:
    pp_admin: Any
    env_id: str


@pytest.fixture
def pp_client(fake_token: str):
    """A real PPAdminClient with a pre-populated token."""
    from flightcheck.pp_admin_client import PPAdminClient

    client = PPAdminClient(tenant_id="00000000-0000-0000-0000-000000001111")
    client._token = fake_token
    return client


@pytest.fixture
def runner(pp_client) -> _MinimalRunner:
    return _MinimalRunner(pp_admin=pp_client, env_id=pp.MOCK_ENV_ID)


def _result_by_id(results: list, checkpoint_id: str):
    matches = [r for r in results if r.checkpoint_id == checkpoint_id]
    assert len(matches) == 1, (
        f"Expected exactly one result for {checkpoint_id}, got {len(matches)}: "
        f"{[r.checkpoint_id for r in results]}"
    )
    return matches[0]


# ───────────────────────────────────────────────────────────────────────


class TestGoodConfig:
    @responses.activate
    def test_single_connected_eusi_servicenow_passes(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.external_systems import (
            _check_sn_entra_user_signin_connections,
        )

        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.servicenow_entra_user_signin_connection(status="Connected"),
            ],
        ))

        results = _check_sn_entra_user_signin_connections(runner)

        sn_002 = _result_by_id(results, "SN-002")
        assert sn_002.status == "Passed"
        assert sn_002.priority == "High"
        assert sn_002.category == "External Systems"
        assert "1 ServiceNow connection" in sn_002.result
        assert "Microsoft Entra User Sign In" in sn_002.result
        assert "all Connected" in sn_002.result

    @responses.activate
    def test_multiple_connected_eusi_servicenow_pass(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.external_systems import (
            _check_sn_entra_user_signin_connections,
        )

        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.servicenow_entra_user_signin_connection(
                    name="conn-eusi-a", display_name="ServiceNow Prod (EUSI)",
                    status="Connected",
                ),
                pp.servicenow_entra_user_signin_connection(
                    name="conn-eusi-b", display_name="ServiceNow Stage (EUSI)",
                    status="Connected",
                ),
            ],
        ))

        results = _check_sn_entra_user_signin_connections(runner)

        sn_002 = _result_by_id(results, "SN-002")
        assert sn_002.status == "Passed"
        assert "2 ServiceNow connection" in sn_002.result


class TestBadConfig:
    @responses.activate
    def test_single_errored_eusi_servicenow_fails_with_federated_remediation(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.external_systems import (
            _check_sn_entra_user_signin_connections,
        )

        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.servicenow_entra_user_signin_connection(
                    display_name="ServiceNow Prod (EUSI)",
                    status="Error",
                ),
            ],
        ))

        results = _check_sn_entra_user_signin_connections(runner)

        sn_002 = _result_by_id(results, "SN-002")
        assert sn_002.status == "Failed", (
            f"Expected SN-002 to FAIL when an entraIDUserLogin ServiceNow "
            f"connection is in Error state with an AAD token-refresh "
            f"failure, got status={sn_002.status} result={sn_002.result!r}"
        )
        assert sn_002.priority == "High"
        assert "all in Error state" in sn_002.result
        assert "ServiceNow Prod (EUSI)" in sn_002.result
        # Federated-SSO specific remediation copy must surface — this is
        # the whole point of the check.
        assert "Re-authenticate" in sn_002.remediation
        assert "federated identity" in sn_002.remediation.lower()
        assert "external IdP" in sn_002.remediation

    @responses.activate
    def test_all_errored_eusi_servicenow_fails(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.external_systems import (
            _check_sn_entra_user_signin_connections,
        )

        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.servicenow_entra_user_signin_connection(
                    name="a", display_name="SN-A", status="Error",
                ),
                pp.servicenow_entra_user_signin_connection(
                    name="b", display_name="SN-B", status="Error",
                ),
            ],
        ))

        results = _check_sn_entra_user_signin_connections(runner)

        sn_002 = _result_by_id(results, "SN-002")
        assert sn_002.status == "Failed"
        assert "2 ServiceNow connection" in sn_002.result
        assert "all in Error state" in sn_002.result
        assert "SN-A" in sn_002.result
        assert "SN-B" in sn_002.result

    @responses.activate
    def test_non_token_error_skips_federated_specific_guidance(
        self, runner: _MinimalRunner
    ) -> None:
        """An entraIDUserLogin connection in some non-token Error state
        (e.g. backend service unavailable) should still FAIL but the
        remediation should not point at federated SSO since that's not
        the diagnosed cause."""
        from flightcheck.checks.external_systems import (
            _check_sn_entra_user_signin_connections,
        )

        # Build an Error connection then strip token-failure markers
        # to simulate a non-AAD failure.
        conn = pp.servicenow_entra_user_signin_connection(
            display_name="ServiceNow", status="Error",
        )
        conn["properties"]["statuses"] = [
            {
                "status": "Error",
                "target": "service",
                "error": {
                    "code": "ServiceUnavailable",
                    "message": "Backend connector temporarily unavailable.",
                },
            }
        ]

        responses.add(**pp.list_connections(
            env_id=runner.env_id, connections=[conn],
        ))

        results = _check_sn_entra_user_signin_connections(runner)

        sn_002 = _result_by_id(results, "SN-002")
        assert sn_002.status == "Failed"
        assert "Re-authenticate" in sn_002.remediation
        assert "federated identity" not in sn_002.remediation.lower()

    @responses.activate
    def test_token_target_without_aad_fingerprint_skips_federated_guidance(
        self, runner: _MinimalRunner
    ) -> None:
        """Regression for the PR review finding on SN-002:
        ``target == "token"`` + ``code == "Unauthorized"`` is NOT enough
        on its own to attribute the failure to the Entra federation —
        a connector-backend token rejection (e.g. revoked refresh token
        on the ServiceNow side, not in AAD) can produce the same shape
        without any AADSTS / "refresh access token" / "invalid_grant" /
        "not authenticated" fingerprint in the message. In that case
        SN-002 must still fail (the connection IS broken) but the
        remediation must NOT claim the federated identity flow with the
        external IdP is the cause.
        """
        from flightcheck.checks.external_systems import (
            _check_sn_entra_user_signin_connections,
        )

        conn = pp.servicenow_entra_user_signin_connection(
            display_name="ServiceNow", status="Error",
        )
        conn["properties"]["statuses"] = [
            {
                "status": "Error",
                "target": "token",
                "error": {
                    "code": "Unauthorized",
                    "message": "ServiceNow rejected the access token.",
                },
            }
        ]

        responses.add(**pp.list_connections(
            env_id=runner.env_id, connections=[conn],
        ))

        results = _check_sn_entra_user_signin_connections(runner)

        sn_002 = _result_by_id(results, "SN-002")
        assert sn_002.status == "Failed"
        assert "Re-authenticate" in sn_002.remediation
        assert "federated identity" not in sn_002.remediation.lower(), (
            "SN-002 should not attribute a generic token rejection "
            "to the Entra federation without an AAD/refresh fingerprint "
            "in the error message."
        )
        assert "external IdP" not in sn_002.remediation


class TestMixedState:
    @responses.activate
    def test_one_connected_one_errored_passes_overall_but_flags_errored(
        self, runner: _MinimalRunner
    ) -> None:
        """Mirrors the workday _check_connections "mixed state" pattern:
        one healthy + one broken — SN-002 PASSES (the integration
        partially works) but the remediation calls out the broken one."""
        from flightcheck.checks.external_systems import (
            _check_sn_entra_user_signin_connections,
        )

        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.servicenow_entra_user_signin_connection(
                    name="healthy", display_name="ServiceNow Prod (EUSI)",
                    status="Connected",
                ),
                pp.servicenow_entra_user_signin_connection(
                    name="broken", display_name="ServiceNow Stage (EUSI)",
                    status="Error",
                ),
            ],
        ))

        results = _check_sn_entra_user_signin_connections(runner)

        sn_002 = _result_by_id(results, "SN-002")
        assert sn_002.status == "Passed"
        assert "2 ServiceNow connection" in sn_002.result
        assert "1 Connected" in sn_002.result
        assert "1 in Error" in sn_002.result
        assert "ServiceNow Stage (EUSI)" in sn_002.result
        assert "Re-authenticate" in sn_002.remediation
        assert "federated identity" in sn_002.remediation.lower()


class TestSkipScenarios:
    @responses.activate
    def test_no_connections_at_all_returns_empty(
        self, runner: _MinimalRunner
    ) -> None:
        """No connections in environment — SN-002 stays silent (SN-001
        already reports the "no ServiceNow installed" case)."""
        from flightcheck.checks.external_systems import (
            _check_sn_entra_user_signin_connections,
        )

        responses.add(**pp.list_connections(
            env_id=runner.env_id, connections=[],
        ))

        results = _check_sn_entra_user_signin_connections(runner)
        assert results == []

    @responses.activate
    def test_servicenow_connections_but_none_use_eusi_returns_empty(
        self, runner: _MinimalRunner
    ) -> None:
        """ServiceNow connections present but only Basic-auth ones —
        SN-002 stays silent because the federated-SSO failure mode
        cannot apply to non-EUSI connections."""
        from flightcheck.checks.external_systems import (
            _check_sn_entra_user_signin_connections,
        )

        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.servicenow_basic_auth_connection(status="Connected"),
                pp.servicenow_basic_auth_connection(
                    name="another-basic", status="Error",
                ),
            ],
        ))

        results = _check_sn_entra_user_signin_connections(runner)
        assert results == []

    @responses.activate
    def test_only_non_servicenow_connections_returns_empty(
        self, runner: _MinimalRunner
    ) -> None:
        """O365/Dataverse/etc. only — SN-002 not applicable."""
        from flightcheck.checks.external_systems import (
            _check_sn_entra_user_signin_connections,
        )

        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.non_workday_connection(display_name="Office 365"),
                pp.workday_connection(status="Connected"),
            ],
        ))

        results = _check_sn_entra_user_signin_connections(runner)
        assert results == []

    def test_skips_when_env_id_missing(self, pp_client) -> None:
        """No env_id (e.g. derive_environment_id failed) — empty list."""
        from flightcheck.checks.external_systems import (
            _check_sn_entra_user_signin_connections,
        )

        runner_no_env = _MinimalRunner(pp_admin=pp_client, env_id="")
        assert _check_sn_entra_user_signin_connections(runner_no_env) == []

    def test_skips_when_pp_admin_missing(self) -> None:
        """No PP admin client (auth failed) — empty list, no crash."""
        from flightcheck.checks.external_systems import (
            _check_sn_entra_user_signin_connections,
        )

        runner_no_pp = _MinimalRunner(pp_admin=None, env_id=pp.MOCK_ENV_ID)
        assert _check_sn_entra_user_signin_connections(runner_no_pp) == []


class TestApiFiltering:
    @responses.activate
    def test_eusi_connections_for_other_connectors_are_excluded(
        self, runner: _MinimalRunner
    ) -> None:
        """A connection with connectionParametersSet.name=='entraIDUserLogin'
        on a NON-ServiceNow connector (e.g. some other Entra-federated
        connector) must not be picked up by SN-002."""
        from flightcheck.checks.external_systems import (
            _check_sn_entra_user_signin_connections,
        )

        # Take an EUSI ServiceNow record and rewrite its apiId to an
        # unrelated connector — confirms the apiId filter is doing real
        # work, not just blindly trusting the connectionParametersSet field.
        impostor = pp.servicenow_entra_user_signin_connection(
            display_name="Impostor", status="Connected",
        )
        impostor["properties"]["apiId"] = (
            f"/providers/Microsoft.PowerApps/scopes/admin/environments/"
            f"{runner.env_id}/apis/shared_some-other-connector"
        )

        responses.add(**pp.list_connections(
            env_id=runner.env_id, connections=[impostor],
        ))

        assert _check_sn_entra_user_signin_connections(runner) == []
