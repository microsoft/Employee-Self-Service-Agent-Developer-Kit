"""Auth: tenant discovery from the Dataverse challenge, and scope shaping."""

from __future__ import annotations

import httpx
import pytest

from essmig import auth

ENV = "https://contoso.crm.dynamics.com"
TENANT = "72f988bf-86f1-41af-91ab-2d7cd011db47"


def _challenge(value: str | None) -> object:
    headers = {} if value is None else {"WWW-Authenticate": value}

    class _Response:
        def __init__(self) -> None:
            self.headers = headers

    return _Response()


@pytest.fixture(autouse=True)
def _no_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ESSMIG_MSAL_AUTHORITY", "ESSMIG_MSAL_SCOPE", "ESSMIG_MSAL_CLIENT_ID"):
        monkeypatch.delenv(name, raising=False)


def test_discovers_the_tenant_from_the_challenge(monkeypatch: pytest.MonkeyPatch) -> None:
    header = (
        f'Bearer authorization_uri=https://login.microsoftonline.com/{TENANT}/oauth2/authorize, '
        "resource_id=https://contoso.crm.dynamics.com/"
    )
    monkeypatch.setattr(auth.httpx, "get", lambda *a, **k: _challenge(header))
    assert auth.discover_tenant(ENV) == TENANT


def test_falls_back_when_the_environment_is_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_a: object, **_k: object) -> object:
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(auth.httpx, "get", _raise)
    assert auth.discover_tenant(ENV) == "organizations"


def test_falls_back_when_no_authorization_uri_is_advertised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth.httpx, "get", lambda *a, **k: _challenge(None))
    assert auth.discover_tenant(ENV) == "organizations"


def test_provider_targets_the_environments_own_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "discover_tenant", lambda _url: TENANT)
    monkeypatch.setattr(auth.MsalTokenProvider, "_build_app", staticmethod(lambda _c: object()))

    config = auth.provider_for(f"{ENV}/")._config

    assert config.authority == f"https://login.microsoftonline.com/{TENANT}"
    assert config.scopes == (f"{ENV}/user_impersonation",)
    assert config.client_id == auth.DEFAULT_CLIENT_ID


def test_environment_variables_override_authority_and_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ESSMIG_MSAL_AUTHORITY", "https://login.microsoftonline.com/other")
    monkeypatch.setenv("ESSMIG_MSAL_SCOPE", f"{ENV}/.default")
    monkeypatch.setenv("ESSMIG_MSAL_CLIENT_ID", "11111111-1111-1111-1111-111111111111")
    monkeypatch.setattr(auth.MsalTokenProvider, "_build_app", staticmethod(lambda _c: object()))

    def _fail(_url: str) -> str:
        raise AssertionError("tenant discovery must be skipped when the authority is pinned")

    monkeypatch.setattr(auth, "discover_tenant", _fail)

    config = auth.provider_for(ENV)._config

    assert config.authority == "https://login.microsoftonline.com/other"
    assert config.scopes == (f"{ENV}/.default",)
    assert config.client_id == "11111111-1111-1111-1111-111111111111"


def test_a_user_impersonation_scope_is_not_rewritten_to_default() -> None:
    assert auth._normalize_scope(f"{ENV}/user_impersonation") == f"{ENV}/user_impersonation"
    assert auth._normalize_scope(ENV) == f"{ENV}/.default"
