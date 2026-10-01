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

import base64
import json
from pathlib import Path
from unittest.mock import Mock, call
from urllib.parse import parse_qs, urlparse

import pytest
import responses
import vcr
from requests import HTTPError

from tests.conftest import require_validated_mock
from tests.mocks import pp_admin as pp

require_validated_mock(pp)


_BAP_SCOPE = "https://api.bap.microsoft.com/.default"
_PP_SCOPE = "https://service.powerapps.com//.default"
_FLOW_SCOPE = "https://service.flow.microsoft.com//.default"
_TENANT = "00000000-0000-0000-0000-000000001111"
_ACCOUNT = {"username": "maker@example.com", "home_account_id": "maker.home"}
_CLAIMS = {"preferred_username": "maker@example.com", "oid": "maker", "tid": _TENANT}
_TOKENS = {_BAP_SCOPE: "bap-token", _PP_SCOPE: "pp-token", _FLOW_SCOPE: "flow-token"}


@pytest.fixture
def isolated_msal(monkeypatch, tmp_path):
    """Fake MSAL and a temporary cwd: never read the operator's cache."""
    from flightcheck import pp_admin_client

    monkeypatch.chdir(tmp_path)
    cache = Mock(has_state_changed=False)
    app = Mock()
    app.get_accounts.return_value = []
    app.acquire_token_silent.return_value = None
    app.acquire_token_interactive.side_effect = lambda scopes, **kwargs: {
        "access_token": _TOKENS[scopes[0]],
        "id_token_claims": dict(_CLAIMS),
    }
    factory = Mock(return_value=app)
    monkeypatch.setattr(pp_admin_client.msal, "SerializableTokenCache", lambda: cache)
    monkeypatch.setattr(pp_admin_client.msal, "PublicClientApplication", factory)
    return app, cache, factory


class TestAuthenticationScope:
    @pytest.mark.parametrize("tenant", ["organizations", _TENANT])
    def test_bap_only_never_requests_powerapps_or_flow(self, isolated_msal, tenant):
        from flightcheck.pp_admin_client import PPAdminClient

        app, cache, factory = isolated_msal
        client = PPAdminClient(tenant)
        assert client.authenticate(include_powerapps=False, include_flow=False) == "bap-token"
        factory.assert_called_once_with(
            "417219b4-3a7d-42a2-bdb1-972bd8281a02",
            authority=f"https://login.microsoftonline.com/{tenant}",
            token_cache=cache,
        )
        app.acquire_token_interactive.assert_called_once_with(
            [_BAP_SCOPE], prompt="select_account",
        )
        assert client._token is None
        assert client._flow_token is None
        assert client.signed_in_username == "maker@example.com"

    def test_powerapps_only_preserves_return_and_username(self, isolated_msal):
        from flightcheck.pp_admin_client import PPAdminClient

        app, _, _ = isolated_msal
        client = PPAdminClient(_TENANT)
        assert client.authenticate(include_bap=False, include_flow=False) == "pp-token"
        app.acquire_token_interactive.assert_called_once_with(
            [_PP_SCOPE], prompt="select_account",
        )
        assert client._bap_token is None
        assert client._flow_token is None
        assert client.signed_in_username == "maker@example.com"

    def test_default_auth_keeps_flow_and_returns_powerapps(self, isolated_msal):
        from flightcheck.pp_admin_client import PPAdminClient

        app, _, _ = isolated_msal
        client = PPAdminClient(_TENANT)
        assert client.authenticate() == "pp-token"
        assert app.acquire_token_interactive.call_args_list == [
            call([_PP_SCOPE], prompt="select_account"),
            call([_BAP_SCOPE], prompt="select_account", login_hint="maker@example.com"),
            call([_FLOW_SCOPE], prompt="select_account", login_hint="maker@example.com"),
        ]
        assert client._bap_token == "bap-token"
        assert client._flow_token == "flow-token"

    def test_flow_only_uses_existing_flow_scope(self, isolated_msal):
        from flightcheck.pp_admin_client import PPAdminClient

        app, _, _ = isolated_msal
        client = PPAdminClient(_TENANT)
        assert client.authenticate(include_bap=False, include_powerapps=False) == "flow-token"
        app.acquire_token_interactive.assert_called_once_with(
            [_FLOW_SCOPE], prompt="select_account",
        )
        assert client._token is client._bap_token is None

    def test_no_audience_is_an_explicit_error(self, isolated_msal):
        from flightcheck.pp_admin_client import PPAdminClient

        with pytest.raises(ValueError, match="at least one"):
            PPAdminClient(_TENANT).authenticate(
                include_bap=False, include_powerapps=False, include_flow=False,
            )
        isolated_msal[2].assert_not_called()

    def test_preferred_cached_account_used_for_every_audience(self, isolated_msal):
        from flightcheck.pp_admin_client import PPAdminClient

        app, _, _ = isolated_msal
        app.get_accounts.return_value = [{"username": "other@example.com"}, _ACCOUNT]
        app.acquire_token_silent.side_effect = lambda scopes, **kwargs: {
            "access_token": _TOKENS[scopes[0]],
        }
        client = PPAdminClient(_TENANT)
        client.authenticate(preferred_username="MAKER@example.com")
        assert app.acquire_token_silent.call_args_list == [
            call([scope], account=_ACCOUNT)
            for scope in [_PP_SCOPE, _BAP_SCOPE, _FLOW_SCOPE]
        ]
        app.acquire_token_interactive.assert_not_called()
        assert client.signed_in_username == "maker@example.com"

    def test_interactive_account_selection_refreshes_cache_for_other_audiences(
        self, isolated_msal,
    ):
        from flightcheck.pp_admin_client import PPAdminClient

        app, _, _ = isolated_msal
        other = {"username": "other@example.com"}
        app.get_accounts.side_effect = [[other], [other, _ACCOUNT], [other, _ACCOUNT]]
        app.acquire_token_silent.side_effect = [
            None,
            {"access_token": "bap-token", "id_token_claims": _CLAIMS},
            {"access_token": "flow-token", "id_token_claims": _CLAIMS},
        ]
        client = PPAdminClient(_TENANT)
        client.authenticate()
        assert app.acquire_token_silent.call_args_list == [
            call([_PP_SCOPE], account=other),
            call([_BAP_SCOPE], account=_ACCOUNT),
            call([_FLOW_SCOPE], account=_ACCOUNT),
        ]
        app.acquire_token_interactive.assert_called_once_with(
            [_PP_SCOPE], prompt="select_account",
        )
        assert client.signed_in_username == "maker@example.com"

    def test_unknown_preferred_account_does_not_use_another_cached_account(
        self, isolated_msal,
    ):
        from flightcheck.pp_admin_client import PPAdminClient

        app, _, _ = isolated_msal
        app.get_accounts.return_value = [{"username": "other@example.com"}]
        PPAdminClient(_TENANT).authenticate(
            include_powerapps=False, include_flow=False,
            preferred_username="maker@example.com",
        )
        app.acquire_token_silent.assert_not_called()
        app.acquire_token_interactive.assert_called_once_with(
            [_BAP_SCOPE], prompt="select_account", login_hint="maker@example.com",
        )

    @pytest.mark.parametrize("field", ["preferred_username", "oid", "tid"])
    def test_mixed_account_or_tenant_is_rejected_without_publishing_tokens(
        self, isolated_msal, field,
    ):
        from flightcheck.pp_admin_client import PPAdminClient

        app, _, _ = isolated_msal
        app.acquire_token_interactive.side_effect = [
            {"access_token": "pp-token", "id_token_claims": _CLAIMS},
            {"access_token": "bap-token", "id_token_claims": {**_CLAIMS, field: "different"}},
        ]
        client = PPAdminClient(_TENANT)
        with pytest.raises(RuntimeError, match="BAP .*account_mismatch"):
            client.authenticate()
        assert client._token is client._bap_token is client._flow_token is None
        assert client.signed_in_username is None

    @pytest.mark.parametrize("result", [None, {}, {"access_token": ""}, {"access_token": "  "}, {"access_token": 7}])
    def test_invalid_interactive_token_is_an_auth_error(self, isolated_msal, result):
        from flightcheck.pp_admin_client import PPAdminClient

        app, _, _ = isolated_msal
        app.acquire_token_interactive.side_effect = None
        app.acquire_token_interactive.return_value = result
        client = PPAdminClient(_TENANT)
        client._bap_token = "stale-token"
        with pytest.raises(RuntimeError, match="auth failed for BAP"):
            client.authenticate(include_powerapps=False, include_flow=False)
        assert client._bap_token is None

    @pytest.mark.parametrize("result", [None, {}, {"access_token": ""}, {"access_token": "  "}, {"error": "interaction_required"}])
    def test_invalid_silent_result_falls_back_to_interactive(self, isolated_msal, result):
        from flightcheck.pp_admin_client import PPAdminClient

        app, _, _ = isolated_msal
        app.get_accounts.return_value = [_ACCOUNT]
        app.acquire_token_silent.return_value = result
        client = PPAdminClient(_TENANT)
        assert client.authenticate(include_powerapps=False, include_flow=False) == "bap-token"
        app.acquire_token_silent.assert_called_once_with([_BAP_SCOPE], account=_ACCOUNT)
        app.acquire_token_interactive.assert_called_once()

    def test_auth_error_does_not_echo_error_description(self, isolated_msal):
        from flightcheck.pp_admin_client import PPAdminClient

        app, _, _ = isolated_msal
        app.acquire_token_interactive.side_effect = None
        app.acquire_token_interactive.return_value = {
            "error": "access_denied", "error_description": "private server details",
        }
        with pytest.raises(RuntimeError) as exc:
            PPAdminClient(_TENANT).authenticate(include_powerapps=False, include_flow=False)
        assert str(exc.value) == "Power Platform auth failed for BAP (access_denied)."

    def test_msal_exception_propagates_for_mandatory_auth(self, isolated_msal):
        from flightcheck.pp_admin_client import PPAdminClient

        app, _, _ = isolated_msal
        app.acquire_token_interactive.side_effect = RuntimeError("MSAL unavailable")
        with pytest.raises(RuntimeError, match="MSAL unavailable"):
            PPAdminClient(_TENANT).authenticate(include_powerapps=False, include_flow=False)

    @pytest.mark.parametrize("failed_scope", [_BAP_SCOPE, _FLOW_SCOPE])
    def test_failed_secondary_audience_does_not_publish_partial_auth(
        self, isolated_msal, failed_scope,
    ):
        from flightcheck.pp_admin_client import PPAdminClient

        app, _, _ = isolated_msal
        app.acquire_token_interactive.side_effect = lambda scopes, **kwargs: (
            {"error": "access_denied"} if scopes == [failed_scope]
            else {"access_token": _TOKENS[scopes[0]], "id_token_claims": _CLAIMS}
        )
        client = PPAdminClient(_TENANT)
        with pytest.raises(RuntimeError, match="access_denied"):
            client.authenticate()
        assert client._token is client._bap_token is client._flow_token is None

    def test_changed_fake_cache_is_persisted(self, isolated_msal, tmp_path):
        from flightcheck.pp_admin_client import PPAdminClient

        _, cache, _ = isolated_msal
        local = tmp_path / ".local"
        local.mkdir()
        path = local / ".token_cache.bin"
        path.write_text("fake cache before", encoding="utf-8")
        cache.has_state_changed = True
        cache.serialize.return_value = "fake cache after"
        PPAdminClient(_TENANT).authenticate(include_powerapps=False, include_flow=False)
        cache.deserialize.assert_called_once_with("fake cache before")
        assert path.read_text(encoding="utf-8") == "fake cache after"


@pytest.fixture
def pp_client():
    """Real client with distinct audience tokens to detect cross-routing."""
    from flightcheck.pp_admin_client import PPAdminClient

    client = PPAdminClient(tenant_id="00000000-0000-0000-0000-000000001111")
    client._token = "pp-token"
    client._bap_token = "bap-token"
    # get_flows()/get_flow() use the flow audience token; tests that
    # exercise either need this set or `flow_headers` raises.
    client._flow_token = "flow-token"
    return client


class TestPermissionHandling:
    @responses.activate
    def test_get_connections_returns_error_dict_on_403(
        self, pp_client
    ) -> None:
        """401/403 on a paginated endpoint surfaces a structured
        ``{"_error": ...}`` dict (matching ``_get``), so callers can
        distinguish a permission failure from a genuinely empty
        collection. (Previously ``_get_all`` swallowed 401/403 into an
        empty list — "bug 2"; this is the fixed behavior.)
        """
        responses.add(**pp.insufficient_permissions(
            env_id=pp.MOCK_ENV_ID, endpoint="connections",
        ))
        result = pp_client.get_connections(pp.MOCK_ENV_ID)
        assert isinstance(result, dict)
        assert result["_error"] == "insufficient_permissions"
        assert result["_status"] == 403


_BAP_PATH = "https://api.bap.microsoft.com/providers/Microsoft.BusinessAppPlatform/scopes/admin"
_PP_PATH = "https://api.powerapps.com/providers/Microsoft.PowerApps"
_FLOW_PATH = "https://api.flow.microsoft.com/providers/Microsoft.ProcessSimple"
_ROUTES = [
    ("get_environment", (pp.MOCK_ENV_ID,), f"{_BAP_PATH}/environments/{pp.MOCK_ENV_ID}", pp.environment(), False, "bap-token"),
    ("get_environments", (), f"{_BAP_PATH}/environments", pp.environment(), True, "bap-token"),
    ("get_dlp_policies", (), f"{_BAP_PATH}/apiPolicies", pp.dlp_policy(), True, "bap-token"),
    ("get_connections", (pp.MOCK_ENV_ID,), f"{_PP_PATH}/scopes/admin/environments/{pp.MOCK_ENV_ID}/connections", pp.connection(), True, "pp-token"),
    ("get_connector_connections", (pp.MOCK_ENV_ID, "shared_workdaysoap"), f"{_PP_PATH}/apis/shared_workdaysoap/connections", pp.connection(), True, "pp-token"),
    ("get_flows", (pp.MOCK_ENV_ID,), f"{_FLOW_PATH}/scopes/admin/environments/{pp.MOCK_ENV_ID}/v2/flows", pp.flow(), True, "flow-token"),
    ("get_flow", (pp.MOCK_ENV_ID, "flow-id"), f"{_FLOW_PATH}/scopes/admin/environments/{pp.MOCK_ENV_ID}/flows/flow-id", pp.flow_detail(), False, "flow-token"),
    ("get_flow_runs", (pp.MOCK_ENV_ID, "flow-id"), f"{_FLOW_PATH}/environments/{pp.MOCK_ENV_ID}/flows/flow-id/runs", pp.flow_run(), False, "flow-token"),
]


class TestAudienceRouting:
    @pytest.mark.parametrize("method,args,url,record,paginated,token", _ROUTES)
    @responses.activate
    def test_routes_each_endpoint_to_its_own_bearer(
        self, pp_client, method, args, url, record, paginated, token,
    ):
        is_list = paginated or method == "get_flow_runs"
        body = pp.collection([record]) if is_list else record
        responses.add("GET", url, json=body)
        assert getattr(pp_client, method)(*args) == ([record] if is_list else record)
        request = responses.calls[0].request
        assert request.headers["Authorization"] == f"Bearer {token}"
        assert request.headers["Accept"] == "application/json"
        query = parse_qs(urlparse(request.url).query)
        assert query["api-version"] == [
            "2021-04-01" if token == "bap-token" else "2016-11-01"
        ]
        if method == "get_connector_connections":
            assert query["$filter"] == [f"environment eq '{pp.MOCK_ENV_ID}'"]

    @pytest.mark.parametrize("method,args,url,record,paginated,token", [r for r in _ROUTES if r[4]])
    @pytest.mark.parametrize("next_key", ["nextLink", "@odata.nextLink"])
    @responses.activate
    def test_next_links_keep_the_original_audience(
        self, pp_client, method, args, url, record, paginated, token, next_key,
    ):
        next_url = f"{url}?$skiptoken=page2"
        responses.add("GET", url, json={"value": [record], next_key: next_url})
        responses.add(
            "GET", next_url, json=pp.collection([record]),
            match=[responses.matchers.query_param_matcher({"$skiptoken": "page2"})],
        )
        assert getattr(pp_client, method)(*args) == [record, record]
        assert len(responses.calls) == 2
        assert [c.request.headers["Authorization"] for c in responses.calls] == [
            f"Bearer {token}", f"Bearer {token}",
        ]

    @pytest.mark.parametrize("method,args,url,record,paginated,token", _ROUTES)
    @pytest.mark.parametrize("status", [401, 403])
    @responses.activate
    def test_permission_failures_are_not_empty_successes(
        self, pp_client, method, args, url, record, paginated, token, status,
    ):
        responses.add("GET", url, status=status)
        assert getattr(pp_client, method)(*args) == {
            "_error": "insufficient_permissions", "_status": status,
        }

    @pytest.mark.parametrize("method,args,url,record,paginated,token", [r for r in _ROUTES if r[4]])
    @pytest.mark.parametrize("status", [401, 403, 404])
    @responses.activate
    def test_page_failure_never_returns_partial_data(
        self, pp_client, method, args, url, record, paginated, token, status,
    ):
        next_url = f"{url}?$skiptoken=page2"
        responses.add("GET", url, json=pp.collection([record], next_link=next_url))
        responses.add(
            "GET", next_url, status=status,
            match=[responses.matchers.query_param_matcher({"$skiptoken": "page2"})],
        )
        if status == 404:
            with pytest.raises(HTTPError):
                getattr(pp_client, method)(*args)
        else:
            assert getattr(pp_client, method)(*args) == {
                "_error": "insufficient_permissions", "_status": status,
            }

    @pytest.mark.parametrize("method,args,url,record,paginated,token", _ROUTES)
    @pytest.mark.parametrize("missing_token", [None, ""])
    @responses.activate
    def test_missing_audience_token_never_falls_back_to_another(
        self, pp_client, method, args, url, record, paginated, token, missing_token,
    ):
        setattr(pp_client, {
            "bap-token": "_bap_token", "pp-token": "_token", "flow-token": "_flow_token",
        }[token], missing_token)
        with pytest.raises(RuntimeError, match="authenticate"):
            getattr(pp_client, method)(*args)
        assert not responses.calls

    def test_existing_cassette_replays_with_separate_bap_and_powerapps_bearers(
        self, pp_client, monkeypatch,
    ):
        from flightcheck.pp_admin_client import _SESSION

        get = Mock(wraps=_SESSION.get)
        monkeypatch.setattr(_SESSION, "get", get)
        cassette = Path(__file__).parents[1] / "fixtures" / "cassettes" / "flightcheck_pp_admin.yaml"
        with vcr.use_cassette(str(cassette), record_mode="none") as recorded:
            assert pp_client.get_environments()
            assert pp_client.get_environment(_TENANT)["name"] == _TENANT
            assert pp_client.get_dlp_policies() == []
            assert isinstance(pp_client.get_connections(_TENANT), list)
        assert recorded.play_count == 4
        assert [c.kwargs["headers"]["Authorization"] for c in get.call_args_list] == [
            "Bearer bap-token", "Bearer bap-token", "Bearer bap-token", "Bearer pp-token",
        ]


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


class TestGetDlpPoliciesForEnv:
    """Pins environment-scoping of get_dlp_policies_for_env across both
    DLP policy schemas.

    Bug being fixed: the filter historically read env scope ONLY from the
    legacy ``properties.environmentFilter.environments``. Modern-schema
    policies store scope under ``properties.definition.constraints``
    (``EnvironmentFilter``) and leave ``environmentFilter`` empty, so a
    modern policy scoped to a DIFFERENT environment resolved to an empty
    env list and was wrongly treated as tenant-wide — corrupting the
    INFRA-006 verdict (false FAIL/WARN) for that environment.
    """

    _THIS_ENV = pp.MOCK_ENV_ID
    _OTHER_ENV = "Default-99999999-9999-9999-9999-999999999999"

    def _client(self, policies):
        from flightcheck.pp_admin_client import PPAdminClient

        client = PPAdminClient(tenant_id="00000000-0000-0000-0000-000000001111")
        client.get_dlp_policies = lambda: policies  # type: ignore[method-assign]
        return client

    def test_unscoped_policy_applies_to_all_envs(self):
        client = self._client([pp.dlp_policy_modern(business=["shared_x"])])
        result = client.get_dlp_policies_for_env(self._THIS_ENV)
        assert len(result) == 1

    def test_legacy_include_scopes_by_env(self):
        client = self._client([
            pp.dlp_policy(display_name="here", environments=[self._THIS_ENV]),
            pp.dlp_policy(display_name="elsewhere", environments=[self._OTHER_ENV]),
        ])
        result = client.get_dlp_policies_for_env(self._THIS_ENV)
        names = [p["properties"]["displayName"] for p in result]
        assert names == ["here"]

    def test_modern_scoped_to_this_env_is_included(self):
        client = self._client([
            pp.dlp_policy_modern(display_name="here", environments=[self._THIS_ENV]),
        ])
        result = client.get_dlp_policies_for_env(self._THIS_ENV)
        assert len(result) == 1

    def test_modern_scoped_to_other_env_is_excluded(self):
        # The core regression: a modern policy governing a DIFFERENT env
        # must NOT be returned as effective on this env.
        client = self._client([
            pp.dlp_policy_modern(display_name="elsewhere", environments=[self._OTHER_ENV]),
        ])
        result = client.get_dlp_policies_for_env(self._THIS_ENV)
        assert result == []

    def test_permission_error_passthrough(self):
        client = self._client({"_error": "insufficient_permissions", "_status": 403})
        result = client.get_dlp_policies_for_env(self._THIS_ENV)
        assert isinstance(result, dict)
        assert result["_error"] == "insufficient_permissions"


class TestPolicyEnvScopeParsing:
    """Direct coverage for the schema-aware env-scope extractor."""

    def test_modern_constraints_scope_and_default_include(self):
        from flightcheck.pp_admin_client import _policy_applies_to_env

        policy = pp.dlp_policy_modern(environments=["env-a"])
        assert _policy_applies_to_env(policy, "env-a") is True
        assert _policy_applies_to_env(policy, "env-b") is False

    def test_exclude_filter_applies_to_all_but_listed(self):
        from flightcheck.pp_admin_client import _policy_env_scope, _policy_applies_to_env

        policy = pp.dlp_policy_modern(environments=["env-a"])
        # Flip the modern constraint to an exclude filter.
        params = (
            policy["properties"]["definition"]["constraints"]
            ["environmentFilter1"]["parameters"]
        )
        params["filterType"] = "exclude"

        ft, ids = _policy_env_scope(policy)
        assert ft == "exclude" and ids == ["env-a"]
        assert _policy_applies_to_env(policy, "env-a") is False
        assert _policy_applies_to_env(policy, "env-b") is True

    def test_unscoped_policy_has_no_filter(self):
        from flightcheck.pp_admin_client import _policy_env_scope

        assert _policy_env_scope(pp.dlp_policy_modern()) == (None, [])


class TestGetEnvironmentSkuByDataverseUrl:
    """Pins PPAdminClient.get_environment_sku_by_dataverse_url — the deploy
    telemetry classifier resolves sandbox-vs-production from this SKU. Mirrors
    the host-matching contract of find_environment_id_by_dataverse_url (matches
    on both instanceUrl and instanceApiUrl), but returns the SKU string."""

    def _make_client(self, envs):
        from flightcheck.pp_admin_client import PPAdminClient

        client = PPAdminClient(tenant_id="00000000-0000-0000-0000-000000001111")
        client.get_environments = lambda: envs  # type: ignore[method-assign]
        return client

    def _env(self, *, sku=None, env_type=None, instance_url="", instance_api_url=""):
        linked = {}
        if instance_url:
            linked["instanceUrl"] = instance_url
        if instance_api_url:
            linked["instanceApiUrl"] = instance_api_url
        props = {"linkedEnvironmentMetadata": linked}
        if sku is not None:
            props["environmentSku"] = sku
        if env_type is not None:
            props["environmentType"] = env_type
        return {"name": "bap-env-1", "properties": props}

    def test_returns_sku_on_host_match(self):
        client = self._make_client([
            self._env(sku="Sandbox",
                      instance_api_url="https://orgd98aef4a.api.crm12.dynamics.com"),
        ])
        assert client.get_environment_sku_by_dataverse_url(
            "https://orgd98aef4a.api.crm12.dynamics.com"
        ) == "Sandbox"

    def test_falls_back_to_environment_type_when_no_sku(self):
        client = self._make_client([
            self._env(env_type="Production",
                      instance_url="https://orgmocktenant.crm.dynamics.com/"),
        ])
        assert client.get_environment_sku_by_dataverse_url(
            "https://orgmocktenant.crm.dynamics.com/"
        ) == "Production"

    def test_returns_none_when_no_env_matches(self):
        client = self._make_client([
            self._env(sku="Production",
                      instance_url="https://otherorg.crm.dynamics.com/"),
        ])
        assert client.get_environment_sku_by_dataverse_url(
            "https://orgd98aef4a.api.crm12.dynamics.com"
        ) is None

    def test_skips_envs_with_empty_url_fields(self):
        client = self._make_client([
            self._env(sku="ignored"),  # no linked URLs
            self._env(sku="Trial",
                      instance_api_url="https://orgd98aef4a.api.crm12.dynamics.com"),
        ])
        assert client.get_environment_sku_by_dataverse_url(
            "https://orgd98aef4a.api.crm12.dynamics.com"
        ) == "Trial"


class TestAuthenticateSilent:
    """authenticate_silent() must NEVER prompt interactively; when there is no
    cached token it returns False so best-effort callers (push telemetry) fall
    back cleanly instead of popping a browser."""

    def test_returns_false_when_no_token_cache(self, chdir_kit_root):
        from flightcheck.pp_admin_client import PPAdminClient

        # chdir_kit_root created .local/ but no .token_cache.bin — the guard
        # returns False before touching MSAL (no interactive prompt).
        client = PPAdminClient(tenant_id="00000000-0000-0000-0000-000000001111")
        assert client.authenticate_silent() is False

    @pytest.mark.parametrize("result", [
        None, {}, {"error": "interaction_required"}, {"access_token": ""},
        {"access_token": "  "}, {"access_token": 7}, {"access_token": "bap-token"},
    ])
    @responses.activate
    def test_optional_push_sku_uses_only_silent_bap(
        self, isolated_msal, tmp_path, monkeypatch, result,
    ):
        import push

        app, _, factory = isolated_msal
        local = tmp_path / ".local"
        local.mkdir()
        (local / ".token_cache.bin").write_text("fake cache", encoding="utf-8")
        app.get_accounts.return_value = [_ACCOUNT]
        app.acquire_token_silent.return_value = result
        monkeypatch.setattr("auth.discover_tenant", lambda _: _TENANT)
        valid = result == {"access_token": "bap-token"}
        if valid:
            responses.add(**pp.list_environments(environments=[pp.environment()]))
        sku = push._lookup_environment_sku_silent("https://orgmocktenant.crm.dynamics.com")
        assert sku == ("Production" if valid else None)
        app.acquire_token_silent.assert_called_once_with([_BAP_SCOPE], account=_ACCOUNT)
        app.acquire_token_interactive.assert_not_called()
        assert factory.call_args.args == ("417219b4-3a7d-42a2-bdb1-972bd8281a02",)
        assert factory.call_args.kwargs["authority"] == f"https://login.microsoftonline.com/{_TENANT}"
        if valid:
            assert responses.calls[0].request.headers["Authorization"] == "Bearer bap-token"
        else:
            assert not responses.calls

    @pytest.mark.parametrize("failure", ["no_accounts", "bad_cache", "silent_error"])
    def test_optional_failures_never_prompt_or_leave_stale_bap(
        self, isolated_msal, tmp_path, failure,
    ):
        from flightcheck.pp_admin_client import PPAdminClient

        app, cache, _ = isolated_msal
        local = tmp_path / ".local"
        local.mkdir()
        (local / ".token_cache.bin").write_text("fake cache", encoding="utf-8")
        if failure == "bad_cache":
            cache.deserialize.side_effect = ValueError("bad cache")
        elif failure == "silent_error":
            app.get_accounts.return_value = [_ACCOUNT]
            app.acquire_token_silent.side_effect = RuntimeError("offline")
        client = PPAdminClient(_TENANT)
        client._bap_token = "stale-token"
        assert client.authenticate_silent() is False
        assert client._bap_token is None
        app.acquire_token_interactive.assert_not_called()


class TestBapOnlyCallers:
    @responses.activate
    def test_environment_discovery_returns_tenant_from_the_actual_bap_token(
        self, isolated_msal,
    ):
        import list_environments

        app, _, factory = isolated_msal
        payload = base64.urlsafe_b64encode(json.dumps({"tid": _TENANT}).encode()).decode().rstrip("=")
        token = f"header.{payload}.signature"
        app.acquire_token_interactive.side_effect = None
        app.acquire_token_interactive.return_value = {"access_token": token, "id_token_claims": _CLAIMS}
        responses.add(**pp.list_environments(environments=[pp.environment()]))
        envs, tenant = list_environments.list_environments_with_tenant()
        assert tenant == _TENANT
        assert envs[0]["id"] == pp.MOCK_ENV_ID
        assert responses.calls[0].request.headers["Authorization"] == f"Bearer {token}"
        assert factory.call_args.kwargs["authority"] == "https://login.microsoftonline.com/organizations"
        app.acquire_token_interactive.assert_called_once_with([_BAP_SCOPE], prompt="select_account")

    @responses.activate
    def test_picker_does_not_authenticate_powerapps_or_flow(
        self, isolated_msal, tmp_path, monkeypatch,
    ):
        from flightcheck import environment_picker

        local = tmp_path / ".local"
        local.mkdir()
        (local / "config.json").write_text(
            json.dumps({"dataverseEndpoint": "https://orgmocktenant.crm.dynamics.com"}),
            encoding="utf-8",
        )
        monkeypatch.setattr(environment_picker, "discover_tenant", lambda _: _TENANT)
        monkeypatch.setattr(environment_picker, "display_environment_menu", lambda _: 0)
        run = Mock()
        monkeypatch.setattr(environment_picker, "run_flightcheck_for_environment", run)
        monkeypatch.setattr("sys.argv", ["environment_picker.py"])
        responses.add(**pp.list_environments(environments=[pp.environment()]))
        environment_picker.main()
        run.assert_called_once()
        isolated_msal[0].acquire_token_interactive.assert_called_once_with(
            [_BAP_SCOPE], prompt="select_account",
        )

    @pytest.mark.parametrize("mode", ["checkpoint", "profile"])
    @responses.activate
    def test_environment_checkpoint_and_profile_need_only_bap(
        self, isolated_msal, monkeypatch, mode,
    ):
        from flightcheck import cli, registry

        monkeypatch.setattr("auth.discover_tenant", lambda _: _TENANT)
        monkeypatch.setattr("auth.authenticate", Mock(side_effect=AssertionError("No Dataverse sign-in")))
        monkeypatch.setitem(
            registry.PROFILES, "bap-auth-test",
            registry.ProfileSpec("bap-auth-test", ("ENV-001",), "BAP auth regression"),
        )
        save = Mock()
        monkeypatch.setattr(cli, "save_results", save)
        monkeypatch.setattr(cli, "_print_prioritized_summary", lambda *a, **kw: None)
        monkeypatch.setattr("sys.argv", [
            "cli.py", f"--{mode}", "ENV-001" if mode == "checkpoint" else "bap-auth-test",
            "--environment-url", "https://orgmocktenant.crm.dynamics.com",
            "--validation-realm", "dev", "--no-telemetry", "--no-open",
        ])
        responses.add(**pp.list_environments(environments=[pp.environment()]))
        responses.add("GET", f"{_BAP_PATH}/environments/{pp.MOCK_ENV_ID}", json=pp.environment())
        responses.add("GET", f"{_BAP_PATH}/apiPolicies", json=pp.collection([]))
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 0
        result = save.call_args.args[0]
        assert result.results[0].checkpoint_id == "ENV-001"
        assert result.results[0].status == "Passed"
        assert "Environment: Mock Environment" in result.results[0].result
        isolated_msal[0].acquire_token_interactive.assert_called_once_with(
            [_BAP_SCOPE], prompt="select_account",
        )
        assert all(c.request.headers["Authorization"] == "Bearer bap-token" for c in responses.calls)
