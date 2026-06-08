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


class TestFindEnvironmentIdByDataverseUrl:
    """Pins the hostname-matching behavior of
    PPAdminClient.find_environment_id_by_dataverse_url.

    Bug being fixed: BAP advertises two URLs per env in
    ``linkedEnvironmentMetadata``:
      - ``instanceUrl``:    https://org<hash>.crm12.dynamics.com/
      - ``instanceApiUrl``: https://org<hash>.api.crm12.dynamics.com

    The config's ``dataverseEndpoint`` is typically the API form, but
    the matcher historically only checked ``instanceUrl``, so every
    tenant with an ``api.`` host silently missed and the caller fell
    back to the Dataverse OrganizationId — which is NOT a valid BAP
    env id and breaks both BAP admin calls AND any URL that embeds
    the env id (e.g. Copilot Studio deep links).
    """

    def _make_client(self, envs):
        from flightcheck.pp_admin_client import PPAdminClient

        client = PPAdminClient(tenant_id="00000000-0000-0000-0000-000000001111")

        # Patch out network: get_environments() now returns the fixture.
        client.get_environments = lambda: envs  # type: ignore[method-assign]
        return client

    def _env(self, *, name, instance_url="", instance_api_url=""):
        linked = {}
        if instance_url:
            linked["instanceUrl"] = instance_url
        if instance_api_url:
            linked["instanceApiUrl"] = instance_api_url
        return {
            "name": name,
            "properties": {"linkedEnvironmentMetadata": linked},
        }

    def test_matches_when_config_uses_api_hostname_and_env_advertises_instance_api_url(
        self,
    ) -> None:
        """The user's repro: config has the .api. host, BAP advertises
        the .api. host on instanceApiUrl. Historically missed because
        only instanceUrl was checked."""
        envs = [
            self._env(
                name="ecf4737d-bef7-e58a-aa5e-e71a60780efc",
                instance_url="https://orgd98aef4a.crm12.dynamics.com/",
                instance_api_url="https://orgd98aef4a.api.crm12.dynamics.com",
            ),
        ]
        client = self._make_client(envs)
        assert (
            client.find_environment_id_by_dataverse_url(
                "https://orgd98aef4a.api.crm12.dynamics.com"
            )
            == "ecf4737d-bef7-e58a-aa5e-e71a60780efc"
        )

    def test_matches_when_config_uses_web_hostname_and_env_advertises_instance_url(
        self,
    ) -> None:
        """Original behavior: config has the bare .crm. host, BAP
        advertises it on instanceUrl. Must still match."""
        envs = [
            self._env(
                name="bap-env-1",
                instance_url="https://orgmocktenant.crm.dynamics.com/",
                instance_api_url="https://orgmocktenant.api.crm.dynamics.com",
            ),
        ]
        client = self._make_client(envs)
        assert (
            client.find_environment_id_by_dataverse_url(
                "https://orgmocktenant.crm.dynamics.com/"
            )
            == "bap-env-1"
        )

    def test_returns_none_when_no_env_matches_either_url_field(self) -> None:
        envs = [
            self._env(
                name="bap-env-1",
                instance_url="https://otherorg.crm.dynamics.com/",
                instance_api_url="https://otherorg.api.crm.dynamics.com",
            ),
        ]
        client = self._make_client(envs)
        assert (
            client.find_environment_id_by_dataverse_url(
                "https://orgd98aef4a.api.crm12.dynamics.com"
            )
            is None
        )

    def test_skips_envs_with_empty_url_fields(self) -> None:
        """Some BAP env records (e.g. envs without linked Dataverse)
        have no instanceUrl/instanceApiUrl. They must not raise and
        must not produce false matches."""
        envs = [
            self._env(name="bap-env-empty"),
            self._env(
                name="bap-env-match",
                instance_api_url="https://orgd98aef4a.api.crm12.dynamics.com",
            ),
        ]
        client = self._make_client(envs)
        assert (
            client.find_environment_id_by_dataverse_url(
                "https://orgd98aef4a.api.crm12.dynamics.com"
            )
            == "bap-env-match"
        )


class TestDeriveEnvironmentIdFallbackBehavior:
    """Pins the post-fix behavior of derive_environment_id.

    Before: when pp_admin was supplied but the matcher returned None,
    we silently fell through to WhoAmI/OrganizationId. That value is
    NOT a valid BAP env id — every downstream BAP admin call 404s, and
    any URL that embeds it (Copilot Studio deep link, maker portal)
    points at a non-existent env.

    After: when pp_admin is supplied, the matcher's verdict is final.
    A None means "could not resolve via BAP" and is surfaced to the
    caller; downstream features (deep links, BAP-scoped checks)
    degrade gracefully rather than silently fabricating wrong targets.
    """

    def test_returns_none_when_pp_admin_supplied_but_matcher_misses(self) -> None:
        from flightcheck.pp_admin_client import derive_environment_id

        class StubAdmin:
            def find_environment_id_by_dataverse_url(self, _env_url):
                return None

        # Must NOT fall through to WhoAmI/OrganizationId even though
        # we pass a non-empty dataverse_token. The whole point is to
        # avoid the fabricated-OrgId footgun. If this test starts
        # failing because the function hit the network, that means the
        # silent-fallback regression has come back.
        result = derive_environment_id(
            "https://orgd98aef4a.api.crm12.dynamics.com",
            "fake-token-must-not-be-used",
            pp_admin=StubAdmin(),
        )
        assert result is None

    def test_returns_bap_id_when_pp_admin_supplied_and_matcher_hits(self) -> None:
        from flightcheck.pp_admin_client import derive_environment_id

        class StubAdmin:
            def find_environment_id_by_dataverse_url(self, _env_url):
                return "ecf4737d-bef7-e58a-aa5e-e71a60780efc"

        result = derive_environment_id(
            "https://orgd98aef4a.api.crm12.dynamics.com",
            "fake-token",
            pp_admin=StubAdmin(),
        )
        assert result == "ecf4737d-bef7-e58a-aa5e-e71a60780efc"
