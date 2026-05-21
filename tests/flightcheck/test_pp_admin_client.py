# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Regression tests for solutions/ess-maker-skills/scripts/flightcheck/pp_admin_client.py.

Covers behavior that historically had latent bugs the kit needs to
not regress on (401/403 handling on the connections endpoint, etc.).

Historical note: an earlier version of this file pinned a 404 from
``GET https://api.powerapps.com/.../v2/flows`` as "expected behavior
for Dataverse-only environments." That was a misdiagnosis — the
flow listing endpoint actually lives on ``api.flow.microsoft.com``
with a separate audience token. ``pp_admin_client.get_flows()`` now
targets the correct host. The captured 404 was a wrong-URL artefact,
not a Dataverse-only-env signal, and the regression test that
codified it has been removed.
"""

from __future__ import annotations

import pytest
import responses

from tests.conftest import require_validated_mock
from tests.mocks import pp_admin as pp

require_validated_mock(pp)


@pytest.fixture
def pp_client(fake_token: str):
    """Real PPAdminClient with both PowerApps and Flow audience tokens populated."""
    from flightcheck.pp_admin_client import PPAdminClient

    client = PPAdminClient(tenant_id="00000000-0000-0000-0000-000000001111")
    client._token = fake_token
    # get_flows()/get_flow() use the flow audience token; tests that
    # exercise either need this set or `flow_headers` raises.
    client._flow_token = fake_token
    return client


class TestPermissionHandling:
    @responses.activate
    def test_get_connections_handles_403_gracefully_returns_empty_list(
        self, pp_client
    ) -> None:
        """Companion test: 401/403 ARE handled (return empty list).
        This pins the existing behavior so we know it doesn't regress.

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
