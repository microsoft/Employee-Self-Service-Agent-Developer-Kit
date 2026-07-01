"""Unit tests for the MSAL-backed token provider."""

from __future__ import annotations

from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any

import pytest

from core.auth.token_provider import (
    AuthenticationException,
    MsalTokenProvider,
    MsalTokenProviderConfig,
    TokenResult,
)

AUTHORITY = "https://login.microsoftonline.com/tenant-id"
SCOPE = "https://contoso.crm.dynamics.com/.default"
CLIENT_ID = "client-id"
NOW = 1_000.0


class FakeMsalApplication:
    def __init__(
        self,
        *,
        accounts: list[object] | None = None,
        silent_results: list[TokenResult | None] | None = None,
        interactive_result: TokenResult | None = None,
    ) -> None:
        self.accounts = accounts or []
        self.silent_results = silent_results or []
        self.interactive_result = interactive_result or {
            "access_token": "interactive-token",
            "expires_on": NOW + 3_600,
        }
        self.silent_calls: list[tuple[tuple[str, ...], object | None, dict[str, object]]] = []
        self.interactive_calls: list[tuple[str, ...]] = []

    def get_accounts(self) -> list[object]:
        return self.accounts

    def acquire_token_silent(
        self,
        scopes: Sequence[str],
        account: object | None,
        **kwargs: object,
    ) -> TokenResult | None:
        self.silent_calls.append((tuple(scopes), account, kwargs))
        if self.silent_results:
            return self.silent_results.pop(0)
        return None

    def acquire_token_interactive(self, scopes: Sequence[str]) -> TokenResult:
        self.interactive_calls.append(tuple(scopes))
        if not self.accounts:
            self.accounts.append(object())
        return self.interactive_result


def config(
    *,
    authority: str = AUTHORITY,
    scopes: tuple[str, ...] = (SCOPE,),
) -> MsalTokenProviderConfig:
    return MsalTokenProviderConfig(client_id=CLIENT_ID, authority=authority, scopes=scopes)


def test_cold_start_uses_interactive_acquisition_only_when_no_account_exists() -> None:
    app = FakeMsalApplication()
    provider = MsalTokenProvider(config(), app=app, now=lambda: NOW)

    token = provider.get_token()

    assert token == "interactive-token"
    assert app.silent_calls == []
    assert app.interactive_calls == [(SCOPE,)]


def test_existing_account_uses_silent_acquisition_without_interactive_fallback() -> None:
    account = object()
    app = FakeMsalApplication(
        accounts=[account],
        silent_results=[{"access_token": "silent-token", "expires_on": NOW + 3_600}],
    )
    provider = MsalTokenProvider(config(), app=app, now=lambda: NOW)

    token = provider.get_token("https://contoso.crm.dynamics.com")

    assert token == "silent-token"
    assert app.silent_calls == [((SCOPE,), account, {})]
    assert app.interactive_calls == []


def test_near_expiry_token_forces_silent_refresh_before_returning() -> None:
    account = object()
    app = FakeMsalApplication(
        accounts=[account],
        silent_results=[
            {"access_token": "almost-expired-token", "expires_on": NOW + 60},
            {"access_token": "refreshed-token", "expires_on": NOW + 3_600},
        ],
    )
    provider = MsalTokenProvider(config(), app=app, now=lambda: NOW)

    token = provider.get_token()

    assert token == "refreshed-token"
    assert app.silent_calls == [
        ((SCOPE,), account, {}),
        ((SCOPE,), account, {"force_refresh": True}),
    ]
    assert app.interactive_calls == []


def test_rejects_non_https_authority_and_scopes() -> None:
    with pytest.raises(ValueError, match="authority must be an HTTPS URL"):
        config(authority="http://login.microsoftonline.com/tenant-id")

    with pytest.raises(ValueError, match="scope must be an HTTPS URL"):
        config(scopes=("http://contoso.crm.dynamics.com/.default",))

    provider = MsalTokenProvider(config(), app=FakeMsalApplication(), now=lambda: NOW)
    with pytest.raises(ValueError, match="scope must be an HTTPS URL"):
        provider.get_token("http://contoso.crm.dynamics.com")


def test_acquisition_failure_raises_sanitized_authentication_exception() -> None:
    account = object()
    app = FakeMsalApplication(
        accounts=[account],
        silent_results=[{"error": "invalid_grant", "error_description": "secret provider detail"}],
    )
    provider = MsalTokenProvider(config(), app=app, now=lambda: NOW)

    with pytest.raises(AuthenticationException) as exc_info:
        provider.get_token()

    assert str(exc_info.value) == "Authentication token acquisition failed."
    assert "secret provider detail" not in str(exc_info.value)
    assert app.interactive_calls == []


def test_default_msal_application_uses_in_memory_cache_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class CapturingPublicClientApplication:
        def __init__(self, client_id: str, **kwargs: object) -> None:
            calls.append({"client_id": client_id, **kwargs})

    fake_msal = SimpleNamespace(PublicClientApplication=CapturingPublicClientApplication)
    monkeypatch.setattr("core.auth.token_provider.import_module", lambda name: fake_msal)

    MsalTokenProvider(config())

    assert calls == [{"client_id": CLIENT_ID, "authority": AUTHORITY}]
    assert "token_cache" not in calls[0]
