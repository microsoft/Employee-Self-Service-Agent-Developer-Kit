"""Unit tests for the typed Dataverse Web API client."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from core.outbound import AuthenticationExpiredError, DataverseApiError, DataverseClient

ENV_URL = "https://contoso.crm.dynamics.com"


class FakeTokenProvider:
    def __init__(self, tokens: list[str] | None = None) -> None:
        self._tokens = tokens or ["token-1"]
        self.calls = 0

    def get_token(self) -> str:
        self.calls += 1
        if self.calls <= len(self._tokens):
            return self._tokens[self.calls - 1]
        return self._tokens[-1]


def make_client(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    token_provider: FakeTokenProvider | None = None,
    sleep: Callable[[float], None] | None = None,
) -> tuple[DataverseClient, FakeTokenProvider]:
    provider = token_provider or FakeTokenProvider()
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, base_url=f"{ENV_URL}/api/data/v9.2/")
    return DataverseClient(ENV_URL, provider, client=http_client, sleep=sleep), provider


def test_query_all_acquires_a_fresh_token_and_applies_odata_headers_per_request() -> None:
    seen_tokens: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_tokens.append(request.headers["Authorization"])
        assert request.headers["Accept"] == "application/json"
        assert request.headers["OData-MaxVersion"] == "4.0"
        assert request.headers["OData-Version"] == "4.0"
        assert request.headers["Prefer"] == "odata.include-annotations=*"

        if "page=2" in str(request.url):
            return httpx.Response(200, json={"value": [{"id": 2}]})
        return httpx.Response(
            200,
            json={
                "value": [{"id": 1}],
                "@odata.nextLink": f"{ENV_URL}/api/data/v9.2/bots?page=2",
            },
        )

    client, provider = make_client(
        handler,
        token_provider=FakeTokenProvider(["token-1", "token-2"]),
    )

    records = client.query_all("bots", select="botid,name")

    assert records == [{"id": 1}, {"id": 2}]
    assert provider.calls == 2
    assert seen_tokens == ["Bearer token-1", "Bearer token-2"]


def test_query_all_follows_odata_next_link_until_all_pages_are_returned() -> None:
    requests_seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(str(request.url))
        if "page=3" in str(request.url):
            return httpx.Response(200, json={"value": [{"id": 3}]})
        if "page=2" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "value": [{"id": 2}],
                    "@odata.nextLink": f"{ENV_URL}/api/data/v9.2/bots?page=3",
                },
            )
        return httpx.Response(
            200,
            json={
                "value": [{"id": 1}],
                "@odata.nextLink": f"{ENV_URL}/api/data/v9.2/bots?page=2",
            },
        )

    client, _ = make_client(handler)

    records = client.query_all("bots", select="botid")

    assert records == [{"id": 1}, {"id": 2}, {"id": 3}]
    assert requests_seen == [
        f"{ENV_URL}/api/data/v9.2/bots?%24select=botid",
        f"{ENV_URL}/api/data/v9.2/bots?page=2",
        f"{ENV_URL}/api/data/v9.2/bots?page=3",
    ]


def test_get_retries_on_retryable_statuses_and_respects_retry_after_header() -> None:
    attempts = 0
    sleep_calls: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        if attempts == 2:
            return httpx.Response(503)
        return httpx.Response(200, json={"value": [{"id": 1}]})

    client, provider = make_client(handler, sleep=sleep_calls.append)

    payload = client.get("bots")

    assert payload == {"value": [{"id": 1}]}
    assert attempts == 3
    assert provider.calls == 3
    assert sleep_calls == [7.0, 2.0]


@pytest.mark.parametrize(
    ("operation", "runner"),
    [
        ("create", lambda client: client.create("bots", {"name": "Created"})),
        ("update", lambda client: client.update("bots", "record-id", {"name": "Updated"})),
        ("delete", lambda client: client.delete("bots", "record-id")),
    ],
)
def test_mutating_operations_do_not_retry_on_server_failures(
    operation: str,
    runner: Callable[[DataverseClient], object],
) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503)

    client, provider = make_client(handler)

    with pytest.raises(DataverseApiError) as exc_info:
        runner(client)

    assert attempts == 1
    assert provider.calls == 1
    assert exc_info.value.operation == operation


def test_401_responses_raise_authentication_expired_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, headers={"x-ms-request-id": "req-401"})

    client, _ = make_client(handler)

    with pytest.raises(AuthenticationExpiredError) as exc_info:
        client.get("bots")

    assert exc_info.value.status == 401
    assert exc_info.value.operation == "read"
    assert exc_info.value.entity_set == "bots"
    assert exc_info.value.request_id == "req-401"


def test_non_auth_http_errors_raise_dataverse_api_error_with_context() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, headers={"x-ms-request-id": "req-404"})

    client, _ = make_client(handler)

    with pytest.raises(DataverseApiError) as exc_info:
        client.create("bots", {"name": "Created"})

    assert exc_info.value.status == 404
    assert exc_info.value.operation == "create"
    assert exc_info.value.entity_set == "bots"
    assert exc_info.value.request_id == "req-404"


def test_constructor_rejects_non_https_environment_urls() -> None:
    with pytest.raises(ValueError, match="env_url must be an HTTPS URL"):
        DataverseClient("http://contoso.crm.dynamics.com", FakeTokenProvider())


def test_create_returns_record_id_from_odata_entity_id_header() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            204,
            headers={"OData-EntityId": f"{ENV_URL}/api/data/v9.2/bots(12345)"},
        )

    client, _ = make_client(handler)

    record_id = client.create("bots", {"name": "Created"})

    assert record_id == "12345"
