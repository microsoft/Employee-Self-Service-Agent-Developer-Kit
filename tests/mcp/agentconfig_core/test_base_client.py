# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the neutral AgentConfiguration client core (auth + token cache).

The token-flow behaviour — the shared MSAL cache location and the interactive
form-post sign-in — lives on the neutral ``AgentConfigBaseClient`` core under ``agentconfig_core/`` and
is shared by every AgentConfiguration MCP (landing-page config and planner), so it is
pinned here against ``base_client`` directly rather than any one server's client.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

import httpx
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


def test_interactive_auth_always_prompts_for_account_selection(monkeypatch, capsys) -> None:
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


def test_the_sign_in_notice_goes_to_stderr_not_stdout(monkeypatch) -> None:
    """Every consumer of this core is an MCP server whose stdout is the transport.

    A plain ``print`` here injects a bare, non-JSON line into the JSON-RPC
    stream and corrupts the session — for the landing-page and planner servers
    just as much as for org announcements. The cue itself is still needed (the
    maker has to know a browser is opening), so it belongs on stderr.
    """
    import contextlib
    import io

    class FakeServer:
        server_port = 12345

        def handle_request(self):
            base_client._FormPostCaptureHandler.captured = {"code": "fake"}

        def server_close(self):
            pass

    class FakeApp:
        def initiate_auth_code_flow(self, **kwargs):
            return {"auth_uri": "https://login.example.test"}

        def acquire_token_by_auth_code_flow(self, flow, response):
            return {"access_token": "token"}

    monkeypatch.setattr(
        base_client.http.server, "HTTPServer", lambda *args: FakeServer()
    )
    monkeypatch.setattr(base_client.webbrowser, "open", lambda url: True)

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        result = base_client._acquire_token_interactive_form_post(FakeApp())

    assert result == {"access_token": "token"}
    assert out.getvalue() == "", "the sign-in notice reached stdout"
    assert "Opening browser" in err.getvalue()
    # The loopback address is part of the cue; it must not be lost in the move.
    assert "12345" in err.getvalue()


def test_the_core_has_no_stdout_print_left() -> None:
    """Guards the whole module, not just the one call site under test."""
    source = Path(base_client.__file__).read_text(encoding="utf-8")
    lines = source.splitlines()

    offenders = []
    for number, line in enumerate(lines, 1):
        if not line.strip().startswith("print("):
            continue
        window = "\n".join(lines[number - 1 : number + 5])
        if "file=sys.stderr" not in window:
            offenders.append(f"line {number}: {line.strip()}")

    assert not offenders, "stdout print in shared MCP core: " + "; ".join(offenders)


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

    requests_seen = []

    def handler(request):
        requests_seen.append(request)
        return httpx.Response(200, json={"configured": True})

    def create_client():
        return base_client.AgentConfigBaseClient(
            base_url="https://authoring.example.test",
            logger_name="test",
            transport=httpx.MockTransport(handler),
        )

    if token_tenant != TENANT_ID:
        with pytest.raises(ValueError, match="token tenant does not match"):
            create_client()
        assert requests_seen == []
    else:
        async def run():
            client = create_client()
            assert client.tenant_id == TENANT_ID
            assert await client._request("GET", "configuration") == {"configured": True}
            await client.aclose()

        asyncio.run(run())
        assert len(requests_seen) == 1
        assert requests_seen[0].headers["Authorization"] == f"Bearer {token}"


def test_unrestricted_fallback_accepts_an_explicit_token(monkeypatch) -> None:
    token = _token_for_tenant(OTHER_TENANT_ID)
    monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN", token)
    assert base_client._resolve_token() == token


@pytest.mark.parametrize("file_tenant", [TENANT_ID, OTHER_TENANT_ID])
def test_token_file_keeps_precedence_over_environment_token(
    monkeypatch, tmp_path, file_tenant
) -> None:
    token = _token_for_tenant(file_tenant)
    path = tmp_path / "access-token"
    path.write_text(token, encoding="utf-8")
    monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN_FILE", str(path))
    monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN", _token_for_tenant(TENANT_ID))
    monkeypatch.setattr(base_client, "configured_tenant_id", lambda: TENANT_ID)
    if file_tenant == TENANT_ID:
        assert base_client._resolve_token() == token
    else:
        with pytest.raises(ValueError, match="token tenant does not match"):
            base_client._resolve_token()


@pytest.mark.parametrize("tenant", [TENANT_ID, None])
@pytest.mark.parametrize("silent", [True, False])
@pytest.mark.parametrize("token_tenant", [TENANT_ID, OTHER_TENANT_ID])
def test_msal_uses_the_resolved_authority_and_coordinated_cache(
    monkeypatch, tenant, silent, token_tenant
) -> None:
    cache = object()
    calls = {}
    account = {"home_account_id": "cached-account"}
    token = _token_for_tenant(token_tenant)
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

    if tenant is not None and token_tenant != tenant:
        with pytest.raises(ValueError, match="token tenant does not match"):
            base_client._resolve_token()
    else:
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


def test_imports_and_configuration_paths_belong_to_this_worktree() -> None:
    import _tenant_context
    import _token_cache
    import auth

    assert Path(base_client.__file__).resolve() == CORE_DIR / "base_client.py"
    assert Path(_tenant_context.__file__).resolve() == CORE_DIR / "_tenant_context.py"
    assert Path(_token_cache.__file__).resolve() == CORE_DIR / "_token_cache.py"
    assert Path(auth.__file__).resolve() == (
        REPO_ROOT / "solutions" / "ess-maker-skills" / "scripts" / "auth.py"
    )


OBJECT_ID = "00000000-0000-0000-0000-000000003333"
OTHER_OBJECT_ID = "00000000-0000-0000-0000-000000004444"


def _identity_token(version, tenant=TENANT_ID, object_id=OBJECT_ID):
    encoded = base64.urlsafe_b64encode(
        json.dumps({"tid": tenant, "oid": object_id, "version": version}).encode()
    ).decode().rstrip("=")
    return f"header.{encoded}.signature"


@pytest.mark.parametrize("source", ["environment", "file"])
@pytest.mark.parametrize("method", ["GET", "POST", "PATCH", "DELETE"])
def test_rejected_explicit_token_refreshes_once_without_changing_identity(
    monkeypatch, tmp_path, source, method
):
    initial, replacement = _identity_token("initial"), _identity_token("replacement")
    token_file = tmp_path / "token"

    def supply(token):
        if source == "file":
            token_file.write_text(token)
            monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN_FILE", str(token_file))
        else:
            monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN", token)

    requests = []

    def handler(request):
        requests.append(request.headers["Authorization"])
        status = 401 if request.headers["Authorization"] == f"Bearer {initial}" else 200
        return httpx.Response(status, json={"ok": True})

    supply(initial)
    client = base_client.AgentConfigBaseClient(
        base_url="https://api.example.test", logger_name="test",
        transport=httpx.MockTransport(handler),
    )
    supply(replacement)
    if source == "file":
        # Refresh must reread the original file, not a newly configured source.
        monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN_FILE", str(tmp_path / "other"))
    monkeypatch.setattr(base_client, "configured_tenant_id", lambda: OTHER_TENANT_ID)

    async def run():
        try:
            assert await client._request(method, "/resource", idempotent=False) == {"ok": True}
            assert await client._request(method, "/resource", idempotent=False) == {"ok": True}
        finally:
            await client.aclose()

    asyncio.run(run())
    assert requests == [f"Bearer {initial}", f"Bearer {replacement}", f"Bearer {replacement}"]
    assert (client.tenant_id, client.object_id) == (TENANT_ID, OBJECT_ID)


@pytest.mark.parametrize(
    "replacement",
    [
        _identity_token("initial"),
        _identity_token("new", tenant=OTHER_TENANT_ID),
        _identity_token("new", object_id=OTHER_OBJECT_ID),
        _identity_token("new", object_id=None),
        "opaque",
    ],
)
def test_refresh_rejects_unchanged_or_unmatched_credentials_without_replay(
    monkeypatch, replacement
):
    initial = _identity_token("initial")
    monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN", initial)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(401, json={})

    client = base_client.AgentConfigBaseClient(
        base_url="https://api.example.test", logger_name="test",
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN", replacement)

    async def run():
        try:
            with pytest.raises(base_client.AgentConfigApiError) as caught:
                await client._request("POST", "/resource", idempotent=False)
            assert caught.value.http_status == 401
            assert replacement not in str(caught.value)
        finally:
            await client.aclose()

    asyncio.run(run())
    assert len(requests) == 1
    assert client._token == initial


def test_shared_account_matching_uses_tenant_profile_not_grouped_local_id():
    from types import SimpleNamespace

    grouped = {"home_account_id": "home", "local_account_id": OTHER_OBJECT_ID, "realm": OTHER_TENANT_ID}
    intended = {"home_account_id": "home", "local_account_id": OBJECT_ID, "realm": TENANT_ID}
    other = {"home_account_id": "other", "local_account_id": OTHER_OBJECT_ID, "realm": TENANT_ID}

    def search(credential_type):
        assert credential_type == msal.TokenCache.CredentialType.ACCOUNT
        return iter([other, grouped, intended, {"realm": None, "local_account_id": None}])

    app = SimpleNamespace(
        token_cache=SimpleNamespace(search=search),
        get_accounts=lambda: [other, grouped],
    )
    assert base_client.account_for_identity(app, TENANT_ID, OBJECT_ID) is grouped
    assert base_client.account_for_identity(app, OTHER_TENANT_ID, OBJECT_ID) is None


@pytest.mark.parametrize("available", [True, False])
def test_msal_refresh_is_silent_and_selects_only_original_identity(monkeypatch, available):
    from types import SimpleNamespace

    account = {"home_account_id": "home"}
    calls = []

    def search(credential_type):
        return iter([{
            **account, "realm": TENANT_ID, "local_account_id": OBJECT_ID
        }] if available else [])

    def silent(scopes, **kwargs):
        calls.append((scopes, kwargs))
        return {"access_token": _identity_token("replacement")}

    def create_app(tenant):
        assert tenant == TENANT_ID
        return SimpleNamespace(
            token_cache=SimpleNamespace(search=search),
            get_accounts=lambda: [account],
            acquire_token_silent=silent,
        )

    monkeypatch.setattr(base_client, "_create_msal_app", create_app)
    if available:
        assert base_client._refresh_msal_token(TENANT_ID, OBJECT_ID) == _identity_token("replacement")
        assert calls == [(base_client._SCOPE, {"account": account, "force_refresh": True})]
    else:
        with pytest.raises(base_client.AgentConfigApiError, match="original account"):
            base_client._refresh_msal_token(TENANT_ID, OBJECT_ID)
        assert calls == []


def test_concurrent_401s_share_one_refresh_and_never_replay_a_second_401(monkeypatch):
    initial, replacement = _identity_token("initial"), _identity_token("replacement")
    monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN", initial)
    refreshes = []
    requests = []

    async def run():
        both_rejected = asyncio.Event()

        async def handler(request):
            token = request.headers["Authorization"]
            requests.append(token)
            if token == f"Bearer {initial}":
                if requests.count(token) == 2:
                    both_rejected.set()
                await both_rejected.wait()
            return httpx.Response(401, json={})

        client = base_client.AgentConfigBaseClient(
            base_url="https://api.example.test", logger_name="test",
            transport=httpx.MockTransport(handler),
        )

        def refresh():
            refreshes.append(True)
            return replacement

        monkeypatch.setattr(client, "_acquire_replacement_token", refresh)
        try:
            results = await asyncio.wait_for(asyncio.gather(
                client._request("GET", "/a"),
                client._request("GET", "/b"),
                return_exceptions=True,
            ), timeout=5)
            assert all(isinstance(result, base_client.AgentConfigApiError) for result in results)
        finally:
            await client.aclose()

    asyncio.run(run())
    assert refreshes == [True]
    assert len(requests) == 4


@pytest.mark.parametrize("failure", [PermissionError("private-cache"), ValueError("private-claims")])
def test_refresh_failures_remain_private_authentication_errors(monkeypatch, failure):
    monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN", _identity_token("initial"))
    client = base_client.AgentConfigBaseClient(base_url="https://api.example.test", logger_name="test")

    def fail():
        raise failure

    monkeypatch.setattr(client, "_acquire_replacement_token", fail)
    with pytest.raises(base_client.AgentConfigApiError) as caught:
        asyncio.run(client._refresh_token(client._token))
    assert caught.value.http_status == 401
    assert str(failure) not in str(caught.value)
    assert caught.value.__cause__ is failure
