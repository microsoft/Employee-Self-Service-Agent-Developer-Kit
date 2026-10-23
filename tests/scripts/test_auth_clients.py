# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Offline regression tests for shared Dataverse/Flow client isolation."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
import socket
import time
from typing import Iterator
from unittest.mock import Mock, call
import webbrowser

import msal
import pytest
import responses

import auth
from tests.conftest import FAKE_DATAVERSE_URL, FAKE_TENANT_ID, require_validated_mock
from tests.mocks import dataverse as dv

require_validated_mock(dv)

DATAVERSE_CLIENT = "417219b4-3a7d-42a2-bdb1-972bd8281a02"
FLOW_CLIENT = "51f81489-12ee-4a9e-aaae-a2591f45987d"
DATAVERSE_SCOPE = f"{FAKE_DATAVERSE_URL}/user_impersonation"
FLOW_SCOPE = "https://service.flow.microsoft.com//user_impersonation"
AUTHORITY = f"https://login.microsoftonline.com/{FAKE_TENANT_ID}"
ACCOUNT = {
    "home_account_id": "mock-user.mock-tenant",
    "environment": "login.microsoftonline.com",
    "realm": FAKE_TENANT_ID,
    "username": "Maker@Example.com",
    "local_account_id": "mock-user",
    "authority_type": "MSSTS",
}
OTHER_ACCOUNT = {**ACCOUNT, "home_account_id": "other-user.mock-tenant",
                 "username": "other@example.com"}


@pytest.fixture(autouse=True)
def offline_auth(
    chdir_kit_root: Path,
    isolate_token_cache: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[responses.RequestsMock]:
    import adk_telemetry
    from flightcheck import graph_client

    def forbidden(*_args, **_kwargs):
        pytest.fail("Auth regression tests must not use real network or sign-in.")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(webbrowser, "open", forbidden)
    monkeypatch.setattr(graph_client, "resolve_tenant_display_name_silent", Mock(return_value=""))
    monkeypatch.setattr(adk_telemetry, "start_session", Mock())
    with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
        http.add(**dv.discover_tenant_challenge(
            base_url=FAKE_DATAVERSE_URL,
            tenant_id=FAKE_TENANT_ID,
            quoted=True,
            include_resource_id=True,
        ))
        yield http


@pytest.fixture
def msal_factory(monkeypatch: pytest.MonkeyPatch) -> Mock:
    app = Mock(spec=msal.PublicClientApplication)
    app.get_accounts.return_value = []
    app.acquire_token_silent.return_value = None
    app.acquire_token_interactive.return_value = {
        "access_token": "interactive-token",
        "id_token_claims": {"preferred_username": ACCOUNT["username"]},
    }
    factory = Mock(return_value=app)
    monkeypatch.setattr(auth.msal, "PublicClientApplication", factory)
    return factory


def assert_client(factory: Mock, expected_client: str) -> None:
    assert factory.call_count == 1
    assert factory.call_args.args == (expected_client,)
    assert factory.call_args.kwargs["authority"] == AUTHORITY
    assert isinstance(factory.call_args.kwargs["token_cache"], msal.SerializableTokenCache)


def test_legacy_client_id_import_keeps_its_value() -> None:
    from auth import CLIENT_ID, DATAVERSE_CLIENT_ID, FLOW_CLIENT_ID

    assert CLIENT_ID == FLOW_CLIENT_ID == FLOW_CLIENT
    assert DATAVERSE_CLIENT_ID == DATAVERSE_CLIENT
    assert auth.FLOW_API_SCOPE == FLOW_SCOPE


@pytest.mark.parametrize(
    ("accounts", "preferred", "options", "silent_account"),
    [
        ([], None, {"prompt": "select_account"}, None),
        ([], "maker@example.com", {"login_hint": "maker@example.com"}, None),
        ([OTHER_ACCOUNT], "maker@example.com", {"login_hint": "maker@example.com"}, None),
        ([ACCOUNT], "maker@example.com", {"login_hint": "maker@example.com"}, ACCOUNT),
    ],
)
def test_dataverse_interactive_preserves_account_hint_and_scope(
    msal_factory: Mock, accounts, preferred, options, silent_account
) -> None:
    app = msal_factory.return_value
    app.get_accounts.return_value = accounts

    assert auth.authenticate(
        FAKE_DATAVERSE_URL, preferred_username=preferred, return_account_identity=True,
    ) == ("interactive-token", ACCOUNT["username"])

    assert_client(msal_factory, DATAVERSE_CLIENT)
    app.acquire_token_interactive.assert_called_once_with([DATAVERSE_SCOPE], **options)
    if silent_account:
        app.acquire_token_silent.assert_called_once_with(
            [DATAVERSE_SCOPE], account=silent_account,
        )
    else:
        app.acquire_token_silent.assert_not_called()


@pytest.mark.parametrize("preferred", [None, "maker@example.com"])
def test_dataverse_silent_preserves_account_selection_and_validation(
    msal_factory: Mock, offline_auth: responses.RequestsMock, preferred: str | None,
) -> None:
    app = msal_factory.return_value
    app.get_accounts.return_value = [OTHER_ACCOUNT, ACCOUNT]
    app.acquire_token_silent.return_value = {"access_token": "cached-dataverse"}
    offline_auth.get(f"{FAKE_DATAVERSE_URL}/api/data/v9.2/WhoAmI", status=200)
    selected = ACCOUNT if preferred else OTHER_ACCOUNT

    assert auth.authenticate(
        FAKE_DATAVERSE_URL, preferred_username=preferred, return_account_identity=True,
    ) == ("cached-dataverse", selected["username"])

    assert_client(msal_factory, DATAVERSE_CLIENT)
    app.acquire_token_silent.assert_called_once_with([DATAVERSE_SCOPE], account=selected)
    app.acquire_token_interactive.assert_not_called()
    assert offline_auth.calls[-1].request.headers["Authorization"] == "Bearer cached-dataverse"


@pytest.mark.parametrize("preferred", [None, "maker@example.com"])
def test_dataverse_rejected_cache_rebuilds_owned_client(
    msal_factory: Mock, offline_auth: responses.RequestsMock, preferred: str | None,
) -> None:
    stale_app = msal_factory.return_value
    stale_app.get_accounts.return_value = [ACCOUNT]
    stale_app.acquire_token_silent.return_value = {"access_token": "rejected-token"}
    fresh_app = Mock()
    fresh_app.acquire_token_interactive.return_value = {"access_token": "fresh-token"}
    msal_factory.side_effect = [stale_app, fresh_app]
    offline_auth.get(f"{FAKE_DATAVERSE_URL}/api/data/v9.2/WhoAmI", status=401)

    assert auth.authenticate(FAKE_DATAVERSE_URL, preferred_username=preferred) == "fresh-token"

    cache = msal_factory.call_args_list[0].kwargs["token_cache"]
    assert msal_factory.call_args_list == [
        call(DATAVERSE_CLIENT, authority=AUTHORITY, token_cache=cache),
        call(DATAVERSE_CLIENT, authority=AUTHORITY, token_cache=cache),
    ]
    stale_app.remove_account.assert_called_once_with(ACCOUNT)
    stale_app.acquire_token_interactive.assert_not_called()
    options = {"login_hint": preferred} if preferred else {"prompt": "select_account"}
    fresh_app.acquire_token_interactive.assert_called_once_with([DATAVERSE_SCOPE], **options)


@pytest.mark.parametrize("account", [None, ACCOUNT])
def test_clear_cache_helper_constructs_dataverse_client(
    msal_factory: Mock, chdir_kit_root: Path, account,
) -> None:
    cache_path = chdir_kit_root / ".local" / ".token_cache.bin"
    cache_path.write_text(msal.SerializableTokenCache().serialize(), encoding="utf-8")
    msal_factory.return_value.get_accounts.return_value = [OTHER_ACCOUNT, ACCOUNT]

    auth.clear_token_cache(FAKE_DATAVERSE_URL, account=account)

    assert_client(msal_factory, DATAVERSE_CLIENT)
    msal_factory.return_value.remove_account.assert_called_once_with(account or OTHER_ACCOUNT)


def test_clear_cache_without_file_does_not_construct_client(msal_factory: Mock) -> None:
    auth.clear_token_cache(FAKE_DATAVERSE_URL)
    msal_factory.assert_not_called()


@pytest.mark.parametrize("silent", [False, True])
def test_flow_uses_original_client_scope_and_first_account(
    msal_factory: Mock, silent: bool,
) -> None:
    app = msal_factory.return_value
    app.get_accounts.return_value = [OTHER_ACCOUNT, ACCOUNT]
    if silent:
        app.acquire_token_silent.return_value = {"access_token": "cached-flow"}

    assert auth.get_flow_token(FAKE_DATAVERSE_URL) == (
        "cached-flow" if silent else "interactive-token"
    )

    assert_client(msal_factory, FLOW_CLIENT)
    app.acquire_token_silent.assert_called_once_with([FLOW_SCOPE], account=OTHER_ACCOUNT)
    if silent:
        app.acquire_token_interactive.assert_not_called()
    else:
        app.acquire_token_interactive.assert_called_once_with(
            [FLOW_SCOPE], prompt="select_account",
        )


@pytest.mark.parametrize("resource", ["dataverse", "flow"])
def test_authentication_errors_still_fail_without_echoing_details(
    msal_factory: Mock, capsys: pytest.CaptureFixture[str], resource: str,
) -> None:
    msal_factory.return_value.acquire_token_interactive.return_value = {
        "error": "access_denied", "error_description": "private-tenant-details",
    }
    acquire = auth.authenticate if resource == "dataverse" else auth.get_flow_token

    with pytest.raises(SystemExit, match="1"):
        acquire(FAKE_DATAVERSE_URL)

    assert_client(msal_factory, DATAVERSE_CLIENT if resource == "dataverse" else FLOW_CLIENT)
    output = capsys.readouterr().out
    assert "access_denied" in output
    assert "private-tenant-details" not in output


@pytest.mark.parametrize("resource", ["dataverse", "flow"])
@pytest.mark.parametrize("cached_state", ["valid", "missing", "expired"])
def test_msal_cache_never_returns_another_clients_access_token(
    monkeypatch: pytest.MonkeyPatch,
    chdir_kit_root: Path,
    offline_auth: responses.RequestsMock,
    resource: str,
    cached_state: str,
) -> None:
    """Exercise real MSAL cache filtering, mocking discovery and browser auth."""
    client, scope = (
        (DATAVERSE_CLIENT, DATAVERSE_SCOPE) if resource == "dataverse"
        else (FLOW_CLIENT, FLOW_SCOPE)
    )
    other_client = FLOW_CLIENT if resource == "dataverse" else DATAVERSE_CLIENT
    cache = msal.SerializableTokenCache()
    cache.modify(msal.TokenCache.CredentialType.ACCOUNT, ACCOUNT, ACCOUNT)
    now = int(time.time())

    def add_token(token_client: str, target: str, secret: str, expires: int) -> None:
        entry = {
            "credential_type": msal.TokenCache.CredentialType.ACCESS_TOKEN,
            "home_account_id": ACCOUNT["home_account_id"],
            "environment": ACCOUNT["environment"],
            "realm": FAKE_TENANT_ID,
            "client_id": token_client,
            "target": target,
            "secret": secret,
            "token_type": "Bearer",
            "cached_at": str(now - 3600),
            "expires_on": str(expires),
        }
        cache.modify(msal.TokenCache.CredentialType.ACCESS_TOKEN, entry, entry)

    add_token(other_client, scope, "wrong-client-token", now + 3600)
    add_token(
        other_client, FLOW_SCOPE if resource == "dataverse" else DATAVERSE_SCOPE,
        "other-resource-token", now + 3600,
    )
    if cached_state != "missing":
        add_token(client, scope, "correct-client-token",
                  now + 3600 if cached_state == "valid" else now - 3600)
    cache_path = chdir_kit_root / ".local" / ".token_cache.bin"
    serialized = cache.serialize()
    cache_path.write_text(serialized, encoding="utf-8")

    real_application = msal.PublicClientApplication
    transport = Mock()
    transport.get.return_value = Mock(status_code=200, headers={}, text=json.dumps({
        "authorization_endpoint": f"{AUTHORITY}/oauth2/v2.0/authorize",
        "token_endpoint": f"{AUTHORITY}/oauth2/v2.0/token",
    }))
    transport.post.side_effect = AssertionError("No refresh token or live HTTP is expected.")
    apps: list[msal.PublicClientApplication] = []

    def make_app(client_id: str, **kwargs):
        app = real_application(
            client_id, **kwargs, http_client=transport, instance_discovery=False,
        )
        monkeypatch.setattr(app, "acquire_token_interactive", Mock(
            return_value={"access_token": "interactive-token"},
        ))
        apps.append(app)
        return app

    factory = Mock(side_effect=make_app)
    monkeypatch.setattr(auth.msal, "PublicClientApplication", factory)
    offline_auth.get(f"{FAKE_DATAVERSE_URL}/api/data/v9.2/WhoAmI", status=200)
    acquire = auth.authenticate if resource == "dataverse" else auth.get_flow_token

    assert acquire(FAKE_DATAVERSE_URL) == (
        "correct-client-token" if cached_state == "valid" else "interactive-token"
    )

    assert_client(factory, client)
    if cached_state == "valid":
        apps[0].acquire_token_interactive.assert_not_called()
    else:
        apps[0].acquire_token_interactive.assert_called_once_with(
            [scope], prompt="select_account",
        )
    transport.post.assert_not_called()
    persisted = msal.SerializableTokenCache()
    persisted.deserialize(cache_path.read_text(encoding="utf-8"))
    assert list(persisted.search(msal.TokenCache.CredentialType.ACCOUNT)) == [ACCOUNT]
    assert {
        entry["secret"] for entry in persisted.search(msal.TokenCache.CredentialType.ACCESS_TOKEN)
    } == (
        {"wrong-client-token", "other-resource-token", "correct-client-token"}
        if cached_state == "valid" else {"wrong-client-token", "other-resource-token"}
    )


def test_reconciliation_passes_owned_client_token_to_dataverse(
    msal_factory: Mock, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import reconcile_setup_agent as reconcile

    record = {"botid": "mock-agent", "schemaname": "msdyn_copilotforemployeeselfservice"}
    get = Mock(return_value=record)
    monkeypatch.setattr(reconcile, "dataverse_get", get)

    assert reconcile._read_dataverse_agent(
        FAKE_DATAVERSE_URL, "mock-agent", "maker@example.com",
    ) == record

    assert_client(msal_factory, DATAVERSE_CLIENT)
    msal_factory.return_value.acquire_token_interactive.assert_called_once_with(
        [DATAVERSE_SCOPE], login_hint="maker@example.com",
    )
    get.assert_called_once_with(
        FAKE_DATAVERSE_URL, "interactive-token", "bots(mock-agent)",
        {"$select": "botid,name,schemaname,ismanaged"},
    )


@pytest.mark.parametrize("module_name", ["push", "restore_template_configs"])
def test_dataverse_callers_refresh_through_owned_client(
    msal_factory: Mock, module_name: str,
) -> None:
    module = importlib.import_module(module_name)
    holder = module._AuthHolder(FAKE_DATAVERSE_URL)
    holder.token = "expired-token"
    operation = Mock(side_effect=[auth.AuthExpiredError(), {"ok": True}])

    assert module._call_with_refresh(
        holder, operation, FAKE_DATAVERSE_URL, holder.token, "bots",
    ) == {"ok": True}

    assert_client(msal_factory, DATAVERSE_CLIENT)
    assert operation.call_args_list == [
        call(FAKE_DATAVERSE_URL, "expired-token", "bots"),
        call(FAKE_DATAVERSE_URL, "interactive-token", "bots"),
    ]


def test_flow_inspector_fallback_uses_flow_client(
    msal_factory: Mock, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flow_run_inspect

    monkeypatch.setattr(flow_run_inspect, "load_config", Mock(
        return_value={"dataverseEndpoint": FAKE_DATAVERSE_URL},
    ))

    assert flow_run_inspect._resolve_token("") == "interactive-token"

    assert_client(msal_factory, FLOW_CLIENT)
    msal_factory.return_value.acquire_token_interactive.assert_called_once_with(
        [FLOW_SCOPE], prompt="select_account",
    )


def test_flow_inspector_env_override_bypasses_authentication(
    msal_factory: Mock, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flow_run_inspect

    monkeypatch.setenv("FLOW_API_TOKEN", "  supplied-flow-token  ")
    config = Mock(side_effect=AssertionError("Explicit token must bypass config."))
    monkeypatch.setattr(flow_run_inspect, "load_config", config)
    latest = Mock(return_value=None)
    monkeypatch.setattr(flow_run_inspect, "get_latest_run", latest)

    assert flow_run_inspect.main(["--environment", "mock-env", "--flow", "mock-flow"]) == 1

    msal_factory.assert_not_called()
    config.assert_not_called()
    latest.assert_called_once_with("mock-env", "mock-flow", "supplied-flow-token")
