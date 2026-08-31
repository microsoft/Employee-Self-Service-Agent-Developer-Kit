# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the local AgentConfiguration REST client."""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

import httpx


REPO_ROOT = Path(__file__).parents[3]
AGENTCONFIG_DIR = (
    REPO_ROOT
    / "solutions"
    / "ess-maker-skills"
    / "src"
    / "mcp"
    / "agentconfig_landing_page"
)
sys.path.insert(0, str(AGENTCONFIG_DIR))

import client as agentconfig_client  # noqa: E402


TENANT_ID = "11111111-2222-3333-4444-555555555555"
BASE_URL = "https://substrate.office.com/weveb2/api/v1.1"


def _token() -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"tid": TENANT_ID}).encode("utf-8")
    ).rstrip(b"=")
    return f"header.{payload.decode('ascii')}.signature"


def _make_client(
    monkeypatch,
    handler,
) -> tuple[agentconfig_client.AgentConfigClient, str]:
    token = _token()
    monkeypatch.setenv("AGENTCONFIG_BASE_URL", BASE_URL)
    monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN", token)
    monkeypatch.delenv("AGENTCONFIG_ACCESS_TOKEN_FILE", raising=False)
    transport = httpx.MockTransport(handler)
    return agentconfig_client.AgentConfigClient(transport=transport), token


def test_client_uses_production_api_by_default(monkeypatch) -> None:
    monkeypatch.delenv("AGENTCONFIG_BASE_URL", raising=False)
    monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN", _token())
    monkeypatch.delenv("AGENTCONFIG_ACCESS_TOKEN_FILE", raising=False)

    client = agentconfig_client.AgentConfigClient()

    assert client.base_url == agentconfig_client.DEFAULT_AGENTCONFIG_BASE_URL
    assert client.base_url == BASE_URL


def test_sends_resolved_token_as_bearer_without_exposing_it(
    monkeypatch,
) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"value": []})

    client, token = _make_client(monkeypatch, handler)

    async def run() -> None:
        await client.list_agent_configs()
        await client.aclose()

    asyncio.run(run())

    assert captured[0].headers["Authorization"] == f"Bearer {token}"
    assert token not in repr(client)


def test_collection_search_create_get_update_and_delete_use_v11_routes(
    monkeypatch,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/SearchAgents"):
            return httpx.Response(
                200,
                json={"value": [{"TitleId": "title-1", "Name": "ESS HR"}]},
            )
        if request.method == "GET" and request.url.path.endswith("/EmployeeAgents"):
            return httpx.Response(200, json={"value": [{"TitleId": "title-1"}]})
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(200, json={"TitleId": "title-1"})

    client, _ = _make_client(monkeypatch, handler)

    async def run() -> None:
        assert await client.list_agent_configs() == [{"titleId": "title-1"}]
        assert await client.search_agents("ESS") == [
            {"titleId": "title-1", "name": "ESS HR"}
        ]
        await client.create_agent_config("title-1")
        await client.get_agent_config("title-1")
        await client.update_agent_config(
            "title-1",
            {"branding": {"theming": []}},
        )
        assert await client.delete_agent_config("title-1") == {"success": True}
        await client.aclose()

    asyncio.run(run())

    collection_path = f"/weveb2/api/v1.1/tenants('{TENANT_ID}')/EmployeeAgents"
    assert requests[0].method == "GET"
    assert requests[0].url.path == collection_path
    assert requests[1].method == "POST"
    assert requests[1].url.path == f"{collection_path}/SearchAgents"
    assert json.loads(requests[1].content) == {"SearchString": "ESS"}
    assert requests[2].method == "POST"
    assert requests[2].url.path == collection_path
    assert json.loads(requests[2].content) == {"TitleId": "title-1"}
    assert requests[3].method == "GET"
    assert requests[3].url.path == f"{collection_path}('title-1')"
    assert requests[4].method == "PATCH"
    assert requests[4].url.path == f"{collection_path}('title-1')"
    update_body = json.loads(requests[4].content)
    assert update_body == {
        "Branding": {"Theming": []},
    }
    assert requests[5].method == "DELETE"
    assert requests[5].url.path == f"{collection_path}('title-1')"


def test_title_id_is_odata_escaped_and_url_encoded(monkeypatch) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    client, _ = _make_client(monkeypatch, handler)

    async def run() -> None:
        await client.get_agent_config("a'b/c")
        await client.aclose()

    asyncio.run(run())

    assert b"EmployeeAgents('a%27%27b%2Fc')" in requests[0].url.raw_path


def test_open_tools_select_the_production_server_fields(monkeypatch) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"TitleId": "title-1"})

    client, _ = _make_client(monkeypatch, handler)

    async def run() -> None:
        await client.view_agent_icon("title-1")
        await client.open_accent_color("title-1")
        await client.open_quick_links("title-1")
        await client.open_starter_prompts("title-1")
        await client.aclose()

    asyncio.run(run())

    assert [request.url.params["$select"] for request in requests] == [
        "titleId,name,icon",
        "titleId,branding",
        "titleId,quickLinksConfig",
        "titleId,pivots",
    ]


def test_api_error_uses_top_level_code_message_and_http_status(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "Code": "BadRequest",
                "Message": "The request is invalid.",
                "Details": [
                    {
                        "Code": "InvalidParameterValue",
                        "Message": "Customer-provided detail",
                    }
                ],
            },
        )

    client, _ = _make_client(monkeypatch, handler)

    async def run() -> agentconfig_client.AgentConfigApiError:
        try:
            await client.get_agent_config("title-1")
        except agentconfig_client.AgentConfigApiError as error:
            return error
        finally:
            await client.aclose()
        raise AssertionError("Expected AgentConfigApiError")

    error = asyncio.run(run())

    assert str(error) == "BadRequest: The request is invalid."
    assert error.http_status == 400
    assert "Customer-provided detail" not in str(error)


def test_create_agent_config_retries_on_ambiguous_5xx(monkeypatch) -> None:
    # The landing-page creates carry no idempotency key, yet a titleId-keyed
    # EmployeeAgents POST is convergent (same titleId => same row), so after the
    # PR #251 retry inversion an unkeyed create defaults to retry-safe. This
    # pins that a 503 is transparently retried rather than surfaced -- the
    # pre-planner behaviour the neutral core must preserve.
    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    posts: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posts.append(request)
            if len(posts) == 1:
                return httpx.Response(
                    503, json={"Code": "ServiceUnavailable", "Message": "down"}
                )
        return httpx.Response(200, json={"TitleId": "title-1"})

    client, _ = _make_client(monkeypatch, handler)

    async def run() -> dict:
        result = await client.create_agent_config("title-1")
        await client.aclose()
        return result

    result = asyncio.run(run())

    assert result == {"titleId": "title-1"}
    assert len(posts) == 2  # retried once, then succeeded
