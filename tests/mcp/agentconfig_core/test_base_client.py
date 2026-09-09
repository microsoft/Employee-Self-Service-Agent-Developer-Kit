# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the neutral AgentConfiguration client core (auth + token cache).

The token-flow behaviour — the shared MSAL cache location and the interactive
form-post sign-in — lives on the neutral ``AgentConfigBaseClient`` core under ``agentconfig_core/`` and
is shared by every AgentConfiguration MCP (landing-page config and planner), so it is
pinned here against ``base_client`` directly rather than any one server's client.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import msal
import pytest


REPO_ROOT = Path(__file__).parents[3]
CORE_DIR = (
    REPO_ROOT
    / "solutions"
    / "ess-maker-skills"
    / "src"
    / "mcp"
    / "agentconfig_core"
)
sys.path.insert(0, str(CORE_DIR))

import base_client  # noqa: E402


TENANT_ID = "00000000-0000-0000-0000-000000001111"
OTHER_TENANT_ID = "00000000-0000-0000-0000-000000002222"


def _token_for_tenant(tenant_id: str) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"tid": tenant_id}).encode()
    ).decode().rstrip("=")
    return f"header.{payload}.signature"


@pytest.fixture(autouse=True)
def isolate_authentication(monkeypatch) -> None:
    monkeypatch.delenv("AGENTCONFIG_ACCESS_TOKEN_FILE", raising=False)
    monkeypatch.delenv("AGENTCONFIG_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(base_client, "configured_tenant_id", lambda: None)


def test_token_cache_uses_shared_local_state() -> None:
    assert Path(base_client._TOKEN_CACHE_PATH) == (
        REPO_ROOT
        / "solutions"
        / "ess-maker-skills"
        / "src"
        / "mcp"
        / "agentconfig_core"
        / ".local"
        / "msal_token_cache.bin"
    )


def test_interactive_auth_always_prompts_for_account_selection(
    monkeypatch, capsys
) -> None:
    captured: dict[str, object] = {}

    class FakeServer:
        server_port = 12345

        def handle_request(self) -> None:
            base_client._FormPostCaptureHandler.captured = {
                "code": "authorization-code"
            }

        def server_close(self) -> None:
            pass

    class FakeApp:
        def initiate_auth_code_flow(self, **kwargs):
            captured.update(kwargs)
            return {"auth_uri": "https://login.example.test"}

        def acquire_token_by_auth_code_flow(self, flow, response):
            return {"access_token": "token"}

    monkeypatch.setattr(
        base_client.http.server,
        "HTTPServer",
        lambda *args: FakeServer(),
    )
    monkeypatch.setattr(base_client.webbrowser, "open", lambda url: True)

    result = base_client._acquire_token_interactive_form_post(FakeApp())

    assert result == {"access_token": "token"}
    assert captured["prompt"] == "select_account"
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == (
        "Opening browser for AgentConfiguration sign-in "
        "(http://localhost:12345) ...\n"
    )


@pytest.mark.parametrize("source", ["environment", "file", "msal"])
@pytest.mark.parametrize("token_tenant", [TENANT_ID, OTHER_TENANT_ID])
def test_every_token_source_is_bound_to_the_configured_tenant(
    monkeypatch, tmp_path, source, token_tenant
) -> None:
    token = _token_for_tenant(token_tenant)
    monkeypatch.setattr(base_client, "configured_tenant_id", lambda: TENANT_ID)
    if source == "environment":
        monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN", token)
    elif source == "file":
        path = tmp_path / "access-token"
        path.write_text(token, encoding="utf-8")
        monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN_FILE", str(path))
    else:
        def acquire(tenant):
            assert tenant == TENANT_ID
            return token

        monkeypatch.setattr(base_client, "acquire_token_msal_interactive", acquire)

    if token_tenant != TENANT_ID:
        with pytest.raises(ValueError, match="token tenant does not match"):
            base_client.AgentConfigBaseClient(
                base_url="https://api.example.test", logger_name="test"
            )
    else:
        client = base_client.AgentConfigBaseClient(
            base_url="https://api.example.test", logger_name="test"
        )
        assert client.tenant_id == TENANT_ID


def test_unrestricted_fallback_accepts_an_explicit_token(monkeypatch) -> None:
    token = _token_for_tenant(OTHER_TENANT_ID)
    monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN", token)

    assert base_client._resolve_token() == token


def test_token_file_keeps_precedence_over_environment_token(monkeypatch, tmp_path) -> None:
    token = _token_for_tenant(TENANT_ID)
    path = tmp_path / "access-token"
    path.write_text(token, encoding="utf-8")
    monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN_FILE", str(path))
    monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN", _token_for_tenant(OTHER_TENANT_ID))
    monkeypatch.setattr(base_client, "configured_tenant_id", lambda: TENANT_ID)

    assert base_client._resolve_token() == token


@pytest.mark.parametrize("tenant", [TENANT_ID, None])
@pytest.mark.parametrize("silent", [True, False])
def test_msal_uses_the_resolved_authority_and_coordinated_cache(
    monkeypatch, tenant, silent
) -> None:
    cache = object()
    calls = {}
    account = {"home_account_id": "cached-account"}
    token = _token_for_tenant(TENANT_ID)
    monkeypatch.setattr(base_client, "configured_tenant_id", lambda: tenant)

    def create_cache(path):
        assert path == base_client._TOKEN_CACHE_PATH
        return cache

    class FakeApp:
        def get_accounts(self):
            return [account]

        def acquire_token_silent(self, scopes, account):
            calls["silent"] = (scopes, account)
            return {"access_token": token} if silent else None

    app = FakeApp()

    def create_app(client_id, **kwargs):
        calls["app"] = (client_id, kwargs)
        return app

    def interactive(actual_app):
        assert actual_app is app
        calls["interactive"] = True
        return {"access_token": token}

    monkeypatch.setattr(base_client, "create_token_cache", create_cache)
    monkeypatch.setattr(msal, "PublicClientApplication", create_app)
    monkeypatch.setattr(base_client, "_acquire_token_interactive_form_post", interactive)

    assert base_client._resolve_token() == token
    assert calls["app"] == (
        base_client._CLIENT_ID,
        {
            "authority": f"https://login.microsoftonline.com/{tenant or 'organizations'}",
            "token_cache": cache,
        },
    )
    assert calls["silent"] == (base_client._SCOPE, account)
    assert ("interactive" in calls) is not silent


def test_scoped_login_failure_does_not_retry_unrestricted(monkeypatch) -> None:
    monkeypatch.setattr(base_client, "configured_tenant_id", lambda: TENANT_ID)
    calls = []

    def acquire(tenant):
        calls.append(tenant)
        raise ValueError("MSAL sign-in failed")

    monkeypatch.setattr(base_client, "acquire_token_msal_interactive", acquire)

    with pytest.raises(ValueError, match="MSAL sign-in failed"):
        base_client._resolve_token()
    assert calls == [TENANT_ID]
