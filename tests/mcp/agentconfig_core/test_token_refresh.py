# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Offline regressions for authentication in a long-lived MCP client."""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

import httpx
import msal
import pytest


CORE_DIR = (
    Path(__file__).parents[3]
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
OBJECT_ID = "00000000-0000-0000-0000-000000003333"
OTHER_OBJECT_ID = "00000000-0000-0000-0000-000000004444"


def _token(version, tenant=TENANT_ID, object_id=OBJECT_ID):
    payload = {"tid": tenant, "version": version}
    if object_id is not None:
        payload["oid"] = object_id
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"header.{encoded}.signature"


@pytest.fixture(autouse=True)
def isolate_authentication(monkeypatch):
    monkeypatch.delenv("AGENTCONFIG_ACCESS_TOKEN_FILE", raising=False)
    monkeypatch.delenv("AGENTCONFIG_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(base_client, "configured_tenant_id", lambda: TENANT_ID)

    def unexpected_interactive(*args, **kwargs):
        pytest.fail("Automatic refresh must not open an interactive sign-in")

    monkeypatch.setattr(
        base_client, "_acquire_token_interactive_form_post", unexpected_interactive
    )


def _client(handler):
    return base_client.AgentConfigBaseClient(
        base_url="https://api.example.test",
        logger_name="test",
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.parametrize("source", ["environment", "file"])
@pytest.mark.parametrize("method", ["GET", "POST", "PATCH", "DELETE"])
def test_long_lived_client_recovers_after_explicit_token_replacement(
    monkeypatch, tmp_path, source, method
):
    initial, replacement = _token("initial"), _token("replacement")
    token_file = tmp_path / "token"

    def supply(token):
        if source == "file":
            token_file.write_text(token, encoding="utf-8")
            monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN_FILE", str(token_file))
        else:
            monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN", token)

    supply(initial)
    expected_token = initial
    requests = []

    def handler(request):
        requests.append(request.headers["Authorization"])
        if request.headers["Authorization"] != f"Bearer {expected_token}":
            return httpx.Response(401, json={"Code": "Unauthorized", "Message": "Expired"})
        return httpx.Response(200, json={"ok": True})

    client = _client(handler)

    async def run():
        nonlocal expected_token
        try:
            assert await client._request(method, "/resource", idempotent=False) == {"ok": True}
            expected_token = replacement
            supply(replacement)
            assert await client._request(method, "/resource", idempotent=False) == {"ok": True}
            assert await client._request(method, "/resource", idempotent=False) == {"ok": True}
        finally:
            await client.aclose()

    asyncio.run(run())
    assert requests == [
        f"Bearer {initial}", f"Bearer {initial}",
        f"Bearer {replacement}", f"Bearer {replacement}",
    ]


def test_unchanged_explicit_token_does_not_retry_or_fall_back_to_msal(monkeypatch):
    token = _token("initial")
    monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN", token)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(401, json={})

    client = _client(handler)

    async def run():
        try:
            with pytest.raises(base_client.AgentConfigApiError) as caught:
                await client._request("GET", "/resource")
            assert caught.value.http_status == 401
            assert token not in str(caught.value)
        finally:
            await client.aclose()

    asyncio.run(run())
    assert len(requests) == 1


@pytest.mark.parametrize(
    ("tenant", "object_id"),
    [(OTHER_TENANT_ID, OBJECT_ID), (TENANT_ID, OTHER_OBJECT_ID), (TENANT_ID, None)],
)
def test_replacement_cannot_change_the_original_account_or_tenant(
    monkeypatch, tenant, object_id
):
    initial = _token("initial")
    monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN", initial)
    requests = []

    def handler(request):
        requests.append(request.headers["Authorization"])
        return httpx.Response(401, json={})

    client = _client(handler)
    monkeypatch.setenv(
        "AGENTCONFIG_ACCESS_TOKEN", _token("replacement", tenant, object_id)
    )

    async def run():
        try:
            with pytest.raises((base_client.AgentConfigApiError, ValueError)):
                await client._request("GET", "/resource")
        finally:
            await client.aclose()

    asyncio.run(run())
    assert client._token == initial
    assert client.tenant_id == TENANT_ID
    assert requests == [f"Bearer {initial}"]


def _mock_msal_refresh(monkeypatch, result, accounts=None, profiles=None):
    original = _token("initial")
    monkeypatch.setattr(base_client, "_resolve_token", lambda: original)
    calls = []
    matching_account = {
        "home_account_id": "home-account",
        "local_account_id": OBJECT_ID,
        "realm": TENANT_ID,
    }
    available = accounts if accounts is not None else [
        {"local_account_id": OTHER_OBJECT_ID, "realm": TENANT_ID},
        {"local_account_id": OBJECT_ID, "realm": OTHER_TENANT_ID},
        matching_account,
    ]

    class FakeCache:
        def search(self, credential_type):
            assert credential_type == msal.TokenCache.CredentialType.ACCOUNT
            return iter(profiles if profiles is not None else available)

    cache = FakeCache()

    class FakeApp:
        token_cache = cache

        def get_accounts(self):
            return available

        def acquire_token_silent(self, scopes, account, **kwargs):
            calls.append((scopes, account, kwargs))
            return result

    def create_app(client_id, **kwargs):
        assert client_id == base_client._CLIENT_ID
        assert kwargs == {
            "authority": f"https://login.microsoftonline.com/{TENANT_ID}",
            "token_cache": cache,
        }
        return FakeApp()

    monkeypatch.setattr(base_client, "create_token_cache", lambda path: cache)
    monkeypatch.setattr(msal, "PublicClientApplication", create_app)
    return original, matching_account, calls


def test_msal_refresh_resolves_the_original_profile_in_a_multitenant_account(monkeypatch):
    original_profile = {
        "home_account_id": "same-home-account",
        "realm": TENANT_ID,
        "local_account_id": OBJECT_ID,
    }
    grouped_account = {
        "home_account_id": "same-home-account",
        "realm": OTHER_TENANT_ID,
        "local_account_id": OTHER_OBJECT_ID,
    }
    replacement = _token("replacement")
    initial, _, calls = _mock_msal_refresh(
        monkeypatch,
        {"access_token": replacement},
        accounts=[grouped_account],
        profiles=[original_profile, grouped_account, {"realm": None, "local_account_id": None}],
    )

    def handler(request):
        if request.headers["Authorization"] == f"Bearer {initial}":
            return httpx.Response(401, json={})
        assert request.headers["Authorization"] == f"Bearer {replacement}"
        return httpx.Response(200, json={"ok": True})

    client = _client(handler)

    async def run():
        try:
            assert await client._request("GET", "/resource") == {"ok": True}
        finally:
            await client.aclose()

    asyncio.run(run())
    assert calls == [(base_client._SCOPE, grouped_account, {"force_refresh": True})]


def test_msal_refresh_is_forced_for_original_identity_and_bounded_on_401(monkeypatch):
    replacement = _token("replacement")
    initial, account, calls = _mock_msal_refresh(
        monkeypatch, {"access_token": replacement}
    )
    requests = []

    def handler(request):
        requests.append(request.headers["Authorization"])
        return httpx.Response(401, json={"Code": "Unauthorized", "Message": "Rejected"})

    client = _client(handler)
    client.max_retries = 1

    async def run():
        try:
            with pytest.raises(base_client.AgentConfigApiError) as caught:
                await client._request("GET", "/resource")
            assert caught.value.http_status == 401
        finally:
            await client.aclose()

    asyncio.run(run())
    assert calls == [(base_client._SCOPE, account, {"force_refresh": True})]
    assert requests == [f"Bearer {initial}", f"Bearer {replacement}"]


@pytest.mark.parametrize("failure", ["missing-account", "interaction-required"])
def test_failed_silent_refresh_does_not_select_another_account(monkeypatch, failure):
    result = {"error": "interaction_required"}
    accounts = [] if failure == "missing-account" else None
    initial, _, calls = _mock_msal_refresh(monkeypatch, result, accounts)
    requests = []

    def handler(request):
        requests.append(request.headers["Authorization"])
        return httpx.Response(401, json={})

    client = _client(handler)

    async def run():
        try:
            with pytest.raises(base_client.AgentConfigApiError) as caught:
                await client._request("GET", "/resource")
            assert caught.value.http_status == 401
            assert "original account" in str(caught.value)
        finally:
            await client.aclose()

    asyncio.run(run())
    assert requests == [f"Bearer {initial}"]
    assert len(calls) == (0 if failure == "missing-account" else 1)


def test_concurrent_401_responses_share_one_refresh(monkeypatch):
    replacement = _token("replacement")
    initial, _, calls = _mock_msal_refresh(monkeypatch, {"access_token": replacement})
    rejected = 0
    requests = []

    async def run():
        both_rejected = asyncio.Event()

        async def handler(request):
            nonlocal rejected
            authorization = request.headers["Authorization"]
            requests.append(authorization)
            if authorization == f"Bearer {initial}":
                rejected += 1
                if rejected == 2:
                    both_rejected.set()
                await both_rejected.wait()
                return httpx.Response(401, json={})
            assert authorization == f"Bearer {replacement}"
            return httpx.Response(200, json={"ok": True})

        client = _client(handler)
        try:
            results = await asyncio.wait_for(
                asyncio.gather(
                    client._request("GET", "/first"),
                    client._request("GET", "/second"),
                ),
                timeout=5,
            )
            assert results == [{"ok": True}, {"ok": True}]
        finally:
            await client.aclose()

    asyncio.run(run())
    assert len(calls) == 1
    assert len(requests) == 4


@pytest.mark.parametrize("status", [400, 403, 404, 409, 412])
def test_non_authentication_failures_do_not_refresh(monkeypatch, status):
    initial, _, calls = _mock_msal_refresh(
        monkeypatch, {"access_token": _token("replacement")}
    )
    requests = []

    def handler(request):
        requests.append(request.headers["Authorization"])
        return httpx.Response(status, json={})

    client = _client(handler)

    async def run():
        try:
            with pytest.raises(base_client.AgentConfigApiError) as caught:
                await client._request("POST", "/resource", idempotent=False)
            assert caught.value.http_status == status
        finally:
            await client.aclose()

    asyncio.run(run())
    assert calls == []
    assert requests == [f"Bearer {initial}"]


def test_refresh_keeps_original_token_file_and_tenant_binding(monkeypatch, tmp_path):
    initial, replacement = _token("initial"), _token("replacement")
    path = tmp_path / "original-token"
    path.write_text(initial, encoding="utf-8")
    monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN_FILE", str(path))
    requests = []

    def handler(request):
        authorization = request.headers["Authorization"]
        requests.append(authorization)
        if authorization == f"Bearer {initial}":
            return httpx.Response(401, json={})
        assert authorization == f"Bearer {replacement}"
        return httpx.Response(200, json={"ok": True})

    client = _client(handler)
    path.write_text(replacement, encoding="utf-8")
    monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN_FILE", str(tmp_path / "different-file"))
    monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN", _token("other", OTHER_TENANT_ID))
    monkeypatch.setattr(base_client, "configured_tenant_id", lambda: OTHER_TENANT_ID)

    async def run():
        try:
            assert await client._request("GET", "/resource") == {"ok": True}
        finally:
            await client.aclose()

    asyncio.run(run())
    assert client.tenant_id == TENANT_ID
    assert requests == [f"Bearer {initial}", f"Bearer {replacement}"]


def test_unavailable_original_file_does_not_fall_back_to_another_source(
    monkeypatch, tmp_path
):
    initial = _token("initial")
    path = tmp_path / "token"
    path.write_text(initial, encoding="utf-8")
    monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN_FILE", str(path))
    client = _client(lambda request: httpx.Response(401, json={}))
    path.unlink()
    monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN", _token("replacement"))

    async def run():
        try:
            with pytest.raises(ValueError, match="does not exist"):
                await client._request("GET", "/resource")
        finally:
            await client.aclose()

    asyncio.run(run())
    assert client._token == initial


def test_missing_original_account_identity_prevents_automatic_refresh(monkeypatch):
    initial = _token("initial", object_id=None)
    monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN", initial)
    client = _client(lambda request: httpx.Response(401, json={}))
    monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN", _token("replacement"))

    async def run():
        try:
            with pytest.raises(base_client.AgentConfigApiError, match="cannot be identified"):
                await client._request("GET", "/resource")
        finally:
            await client.aclose()

    asyncio.run(run())
    assert client._token == initial
