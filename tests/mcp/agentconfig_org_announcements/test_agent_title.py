# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Offline announcement title resolution through the selected bot's components."""

from __future__ import annotations

import asyncio
import base64
import copy
import json
import sys
import threading
from json import dumps
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
import yaml
from mcp.server.fastmcp.exceptions import ToolError
from portalocker.exceptions import LockException


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _mcp_modules import load_org_announcements_modules  # noqa: E402


MODULES = load_org_announcements_modules()
agent_title = MODULES["agent_title"]
server = MODULES["server"]
TENANT_ID = "11111111-2222-3333-4444-555555555555"
OBJECT_ID = "00000000-0000-0000-0000-000000003333"
BOT_ID = "00000000-0000-0000-0000-000000004444"
OTHER_BOT_ID = "00000000-0000-0000-0000-000000005555"
ENVIRONMENT_ID = "00000000-0000-4000-8000-000000001111"
OTHER_ENVIRONMENT_ID = "00000000-0000-4000-8000-000000002222"
HOST = "https://0000000000004000800000000000111.1.environment.api.test.powerplatform.com"
COMPONENTS_URL = f"{HOST}/copilotstudio/minimalBots/api/{BOT_ID}/components"
PRIVATE = "PRIVATE_RESPONSE_OR_AUTH_DETAIL"


def _jwt(tenant_id=TENANT_ID, object_id=OBJECT_ID) -> str:
    encoded = base64.urlsafe_b64encode(
        json.dumps({"tid": tenant_id, "oid": object_id}).encode()
    ).decode().rstrip("=")
    return f"header.{encoded}.signature"


@pytest.fixture
def config(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    monkeypatch.setattr(agent_title, "CONFIG_PATH", path)
    value = {
        "setup": "complete",
        "configVersion": 1,
        "activeAgent": "other",
        "agent": {"botId": OTHER_BOT_ID, "slug": "other", "titleId": "other-title"},
        "agents": [
            {"botId": OTHER_BOT_ID, "slug": "other", "name": "Same name",
             "titleId": "other-title"},
            {"botId": BOT_ID, "slug": "selected", "name": "Same name"},
        ],
        "environmentId": ENVIRONMENT_ID,
        "powerPlatformApiEndpoint": HOST,
        "ring": "test",
        "unrelated": {"preserved": True},
    }

    def write(payload=None):
        path.write_text(json.dumps(value if payload is None else payload), encoding="utf-8")
        return path

    write()
    return value, write


@pytest.fixture
def authoring_identity(monkeypatch):
    class AuthoringClient:
        tenant_id = TENANT_ID
        object_id = OBJECT_ID

    client = AuthoringClient()

    async def get_client():
        return client

    monkeypatch.setattr(server, "get_client", get_client)
    return client


@pytest.fixture
def components():
    # Recorded BotEntity shape; the response's title is deliberately not BOT_ID.
    cassette = REPO_ROOT / "tests/fixtures/cassettes/island_gateway_botcomponents.yaml"
    record = next(
        entry
        for entry in yaml.safe_load(cassette.read_text(encoding="utf-8"))["interactions"]
        if entry["request"]["uri"].endswith("/content/botcomponents")
    )
    body = json.loads(record["response"]["body"]["string"])
    bot = body["bot"]
    return {
        "bot": {
            "cdsBotId": BOT_ID,
            "teamsAppInformation": copy.deepcopy(bot["teamsAppInformation"]),
            "description": PRIVATE,
        },
        "botComponentChanges": [{"privateContent": PRIVATE}],
    }


@pytest.fixture
def api(monkeypatch):
    """A closed request transport; it cannot bypass the MCP network guard."""
    state = SimpleNamespace(
        calls=[], components=None, environments=None, status=200, error=None, closed=0
    )

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            state.closed += 1

        def mount(self, *args):
            pass

        def request(self, method, url, *, params, headers, timeout, json=None):
            state.calls.append({"method": method, "url": url, "params": params})
            assert timeout > 0
            if state.error is not None:
                raise state.error
            if method == "POST":
                assert url == COMPONENTS_URL
                assert params == {"api-version": "2022-03-01-preview"}
                assert json == {}
                assert state.components is not None or state.status != 200
                payload = state.components
            else:
                assert method == "GET"
                assert url == (
                    "https://api.test.powerplatform.com/environmentmanagement/environments"
                )
                assert params == {"api-version": "2024-10-01"}
                assert state.environments is not None
                payload = {"value": state.environments}
            response = requests.Response()
            response.status_code = state.status
            response.headers["x-ms-request-id"] = PRIVATE
            if state.status != 200:
                payload = {"error": {"code": PRIVATE}}
            response._content = dumps(payload).encode()
            return response

    monkeypatch.setattr(agent_title.requests, "Session", Session)
    return state


@pytest.fixture
def msal_auth(monkeypatch, api):
    calls = []
    cache = object()
    account = {"home_account_id": "selected-account"}

    class App:
        def __init__(self, client_id, *, authority, token_cache):
            assert client_id == agent_title.CLIENT_ID
            assert authority == f"https://login.microsoftonline.com/{TENANT_ID}"
            assert token_cache is cache

        def acquire_token_silent(self, scopes, *, account):
            calls.append(("silent", scopes, account))
            return {"access_token": _jwt()}

        def acquire_token_interactive(self, scopes, *, prompt):
            calls.append(("interactive", scopes, prompt))
            return {"access_token": _jwt()}

    def matching_account(app, tenant_id, object_id):
        assert (tenant_id, object_id) == (TENANT_ID, OBJECT_ID)
        return account

    def shared_cache(path):
        assert Path(path) == agent_title.AGENTBUILDER_TOKEN_CACHE_PATH
        return cache

    monkeypatch.setattr(agent_title.msal, "PublicClientApplication", App)
    monkeypatch.setattr(agent_title, "create_token_cache", shared_cache)
    monkeypatch.setattr(agent_title, "account_for_identity", matching_account)
    monkeypatch.setattr(
        agent_title, "derive_environment_host",
        lambda environment_id, ring: (
            HOST if (environment_id, ring) == (ENVIRONMENT_ID, "test") else
            pytest.fail("Resolved a different environment or service ring")
        ),
    )
    return App, calls, account


def _call(bot_id=BOT_ID):
    async def run():
        return await server.mcp.call_tool("resolve_agent_title_id", {"botId": bot_id})

    result = asyncio.run(run())
    return result[1] if isinstance(result, tuple) else result.structuredContent


def _add_components(api, components):
    api.components = components


def test_mcp_resolves_exact_non_active_bot_without_name_search_or_writes(
    config, authoring_identity, components, msal_auth, api, capsys
) -> None:
    value, write = config
    path = write()
    original = path.read_bytes()
    _add_components(api, components)

    result = _call(BOT_ID.upper())

    assert result == {
        "botId": BOT_ID,
        "environmentId": ENVIRONMENT_ID,
        "titleId": components["bot"]["teamsAppInformation"]["microsoft365"]["titleId"],
    }
    assert result["titleId"] != f"T_{BOT_ID}"
    assert value["agent"]["titleId"] == "other-title"
    assert path.read_bytes() == original
    assert len(api.calls) == 1
    assert api.calls[0]["method"] == "POST"
    assert api.closed == 1
    assert PRIVATE not in json.dumps(result)
    assert capsys.readouterr().out == ""
    assert msal_auth[1] == [
        ("silent", ["https://api.test.powerplatform.com/CopilotStudio.MinimalBot.Read"],
         msal_auth[2]),
    ]


@pytest.mark.parametrize("domain_only", [False, True])
@pytest.mark.parametrize("api_host", [False, True])
def test_url_only_setup_resolves_the_exact_environment_before_components(
    config, authoring_identity, components, msal_auth, api, domain_only, api_host
) -> None:
    value, write = config
    value.pop("environmentId")
    value.pop("powerPlatformApiEndpoint")
    value["dataverseEndpoint"] = (
        "https://orgmocktenant.api.crm.dynamics.com/"
        if api_host else "https://orgmocktenant.crm.dynamics.com/"
    )
    path = write()
    before = path.read_bytes()
    environment = {
        "id": f"Default-{ENVIRONMENT_ID}", "tenantId": TENANT_ID,
        **(
            {"domainName": "orgmocktenant.crm.dynamics.com"}
            if domain_only else {"url": "https://orgmocktenant.crm.dynamics.com/"}
        ),
    }
    # EnvironmentResponse schema:
    # https://learn.microsoft.com/rest/api/power-platform/environmentmanagement/
    # environments/list-environments-for-user#environmentresponse
    api.environments = [
        {"id": OTHER_ENVIRONMENT_ID, "url": "https://other.crm.dynamics.com"},
        environment,
    ]
    _add_components(api, components)

    result = _call()

    assert result["environmentId"] == ENVIRONMENT_ID
    assert result["titleId"] == components["bot"]["teamsAppInformation"]["microsoft365"]["titleId"]
    assert [call["method"] for call in api.calls] == ["GET", "POST"]
    assert msal_auth[1][0][1] == ["https://api.test.powerplatform.com/.default"]
    assert msal_auth[1][1][1] == [
        "https://api.test.powerplatform.com/CopilotStudio.MinimalBot.Read"
    ]
    assert path.read_bytes() == before


def test_selected_agent_environment_does_not_inherit_the_active_agents_host(config):
    value, write = config
    value["environmentId"] = OTHER_ENVIRONMENT_ID
    value["powerPlatformApiEndpoint"] = (
        "https://000000000000400080000000000022.22.environment.api.powerplatform.com"
    )
    value["ring"] = "prod"
    value["agents"][1].update({
        "environmentId": ENVIRONMENT_ID,
        "powerPlatformApiEndpoint": HOST,
    })
    write()

    target = agent_title.load_configured_target(BOT_ID)

    assert (target.environment_id, target.host, target.ring) == (
        ENVIRONMENT_ID, HOST, "test"
    )


def test_legacy_active_agent_only_config_is_supported(config):
    value, write = config
    value["agent"] = value.pop("agents")[1]
    value["activeAgent"] = "selected"
    value["environmentId"] = f"Default-{ENVIRONMENT_ID}"
    write()

    assert agent_title.load_configured_target(BOT_ID).bot_id == BOT_ID
    assert agent_title.load_configured_target(BOT_ID).environment_id == ENVIRONMENT_ID


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("environmentId", OTHER_ENVIRONMENT_ID),
        ("powerPlatformApiEndpoint", HOST + ".attacker.example"),
        ("powerPlatformApiEndpoint", HOST + "/path"),
        ("powerPlatformApiEndpoint", "http://private.example"),
        ("powerPlatformApiEndpoint", {"private": PRIVATE}),
        ("ring", "prod"),
        ("ring", ["test"]),
        ("dataverseEndpoint", "http://private.example"),
    ],
)
def test_inconsistent_environment_settings_fail_before_any_auth(
    config, monkeypatch, field, invalid
):
    value, write = config
    value[field] = invalid
    write()
    monkeypatch.setattr(server, "get_client", lambda: pytest.fail("Must not authenticate"))

    with pytest.raises(ToolError, match="environment.*invalid|inconsistent") as caught:
        _call()

    assert PRIVATE not in str(caught.value)


@pytest.mark.parametrize("bot_id", ["unconfigured", OTHER_ENVIRONMENT_ID, "../../other"])
def test_resolver_rejects_unknown_or_invalid_bot_ids_before_auth(config, monkeypatch, bot_id):
    monkeypatch.setattr(server, "get_client", lambda: pytest.fail("Must not authenticate"))

    with pytest.raises(ToolError, match="botId"):
        _call(bot_id)


@pytest.mark.parametrize("variant", ["missing", "malformed", "incomplete", "ambiguous"])
def test_bad_or_ambiguous_config_is_an_explicit_error(config, variant):
    value, write = config
    path = write()
    if variant == "missing":
        path.unlink()
    elif variant == "malformed":
        path.write_text("{", encoding="utf-8")
    elif variant == "incomplete":
        value["setup"] = "pending"
        write()
    else:
        value["agents"].append(dict(value["agents"][1]))
        write()

    with pytest.raises(ToolError, match="setup|configured agent"):
        _call()


@pytest.mark.parametrize(
    "variant", ["missing", "ambiguous", "bad-id", "wrong-tenant", "bad-url", "bad-domain"]
)
def test_unresolved_environment_is_not_replaced_by_a_default_or_bot_id(
    config, authoring_identity, msal_auth, api, variant
):
    value, write = config
    value.pop("environmentId")
    value.pop("powerPlatformApiEndpoint")
    value["dataverseEndpoint"] = "https://orgmocktenant.crm.dynamics.com"
    write()
    environments = []
    if variant != "missing":
        environments = [{"id": ENVIRONMENT_ID, "url": value["dataverseEndpoint"]}]
    if variant == "ambiguous":
        environments.append({"id": OTHER_ENVIRONMENT_ID, "url": value["dataverseEndpoint"]})
    elif variant == "bad-id":
        environments[0]["id"] = PRIVATE
    elif variant == "wrong-tenant":
        environments[0]["tenantId"] = OTHER_ENVIRONMENT_ID
    elif variant == "bad-url":
        environments[0]["url"] = {"private": PRIVATE}
    elif variant == "bad-domain":
        environments[0].pop("url")
        environments[0]["domainName"] = [PRIVATE]
    api.environments = environments

    with pytest.raises(ToolError, match="environment|metadata") as caught:
        _call()

    assert len(api.calls) == 1
    assert PRIVATE not in str(caught.value)


@pytest.mark.parametrize(
    "metadata",
    [
        None,
        {},
        {"teams": {"appId": "teams-app"}, "microsoft365": {}},
        {"microsoft365": {"titleId": None, "appId": "m365-app"}},
        {"microsoft365": {"titleId": "", "shareLink": "https://private.example"}},
        {"microsoft365": {"titleId": " "}},
    ],
)
def test_missing_microsoft365_title_is_an_explicit_registration_error(
    config, authoring_identity, components, msal_auth, api, metadata
):
    components["bot"]["teamsAppInformation"] = metadata
    _add_components(api, components)

    with pytest.raises(ToolError, match="no Microsoft 365 registration titleId") as caught:
        _call()

    assert "RegistrationRequired" in str(caught.value)
    assert PRIVATE not in str(caught.value)
    assert len(api.calls) == 1


@pytest.mark.parametrize(
    "metadata",
    [
        [],
        {"microsoft365": "invalid"},
        {"microsoft365": {"titleId": ["title"]}},
        {"microsoft365": {"titleId": "private\ntitle"}},
        {"microsoft365": {"titleId": " title "}},
    ],
)
def test_malformed_registration_is_not_treated_as_no_agents(
    config, authoring_identity, components, msal_auth, api, metadata
):
    components["bot"]["teamsAppInformation"] = metadata
    _add_components(api, components)

    with pytest.raises(ToolError, match="malformed|invalid Microsoft 365"):
        _call()


@pytest.mark.parametrize("returned_id", [OTHER_BOT_ID, None, "not-a-guid"])
def test_components_must_identify_the_selected_bot(
    config, authoring_identity, components, msal_auth, api, returned_id
):
    components["bot"]["cdsBotId"] = returned_id
    _add_components(api, components)

    with pytest.raises(ToolError, match="did not identify the selected configured bot"):
        _call()


@pytest.mark.parametrize(
    ("status", "message"),
    [(401, "sign-in"), (403, "not authorized"), (404, "not found"),
     (429, "could not resolve"), (500, "could not resolve")],
)
@pytest.mark.parametrize("phase", ["components", "environments"])
def test_api_failures_are_explicit_sanitized_errors_without_search_fallback(
    config, authoring_identity, msal_auth, api, caplog, status, message, phase
):
    if phase == "environments":
        value, write = config
        value.pop("environmentId")
        value.pop("powerPlatformApiEndpoint")
        value["dataverseEndpoint"] = "https://orgmocktenant.crm.dynamics.com"
        write()
        api.environments = []
    api.status = status

    with pytest.raises(ToolError, match=message) as caught:
        _call()

    assert f"HTTP {status}" in str(caught.value)
    assert PRIVATE not in str(caught.value)
    assert PRIVATE not in caplog.text
    assert len(api.calls) == 1
    assert api.closed == 1


def test_network_failure_is_not_empty_discovery(
    config, authoring_identity, msal_auth, api, caplog
):
    api.error = requests.ConnectionError(PRIVATE)

    with pytest.raises(ToolError, match="temporarily unavailable") as caught:
        _call()

    assert PRIVATE not in str(caught.value)
    assert PRIVATE not in caplog.text
    assert len(api.calls) == 1


@pytest.mark.parametrize("payload", [[], {}, {"bot": None}])
def test_invalid_component_responses_are_explicit_service_errors(
    config, authoring_identity, msal_auth, api, payload
):
    api.components = payload

    with pytest.raises(ToolError, match="ServiceError:") as caught:
        _call()

    assert "titleId" in str(caught.value) or "selected configured bot" in str(caught.value)
    assert len(api.calls) == 1


@pytest.mark.parametrize("claims", [
    {"tenant_id": OTHER_ENVIRONMENT_ID}, {"object_id": OTHER_BOT_ID}, {"object_id": None},
])
def test_powerplatform_token_must_match_the_authoring_tenant_and_account(
    msal_auth, monkeypatch, claims
):
    App, _, _ = msal_auth
    monkeypatch.setattr(
        App, "acquire_token_silent",
        lambda *args, **kwargs: {"access_token": _jwt(**claims)},
    )

    with pytest.raises(agent_title.AgentTitleResolutionError, match="different tenant/account"):
        agent_title.acquire_agentbuilder_token(TENANT_ID, OBJECT_ID, ["read-scope"])


def test_missing_authoring_object_id_cannot_start_an_unbound_sign_in(monkeypatch):
    monkeypatch.setattr(
        agent_title.msal, "PublicClientApplication",
        lambda *args, **kwargs: pytest.fail("Must not open unbound sign-in"),
    )

    with pytest.raises(agent_title.AgentTitleResolutionError, match="cannot be identified"):
        agent_title.acquire_agentbuilder_token(TENANT_ID, None, ["read-scope"])


def test_silent_miss_uses_interactive_sign_in_without_stdout(msal_auth, monkeypatch, capsys):
    App, calls, _ = msal_auth
    monkeypatch.setattr(App, "acquire_token_silent", lambda *args, **kwargs: None)

    assert agent_title.acquire_agentbuilder_token(
        TENANT_ID, OBJECT_ID, ["read-scope"]
    ) == _jwt()
    assert calls == [("interactive", ["read-scope"], "select_account")]
    assert capsys.readouterr().out == ""


def test_auth_errors_do_not_expose_provider_details(msal_auth, monkeypatch):
    App, _, _ = msal_auth
    monkeypatch.setattr(
        App, "acquire_token_silent",
        lambda *args, **kwargs: {"error": PRIVATE, "error_description": PRIVATE},
    )
    monkeypatch.setattr(
        App, "acquire_token_interactive",
        lambda *args, **kwargs: {"error": PRIVATE, "error_description": PRIVATE},
    )

    with pytest.raises(agent_title.AgentTitleResolutionError, match="sign-in failed") as caught:
        agent_title.acquire_agentbuilder_token(TENANT_ID, OBJECT_ID, ["read-scope"])

    assert PRIVATE not in str(caught.value)


@pytest.mark.parametrize(
    "error", [ValueError(PRIVATE), OSError(PRIVATE), LockException(PRIVATE),
              requests.ConnectionError(PRIVATE)]
)
def test_auth_exceptions_are_safe_and_explicit(msal_auth, monkeypatch, error, caplog):
    App, _, _ = msal_auth

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(App, "acquire_token_silent", fail)

    with pytest.raises(agent_title.AgentTitleResolutionError, match="sign-in failed") as caught:
        agent_title.acquire_agentbuilder_token(TENANT_ID, OBJECT_ID, ["read-scope"])

    assert caught.value.code == "AuthenticationRequired"
    assert PRIVATE not in str(caught.value)
    assert PRIVATE not in caplog.text


def test_blocking_component_lookup_runs_off_the_mcp_event_loop(
    config, authoring_identity, monkeypatch
):
    caller_thread = threading.get_ident()

    def resolve(target, tenant_id, object_id):
        assert threading.get_ident() != caller_thread
        assert (target.bot_id, tenant_id, object_id) == (BOT_ID, TENANT_ID, OBJECT_ID)
        return {"botId": BOT_ID, "environmentId": ENVIRONMENT_ID, "titleId": "registered-title"}

    monkeypatch.setattr(server, "resolve_configured_agent_title", resolve)

    assert _call()["titleId"] == "registered-title"
