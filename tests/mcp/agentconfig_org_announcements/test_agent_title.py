# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Offline title resolution through the selected bot's Dataverse manifest."""

from __future__ import annotations

import asyncio
import base64
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
import msal
import requests
from mcp.server.fastmcp.exceptions import ToolError
from portalocker.exceptions import LockException


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _mcp_modules import load_org_announcements_modules  # noqa: E402


MODULES = load_org_announcements_modules()
agent_title = MODULES["agent_title"]
server = MODULES["server"]

import base_client  # noqa: E402

TENANT_ID = "11111111-2222-3333-4444-555555555555"
OBJECT_ID = "00000000-0000-0000-0000-000000003333"
BOT_ID = "aaaaaaaa-0000-4000-8000-000000004444"
OTHER_BOT_ID = "bbbbbbbb-0000-4000-8000-000000005555"
TITLE_ID = "T_00000000-0000-0000-0000-000000006666"
DATAVERSE_URL = "https://orgmocktenant.crm.dynamics.com"
OTHER_DATAVERSE_URL = "https://orgother.crm.dynamics.com"
SCOPE = f"{DATAVERSE_URL}/user_impersonation"
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
        "agent": {
            "botId": OTHER_BOT_ID, "slug": "other", "titleId": "other-title",
            "dataverseEndpoint": OTHER_DATAVERSE_URL,
        },
        "agents": [
            {"botId": OTHER_BOT_ID, "slug": "other", "name": "Same name",
             "titleId": "other-title", "dataverseEndpoint": OTHER_DATAVERSE_URL},
            {"botId": BOT_ID, "slug": "selected", "name": "Same name",
             "dataverseEndpoint": DATAVERSE_URL},
        ],
        "dataverseEndpoint": OTHER_DATAVERSE_URL,
        "unrelated": {"preserved": True},
    }

    def write(payload=None):
        path.write_text(
            json.dumps(value if payload is None else payload), encoding="utf-8"
        )
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
def api(monkeypatch):
    """Exercise auth.dataverse_get through a closed, GET-only transport.

    The readable column is documented at:
    https://learn.microsoft.com/power-apps/developer/data-platform/reference/
    entities/bot#applicationmanifestinformation
    Its JSON microsoft365.titleId path was verified with a read-only bot lookup.
    """
    state = SimpleNamespace(
        endpoint=DATAVERSE_URL,
        calls=[],
        payload={
            "botid": BOT_ID,
            "applicationmanifestinformation": json.dumps({
                "microsoft365": {"titleId": TITLE_ID},
            }),
            "unselectedPrivateField": PRIVATE,
        },
        raw=None,
        status=200,
        error=None,
    )

    class Session:
        def get(self, url, *, params, headers, timeout, verify):
            state.calls.append({"method": "GET", "url": url, "params": params})
            assert url == f"{state.endpoint}/api/data/v9.2/bots({BOT_ID})"
            assert params == {"$select": "botid,applicationmanifestinformation"}
            assert headers["Authorization"] == f"Bearer {_jwt()}"
            assert headers["OData-Version"] == "4.0"
            assert timeout > 0
            assert verify is True
            if state.error is not None:
                raise state.error
            response = requests.Response()
            response.status_code = state.status
            response.headers["x-ms-request-id"] = PRIVATE
            response.request = requests.Request("GET", url).prepare()
            payload = (
                {"error": {"code": PRIVATE, "message": PRIVATE}}
                if state.status != 200 else state.payload
            )
            response._content = (
                state.raw if state.raw is not None else json.dumps(payload).encode()
            )
            return response

    import auth

    monkeypatch.setattr(auth, "_SESSION", Session())
    return state


@pytest.fixture
def msal_auth(monkeypatch, api):
    calls = []
    cache = object()
    account = {"home_account_id": "selected-account"}

    class App:
        def __init__(self, client_id, *, authority, token_cache):
            assert client_id == base_client._CLIENT_ID
            assert authority == f"https://login.microsoftonline.com/{TENANT_ID}"
            assert token_cache is cache

        def acquire_token_silent(self, scopes, *, account):
            calls.append(("silent", scopes, account))
            return {"access_token": _jwt()}

        def acquire_token_interactive(self, scopes, *, prompt, timeout):
            calls.append(("interactive", scopes, prompt, timeout))
            return {"access_token": _jwt()}

    def matching_account(app, tenant_id, object_id):
        assert (tenant_id, object_id) == (TENANT_ID, OBJECT_ID)
        return account

    def shared_cache(path):
        assert Path(path) == Path(base_client._TOKEN_CACHE_PATH)
        return cache

    monkeypatch.setattr(msal, "PublicClientApplication", App)
    monkeypatch.setattr(base_client, "create_token_cache", shared_cache)
    monkeypatch.setattr(agent_title, "account_for_identity", matching_account)
    return App, calls, account


def _call(bot_id=BOT_ID):
    async def run():
        return await server.mcp.call_tool("resolve_agent_title_id", {"botId": bot_id})

    result = asyncio.run(run())
    return result[1] if isinstance(result, tuple) else result.structuredContent


def test_dataverse_auth_uses_the_shared_authoring_msal_factory():
    assert agent_title._create_msal_app is base_client._create_msal_app


def test_mcp_reads_exact_non_active_bot_without_name_search_or_writes(
    config, authoring_identity, msal_auth, api, capsys
) -> None:
    value, write = config
    path = write()
    original = path.read_bytes()

    assert _call(BOT_ID.upper()) == {"botId": BOT_ID, "titleId": TITLE_ID}

    assert TITLE_ID != f"T_{BOT_ID}"
    assert value["agent"]["titleId"] == "other-title"
    assert path.read_bytes() == original
    assert len(api.calls) == 1
    assert api.calls[0]["method"] == "GET"
    assert msal_auth[1] == [("silent", [SCOPE], msal_auth[2])]
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("endpoint", [
    DATAVERSE_URL + "/", "https://orgmocktenant.api.crm.dynamics.com/",
])
def test_url_only_setup_uses_the_configured_endpoint_without_environment_inventory(
    config, authoring_identity, msal_auth, api, endpoint
):
    value, write = config
    value["agents"][1].pop("dataverseEndpoint")
    value["agent"] = dict(value["agents"][1])
    value["activeAgent"] = "selected"
    value["dataverseEndpoint"] = endpoint
    write()
    api.endpoint = endpoint.rstrip("/")

    assert _call() == {"botId": BOT_ID, "titleId": TITLE_ID}
    assert len(api.calls) == 1
    assert msal_auth[1][0][1] == [f"{api.endpoint}/user_impersonation"]


def test_selected_agent_endpoint_takes_precedence_over_the_active_environment(
    config, authoring_identity, msal_auth, api
):
    value, write = config
    value["dataverseEndpoint"] = OTHER_DATAVERSE_URL
    value["agents"][1]["dataverseEndpoint"] = DATAVERSE_URL
    write()

    assert agent_title.load_configured_target(BOT_ID).dataverse_endpoint == DATAVERSE_URL
    assert _call()["titleId"] == TITLE_ID
    assert msal_auth[1][0][1] == [SCOPE]


@pytest.mark.parametrize(
    ("field", "value"),
    [("environmentId", "separate-environment"),
     ("powerPlatformApiEndpoint", "https://separate-environment.example")],
)
def test_separate_environment_without_its_own_dataverse_endpoint_cannot_inherit(
    config, monkeypatch, field, value
):
    cfg, write = config
    cfg["agents"][1].pop("dataverseEndpoint")
    cfg["agents"][1][field] = value
    cfg["agent"] = dict(cfg["agents"][1])
    cfg["activeAgent"] = "selected"
    write()
    monkeypatch.setattr(server, "get_client", lambda: pytest.fail("Must not authenticate"))

    with pytest.raises(ToolError, match="no configured Dataverse endpoint"):
        _call()


def test_legacy_active_agent_only_config_is_supported(config):
    value, write = config
    value["agent"] = value.pop("agents")[1]
    value["agent"].pop("dataverseEndpoint")
    value["activeAgent"] = "selected"
    value["dataverseEndpoint"] = DATAVERSE_URL
    write()

    target = agent_title.load_configured_target(BOT_ID)
    assert target.bot_id == BOT_ID
    assert target.dataverse_endpoint == DATAVERSE_URL


def test_non_active_legacy_agent_cannot_use_the_active_agents_workspace_endpoint(
    config, monkeypatch
):
    value, write = config
    value["agents"][1].pop("dataverseEndpoint")
    write()
    monkeypatch.setattr(server, "get_client", lambda: pytest.fail("Must not authenticate"))

    with pytest.raises(ToolError, match="no recorded Dataverse endpoint.*ambiguous"):
        _call()


@pytest.mark.parametrize("variant", ["slug-only", "single-agent"])
def test_unambiguous_legacy_active_binding_can_use_workspace_endpoint(config, variant):
    value, write = config
    value["agents"][1].pop("dataverseEndpoint")
    value.pop("agent")
    value["dataverseEndpoint"] = DATAVERSE_URL
    if variant == "slug-only":
        value["activeAgent"] = "selected"
    else:
        value.pop("activeAgent")
        value["agents"] = [value["agents"][1]]
    write()

    assert agent_title.load_configured_target(BOT_ID).dataverse_endpoint == DATAVERSE_URL


def test_conflicting_legacy_active_markers_are_not_a_binding(config):
    value, write = config
    value["agents"][1].pop("dataverseEndpoint")
    value["agent"] = dict(value["agents"][1])
    write()

    with pytest.raises(agent_title.AgentTitleResolutionError, match="ambiguous"):
        agent_title.load_configured_target(BOT_ID)


def test_non_active_agent_resolves_its_original_environment_after_consecutive_setup(
    tmp_path, monkeypatch, authoring_identity, msal_auth, api
):
    from tests.scripts.test_setup_preserves_title_id import setup as maker_setup

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(agent_title, "CONFIG_PATH", tmp_path / ".local" / "config.json")
    for bot_id, name, slug, endpoint in [
        (BOT_ID, "Agent A", "selected", DATAVERSE_URL),
        (OTHER_BOT_ID, "Agent B", "other", OTHER_DATAVERSE_URL),
    ]:
        maker_setup.write_config(
            {"botId": bot_id, "name": name, "schema": "mock_schema",
             "managed": True, "url": endpoint},
            slug, f"workspace/agents/{slug}", False,
        )
    config = json.loads(agent_title.CONFIG_PATH.read_text(encoding="utf-8"))
    entries = {entry["botId"]: entry for entry in config["agents"]}
    assert entries[BOT_ID]["dataverseEndpoint"] == DATAVERSE_URL
    assert entries[OTHER_BOT_ID]["dataverseEndpoint"] == OTHER_DATAVERSE_URL
    assert config["agent"]["botId"] == OTHER_BOT_ID
    assert config["dataverseEndpoint"] == OTHER_DATAVERSE_URL

    assert _call() == {"botId": BOT_ID, "titleId": TITLE_ID}
    assert len(api.calls) == 1
    assert api.calls[0]["url"].startswith(DATAVERSE_URL)
    assert msal_auth[1][0][1] == [SCOPE]


@pytest.mark.parametrize("endpoint", [
    "", "http://private.example", "https://user:password@private.example",
    DATAVERSE_URL + "/api/data/v9.2", DATAVERSE_URL + "?private=value",
    DATAVERSE_URL + "#private", {"private": PRIVATE}, 123,
])
def test_invalid_endpoints_fail_before_any_auth(config, monkeypatch, endpoint):
    value, write = config
    value["agents"][1]["dataverseEndpoint"] = endpoint
    write()
    monkeypatch.setattr(server, "get_client", lambda: pytest.fail("Must not authenticate"))

    with pytest.raises(ToolError, match="dataverseEndpoint.*HTTPS origin") as caught:
        _call()

    assert PRIVATE not in str(caught.value)


@pytest.mark.parametrize("bot_id", [
    "unconfigured", OTHER_DATAVERSE_URL, "../../other", OTHER_BOT_ID.replace("bbbb", "cccc"),
])
def test_unknown_or_invalid_bot_ids_fail_before_auth(config, monkeypatch, bot_id):
    monkeypatch.setattr(server, "get_client", lambda: pytest.fail("Must not authenticate"))

    with pytest.raises(ToolError, match="botId"):
        _call(bot_id)


@pytest.mark.parametrize(
    "variant",
    ["missing", "malformed", "incomplete", "ambiguous", "not-an-object", "bad-agents",
     "missing-endpoint"],
)
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
    elif variant == "ambiguous":
        value["agents"].append(dict(value["agents"][1]))
        write()
    elif variant == "not-an-object":
        write([])
    elif variant == "bad-agents":
        value["agents"] = [None]
        write()
    else:
        value["agents"][1].pop("dataverseEndpoint")
        value.pop("dataverseEndpoint")
        write()

    with pytest.raises(ToolError, match="setup|configured agent|Dataverse endpoint"):
        _call()


@pytest.mark.parametrize("raw_manifest", [
    None, "", " ", "{}", '{"microsoft365":null}', '{"microsoft365":{}}',
    '{"microsoft365":{"titleId":null}}', '{"microsoft365":{"titleId":""}}',
    '{"microsoft365":{"titleId":" "}}',
    '{"teams":{"titleId":"not-microsoft365"},"microsoft365":{"appId":"not-a-title",'
    '"shareLink":"https://m365.cloud.microsoft/chat/?titleId=not-the-title"}}',
])
def test_missing_title_is_an_explicit_registration_error_without_synthesis(
    config, authoring_identity, msal_auth, api, raw_manifest
):
    api.payload["applicationmanifestinformation"] = raw_manifest

    with pytest.raises(ToolError, match="RegistrationRequired:") as caught:
        _call()

    assert "no Microsoft 365 registration titleId" in str(caught.value)
    assert PRIVATE not in str(caught.value)
    assert len(api.calls) == 1


@pytest.mark.parametrize("raw_manifest", [
    [], {}, 12, "not-json", "null", '"not-an-object"', "[]",
    '{"microsoft365":[]}', '{"microsoft365":"invalid"}',
])
def test_malformed_manifest_is_a_service_error_not_missing_registration(
    config, authoring_identity, msal_auth, api, raw_manifest
):
    api.payload["applicationmanifestinformation"] = raw_manifest

    with pytest.raises(ToolError, match="ServiceError:.*malformed application manifest"):
        _call()


@pytest.mark.parametrize("title_id", [
    False, 123, [], {}, "private\ntitle", " title ", "x" * 257,
])
def test_invalid_title_is_a_service_error(
    config, authoring_identity, msal_auth, api, title_id
):
    api.payload["applicationmanifestinformation"] = json.dumps({
        "microsoft365": {"titleId": title_id},
    })

    with pytest.raises(ToolError, match="ServiceError:.*invalid Microsoft 365 titleId"):
        _call()


@pytest.mark.parametrize("returned_id", [OTHER_BOT_ID, None, "not-a-guid"])
def test_metadata_must_identify_the_selected_bot(
    config, authoring_identity, msal_auth, api, returned_id
):
    api.payload["botid"] = returned_id

    with pytest.raises(ToolError, match="did not identify the selected configured bot"):
        _call()


@pytest.mark.parametrize("payload", [[], {}, None])
def test_invalid_record_responses_are_explicit_service_errors(
    config, authoring_identity, msal_auth, api, payload
):
    api.payload = payload

    with pytest.raises(ToolError, match="ServiceError:"):
        _call()


@pytest.mark.parametrize(
    ("status", "message"),
    [(401, "sign-in"), (403, "not authorized"), (404, "not found"),
     (429, "could not resolve"), (500, "could not resolve")],
)
def test_http_failures_are_sanitized_errors_without_discovery_fallback(
    config, authoring_identity, msal_auth, api, caplog, status, message
):
    api.status = status

    with pytest.raises(ToolError, match=message) as caught:
        _call()

    assert f"HTTP {status}" in str(caught.value)
    assert PRIVATE not in str(caught.value)
    assert PRIVATE not in caplog.text
    assert len(api.calls) == 1


@pytest.mark.parametrize("error_type", [requests.ConnectionError, requests.Timeout])
def test_network_failure_is_not_empty_discovery(
    config, authoring_identity, msal_auth, api, caplog, error_type
):
    api.error = error_type(PRIVATE)

    with pytest.raises(ToolError, match="NetworkError:.*temporarily unavailable") as caught:
        _call()

    assert PRIVATE not in str(caught.value)
    assert PRIVATE not in caplog.text
    assert len(api.calls) == 1


def test_non_json_http_success_is_not_reported_as_network_failure(
    config, authoring_identity, msal_auth, api, caplog
):
    api.raw = f"<html>{PRIVATE}</html>".encode()

    with pytest.raises(ToolError, match="ServiceError:.*invalid discovery response") as caught:
        _call()

    assert PRIVATE not in str(caught.value)
    assert PRIVATE not in caplog.text


@pytest.mark.parametrize("claims", [
    {"tenant_id": OTHER_BOT_ID}, {"object_id": OTHER_BOT_ID}, {"object_id": None},
])
def test_dataverse_token_must_match_the_authoring_tenant_and_account(
    msal_auth, monkeypatch, claims
):
    App, _, _ = msal_auth
    monkeypatch.setattr(
        App, "acquire_token_silent",
        lambda *args, **kwargs: {"access_token": _jwt(**claims)},
    )

    with pytest.raises(agent_title.AgentTitleResolutionError, match="different tenant/account"):
        agent_title.acquire_dataverse_token(DATAVERSE_URL, TENANT_ID, OBJECT_ID)


def test_missing_authoring_object_id_cannot_start_unbound_sign_in(monkeypatch):
    monkeypatch.setattr(
        agent_title, "_create_msal_app",
        lambda *args, **kwargs: pytest.fail("Must not open unbound sign-in"),
    )

    with pytest.raises(agent_title.AgentTitleResolutionError, match="cannot be identified"):
        agent_title.acquire_dataverse_token(DATAVERSE_URL, TENANT_ID, None)


def test_silent_miss_uses_interactive_sign_in_without_stdout(msal_auth, monkeypatch, capsys):
    App, calls, _ = msal_auth
    monkeypatch.setattr(App, "acquire_token_silent", lambda *args, **kwargs: None)

    assert agent_title.acquire_dataverse_token(
        DATAVERSE_URL, TENANT_ID, OBJECT_ID
    ) == _jwt()
    assert calls == [("interactive", [SCOPE], "select_account", 300)]
    assert capsys.readouterr().out == ""


def test_interactive_sign_in_cannot_switch_authoring_account(msal_auth, monkeypatch):
    App, _, _ = msal_auth
    monkeypatch.setattr(App, "acquire_token_silent", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        App, "acquire_token_interactive",
        lambda *args, **kwargs: {"access_token": _jwt(object_id=OTHER_BOT_ID)},
    )

    with pytest.raises(agent_title.AgentTitleResolutionError, match="different tenant/account"):
        agent_title.acquire_dataverse_token(DATAVERSE_URL, TENANT_ID, OBJECT_ID)


def test_interactive_timeout_is_a_sanitized_authentication_failure(
    config, authoring_identity, msal_auth, api, monkeypatch, caplog, capsys
):
    App, _, _ = msal_auth
    monkeypatch.setattr(App, "acquire_token_silent", lambda *args, **kwargs: None)

    def timeout(self, scopes, *, prompt, timeout):
        assert timeout == 300
        raise RuntimeError(f"Timeout. No auth response arrived. {PRIVATE}")

    monkeypatch.setattr(App, "acquire_token_interactive", timeout)

    with pytest.raises(ToolError, match="AuthenticationRequired:") as caught:
        _call()

    assert "sign-in did not complete" in str(caught.value)
    assert "300 seconds" in str(caught.value)
    assert PRIVATE not in str(caught.value)
    assert PRIVATE not in caplog.text
    assert capsys.readouterr().out == ""
    assert api.calls == []
    assert server._title_resolution_task is None


def test_cancelled_sign_in_cannot_accumulate_workers_or_independent_retries(
    config, authoring_identity, msal_auth, api, monkeypatch, caplog
):
    App, _, _ = msal_auth
    monkeypatch.setattr(App, "acquire_token_silent", lambda *args, **kwargs: None)

    async def run():
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
        unhandled = []
        loop.set_exception_handler(lambda loop, context: unhandled.append(context))
        started = asyncio.Event()
        expire_sign_in = threading.Event()
        interactive_calls = []

        def interactive(self, scopes, *, prompt, timeout):
            interactive_calls.append(timeout)
            if len(interactive_calls) == 1:
                loop.call_soon_threadsafe(started.set)
                assert timeout == 300
                # Advance the fake SDK's timeout only after checking cancelled retries.
                assert expire_sign_in.wait(5), "Test did not release the fake sign-in"
                raise RuntimeError(f"Timeout. No auth response arrived. {PRIVATE}")
            return {"access_token": _jwt()}

        monkeypatch.setattr(App, "acquire_token_interactive", interactive)
        first = asyncio.create_task(server.resolve_agent_title_id(BOT_ID))
        try:
            await asyncio.wait_for(started.wait(), timeout=2)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            assert server._title_resolution_task is not None
            assert not server._title_resolution_task.done()

            for bot_id in (BOT_ID, BOT_ID.upper(), OTHER_BOT_ID):
                with pytest.raises(ToolError, match="already in progress"):
                    await asyncio.wait_for(
                        server.resolve_agent_title_id(bot_id), timeout=1
                    )
            assert interactive_calls == [300]

            probe = asyncio.create_task(asyncio.to_thread(lambda: "worker available"))
            await asyncio.sleep(0)
            expire_sign_in.set()
            assert await asyncio.wait_for(probe, timeout=2) == "worker available"
            await asyncio.sleep(0)
            assert server._title_resolution_task is None
            assert unhandled == []

            result = await asyncio.wait_for(
                server.resolve_agent_title_id(BOT_ID), timeout=2
            )
            assert result == {"botId": BOT_ID, "titleId": TITLE_ID}
            assert interactive_calls == [300, 300]
            assert len(api.calls) == 1
        finally:
            expire_sign_in.set()

    asyncio.run(run())
    assert PRIVATE not in caplog.text


def test_cancelled_lookup_cannot_start_another_lookup_before_its_worker_finishes(
    config, authoring_identity, monkeypatch
):
    async def run():
        loop = asyncio.get_running_loop()
        started = asyncio.Event()
        finish = threading.Event()
        calls = []

        def resolve(target, tenant_id, object_id):
            calls.append(target.bot_id)
            loop.call_soon_threadsafe(started.set)
            assert finish.wait(5), "Test did not release the fake lookup"
            return {"botId": target.bot_id, "titleId": TITLE_ID}

        monkeypatch.setattr(server, "resolve_configured_agent_title", resolve)
        first = asyncio.create_task(server.resolve_agent_title_id(BOT_ID))
        try:
            await asyncio.wait_for(started.wait(), timeout=2)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            pending = server._title_resolution_task
            assert pending is not None
            assert not pending.cancelled()
            with pytest.raises(ToolError, match="already in progress"):
                await server.resolve_agent_title_id(OTHER_BOT_ID)
            assert calls == [BOT_ID]
            finish.set()
            assert await asyncio.wait_for(asyncio.shield(pending), timeout=2) == {
                "botId": BOT_ID, "titleId": TITLE_ID,
            }
            await asyncio.sleep(0)
            assert server._title_resolution_task is None
        finally:
            finish.set()

    asyncio.run(run())


def test_auth_errors_do_not_expose_provider_details(msal_auth, monkeypatch):
    App, _, _ = msal_auth
    failure = {"error": PRIVATE, "error_description": PRIVATE}
    monkeypatch.setattr(App, "acquire_token_silent", lambda *args, **kwargs: failure)
    monkeypatch.setattr(App, "acquire_token_interactive", lambda *args, **kwargs: failure)

    with pytest.raises(agent_title.AgentTitleResolutionError, match="sign-in failed") as caught:
        agent_title.acquire_dataverse_token(DATAVERSE_URL, TENANT_ID, OBJECT_ID)

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
        agent_title.acquire_dataverse_token(DATAVERSE_URL, TENANT_ID, OBJECT_ID)

    assert caught.value.code == "AuthenticationRequired"
    assert PRIVATE not in str(caught.value)
    assert PRIVATE not in caplog.text


def test_blocking_dataverse_lookup_runs_off_the_mcp_event_loop(
    config, authoring_identity, monkeypatch
):
    caller_thread = threading.get_ident()

    def resolve(target, tenant_id, object_id):
        assert threading.get_ident() != caller_thread
        assert (target.bot_id, tenant_id, object_id) == (BOT_ID, TENANT_ID, OBJECT_ID)
        return {"botId": BOT_ID, "titleId": TITLE_ID}

    monkeypatch.setattr(server, "resolve_configured_agent_title", resolve)

    assert _call()["titleId"] == TITLE_ID
