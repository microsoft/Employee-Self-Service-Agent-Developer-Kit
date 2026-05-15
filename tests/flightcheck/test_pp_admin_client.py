# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Regression tests for solutions/ess-maker-skills/scripts/flightcheck/pp_admin_client.py.

Currently focused on bug 4 — ``_get_all`` only handles 401/403 specially;
404s and 5xx's bubble up as ``requests.exceptions.HTTPError`` and crash
any FlightCheck check that calls into the affected helper.

The behavior is reproduced from a real cassette captured against the
user's tenant — see
``tests/fixtures/cassettes/flightcheck_pp_admin.yaml`` line 2578-2621
where ``GET /providers/Microsoft.ProcessSimple/scopes/admin/environments/{env}/v2/flows``
returns 404 ResourceNotFound for a Dataverse-only environment.

When the bug is fixed (recommended: have ``_get_all`` return
``{"_error": "...", "_status": 404}`` consistent with ``_get`` on 401/403),
flip the assertions in this file.
"""

from __future__ import annotations

import pytest
import requests
import responses

from tests.conftest import require_validated_mock
from tests.mocks import pp_admin as pp

require_validated_mock(pp)


@pytest.fixture
def pp_client(fake_token: str):
    """Real PPAdminClient with a pre-populated token."""
    from flightcheck.pp_admin_client import PPAdminClient

    client = PPAdminClient(tenant_id="00000000-0000-0000-0000-000000001111")
    client._token = fake_token
    return client


class TestGetAll404Crashes:
    @responses.activate
    def test_get_flows_raises_http_error_on_404(self, pp_client) -> None:
        """Regression: latent bug. Pinned current crashing behavior.

        When PowerApps ProcessSimple returns 404 (env exists in BAP but
        not in PowerApps — happens for Dataverse-only envs), the kit's
        get_flows() bubbles up requests.HTTPError instead of returning
        an empty list or a structured error dict. Any FlightCheck check
        that calls get_flows() crashes mid-run.

        TODO: in pp_admin_client.py:131-144, extend _get_all's
        401/403 handling to also catch 404 and 5xx. Recommended return
        shape (matches _get): {"_error": "resource_not_found", "_status": 404}.
        Then update _check_workflows / _check_flow_status in
        flightcheck/checks/workday.py to surface the structured error
        as a WARNING result. Flip this test's assertions when fixed.
        """
        responses.add(**pp.flows_resource_not_found(env_id=pp.MOCK_ENV_ID))

        with pytest.raises(requests.exceptions.HTTPError) as exc_info:
            pp_client.get_flows(pp.MOCK_ENV_ID)

        assert exc_info.value.response.status_code == 404
        # Once fixed, this test should change to:
        #   result = pp_client.get_flows(pp.MOCK_ENV_ID)
        #   assert result == {"_error": "resource_not_found", "_status": 404}

    @responses.activate
    def test_get_connections_handles_403_gracefully_returns_empty_list(
        self, pp_client
    ) -> None:
        """Companion test: 401/403 ARE handled (return empty list).
        This pins the existing behavior so we know it doesn't regress
        if the fix above is implemented.

        Note: returning an empty list here is itself bug 2 (the kit
        also has a separate inconsistency between _get_all returning a
        list and _get returning a dict on 401/403). When bug 2 is
        fixed, both this test and the test_403_from_bap_is_misreported_*
        test in test_workday_connections.py need updating in lockstep.
        """
        responses.add(**pp.insufficient_permissions(
            env_id=pp.MOCK_ENV_ID, endpoint="connections",
        ))
        result = pp_client.get_connections(pp.MOCK_ENV_ID)
        assert result == []
