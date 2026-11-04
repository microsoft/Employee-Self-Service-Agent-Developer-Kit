# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Offline regressions for native evaluation's Power Platform sign-in."""

import pytest

import broker_auth
import minimalbot_evaluation as minimalbot


TENANT_ID = "00000000-0000-4000-8000-000000001111"
SCOPE = "https://api.preprod.powerplatform.com/.default"


@pytest.mark.parametrize("windows", [False, True])
@pytest.mark.parametrize("silent", [False, True])
@pytest.mark.parametrize("preferred", [None, "maker@example.test"])
def test_native_auth_preserves_account_authority_and_scopes(
    monkeypatch, tmp_path, windows, silent, preferred
):
    monkeypatch.chdir(tmp_path)
    calls = {}
    other_account = {"username": "other@example.test", "account_source": "broker"}
    account = {"username": "maker@example.test", "account_source": "broker"}
    selected = account if preferred else other_account

    class FakeApp:
        _enable_broker = windows

        def __init__(self, client_id, **kwargs):
            calls["constructor"] = (client_id, kwargs)

        def get_accounts(self):
            return [other_account, account]

        def acquire_token_silent(self, scopes, **kwargs):
            calls["silent"] = (scopes, kwargs)
            return {"access_token": "token"} if silent else None

        def acquire_token_interactive(self, **kwargs):
            calls["interactive"] = kwargs
            if windows:
                kwargs["on_before_launching_ui"](ui="broker")
            return {
                "access_token": "token",
                "id_token_claims": {"preferred_username": "maker@example.test"},
            }

    monkeypatch.setattr(broker_auth, "is_windows", lambda: windows)
    monkeypatch.setattr(broker_auth, "_parent_window_handle", lambda: 12345)
    monkeypatch.setattr(minimalbot.msal, "PublicClientApplication", FakeApp)

    assert minimalbot.acquire_test_pp_token(TENANT_ID, SCOPE, preferred) == (
        "token",
        selected["username"] if silent else "maker@example.test",
    )
    client_id, options = calls["constructor"]
    assert client_id == minimalbot.CLIENT_ID
    assert options["authority"] == f"https://login.microsoftonline.com/{TENANT_ID}"
    assert isinstance(options["token_cache"], minimalbot.msal.SerializableTokenCache)
    assert options.get("enable_broker_on_windows", False) is windows
    if windows:
        assert isinstance(options["http_client"], broker_auth._BrokerOnlyHttpClient)
    else:
        assert "http_client" not in options
    assert calls["silent"] == ([SCOPE], {"account": selected})
    assert ("interactive" in calls) is not silent
    if not silent:
        expected = {"scopes": [SCOPE]}
        expected.update({"login_hint": preferred} if preferred else {"prompt": "select_account"})
        if windows:
            expected.update(
                parent_window_handle=12345,
                on_before_launching_ui=broker_auth._require_broker_ui,
            )
        assert calls["interactive"] == expected


@pytest.mark.parametrize("error", ["user_cancelled", "interaction_required"])
def test_native_windows_broker_failure_does_not_retry_in_browser(
    monkeypatch, tmp_path, error
):
    monkeypatch.chdir(tmp_path)
    calls = []

    class FakeApp:
        _enable_broker = True

        def __init__(self, *args, **kwargs):
            pass

        def get_accounts(self):
            return []

        def acquire_token_interactive(self, **kwargs):
            calls.append(kwargs)
            return {"error": error, "error_description": "Sensitive diagnostic text"}

    monkeypatch.setattr(broker_auth, "is_windows", lambda: True)
    monkeypatch.setattr(broker_auth, "_parent_window_handle", lambda: 12345)
    monkeypatch.setattr(minimalbot.msal, "PublicClientApplication", FakeApp)

    with pytest.raises(minimalbot.MinimalBotEvaluationError, match=error) as caught:
        minimalbot.acquire_test_pp_token(TENANT_ID, SCOPE)
    assert "Sensitive" not in str(caught.value)
    assert len(calls) == 1


def test_broker_migration_does_not_attribute_interactive_token_to_stale_account(
    monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)

    class FakeApp:
        _enable_broker = True

        def __init__(self, *args, **kwargs):
            pass

        def get_accounts(self):
            return [{"username": "maker@example.test", "account_source": "authorization_code"}]

        def acquire_token_silent(self, *args, **kwargs):
            pytest.fail("Legacy credentials must not be refreshed without WAM")

        def acquire_token_interactive(self, **kwargs):
            return {"access_token": "header.e30.signature"}

    monkeypatch.setattr(broker_auth, "is_windows", lambda: True)
    monkeypatch.setattr(broker_auth, "_parent_window_handle", lambda: 12345)
    monkeypatch.setattr(minimalbot.msal, "PublicClientApplication", FakeApp)

    assert minimalbot.acquire_test_pp_token(
        TENANT_ID, SCOPE, "maker@example.test"
    ) == ("header.e30.signature", "")
