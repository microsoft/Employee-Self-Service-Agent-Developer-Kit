# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Offline tests for Windows broker activation and browser-cache migration."""

import ctypes
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import broker_auth


@pytest.mark.parametrize("windows", [False, True])
def test_broker_activation_preserves_constructor_arguments(monkeypatch, windows):
    app = SimpleNamespace(_enable_broker=True)
    constructor = Mock(return_value=app)
    cache = object()
    monkeypatch.setattr(broker_auth, "is_windows", lambda: windows)
    monkeypatch.setattr(broker_auth.msal, "PublicClientApplication", constructor)

    assert broker_auth.create_public_client_application(
        "client-id", authority="https://login.example.test/tenant", token_cache=cache
    ) is app
    expected = {"authority": "https://login.example.test/tenant", "token_cache": cache}
    if windows:
        expected["enable_broker_on_windows"] = True
        expected["http_client"] = constructor.call_args.kwargs["http_client"]
        assert isinstance(expected["http_client"], broker_auth._BrokerOnlyHttpClient)
    constructor.assert_called_once_with("client-id", **expected)


@pytest.mark.parametrize("failure", ["missing-dependency", "deactivated-broker"])
def test_windows_broker_unavailability_fails_before_token_acquisition(monkeypatch, failure):
    app = SimpleNamespace(_enable_broker=False)
    constructor = Mock(
        side_effect=ImportError("broker unavailable")
        if failure == "missing-dependency"
        else None,
        return_value=app,
    )
    monkeypatch.setattr(broker_auth, "is_windows", lambda: True)
    monkeypatch.setattr(broker_auth.msal, "PublicClientApplication", constructor)

    with pytest.raises(broker_auth.BrokerAuthenticationError, match="broker"):
        broker_auth.create_public_client_application("client-id")


@pytest.mark.parametrize(
    "console,foreground,expected",
    [(0x100001234, 0, 0x100001234), (0, 0x100005678, 0x100005678), (0, 0, None)],
)
def test_window_parenting_handles_console_and_stdio_hosts(
    monkeypatch, console, foreground, expected
):
    console_function = Mock(return_value=console)
    foreground_function = Mock(return_value=foreground)
    libraries = {
        "kernel32": SimpleNamespace(GetConsoleWindow=console_function),
        "user32": SimpleNamespace(GetForegroundWindow=foreground_function),
    }
    monkeypatch.setattr(
        ctypes, "WinDLL", lambda name, **kwargs: libraries[name], raising=False
    )
    if expected is None:
        with pytest.raises(broker_auth.BrokerAuthenticationError, match="desktop window"):
            broker_auth._parent_window_handle()
    else:
        assert broker_auth._parent_window_handle() == expected
    assert foreground_function.call_count == (0 if console else 1)
    assert console_function.restype is ctypes.c_void_p


@pytest.mark.parametrize("windows", [False, True])
@pytest.mark.parametrize("account_source", ["broker", "authorization_code", None])
def test_silent_auth_does_not_refresh_legacy_windows_credentials(
    monkeypatch, windows, account_source
):
    silent = Mock(return_value={"access_token": "token"})
    app = SimpleNamespace(acquire_token_silent=silent)
    account = {"username": "maker@example.test", "account_source": account_source}
    monkeypatch.setattr(broker_auth, "is_windows", lambda: windows)

    result = broker_auth.acquire_token_silent(
        app, ["scope"], account=account, force_refresh=True
    )

    if windows and account_source != "broker":
        assert result is None
        silent.assert_not_called()
    else:
        assert result == {"access_token": "token"}
        silent.assert_called_once_with(["scope"], account=account, force_refresh=True)


def test_windows_interactive_auth_rejects_browser_fallback(monkeypatch):
    def launch(**kwargs):
        kwargs["on_before_launching_ui"](ui="browser")
        pytest.fail("Browser launch should have been blocked")

    app = SimpleNamespace(acquire_token_interactive=launch)
    monkeypatch.setattr(broker_auth, "is_windows", lambda: True)
    monkeypatch.setattr(broker_auth, "_parent_window_handle", lambda: 12345)

    with pytest.raises(broker_auth.BrokerAuthenticationError, match="Browser fallback"):
        broker_auth.acquire_token_interactive(app, ["scope"])


def test_missing_broker_account_cannot_use_an_old_http_refresh_token(monkeypatch):
    http_client = broker_auth._BrokerOnlyHttpClient()
    request = Mock(side_effect=AssertionError("HTTP token request must not be sent"))
    monkeypatch.setattr(http_client, "request", request)
    monkeypatch.setattr(broker_auth, "is_windows", lambda: True)

    def sdk_silent_fallback(*args, **kwargs):
        return http_client.post("https://login.example.test/tenant/oauth2/v2.0/token")

    app = SimpleNamespace(acquire_token_silent=sdk_silent_fallback)
    assert broker_auth.acquire_token_silent(
        app, ["scope"], account={"account_source": "broker"}
    ) is None
    request.assert_not_called()
